"""工作（job）：DATA_DIR 裡的一份工作，以及它的角色分層資料夾結構。

<DATA_DIR>/
├── shared/vocabulary.tsv、shared/voice/samples/
├── input/<name>/                  你提供或確認過的素材（唯讀，程式不會改）
├── needs_review/<name>/           等你確認的內容（AI 起草、試聽檔、review_history/）
├── work/<name>/                   中間檔（takes、gen、暫存），可清理重建
├── state/<name>/job.toml          這份工作的設定檔
└── output/<name>/
    ├── v1, v2, …                  歷次渲染版本庫（不覆蓋）
    └── releases/<vN>/             唯一最新定稿交付物（硬連結）
"""

from __future__ import annotations

import logging
import re
import tomllib
from pathlib import Path
from typing import Any

from video_studio.config.settings import PROJECT_ROOT, load_config

logger = logging.getLogger(__name__)

ROOT = PROJECT_ROOT  # 程式资料夹
TYPES: tuple[str, ...] = ("extract", "dub", "generate")
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


class JobError(Exception):
    """找不到工作、设定有误等，讯息直接给使用者看。"""


def workspace() -> Path:
    """資料工作區根目錄：優先使用設定覆蓋（SPLIT_VOICE_WORKSPACE），否則使用 DATA_DIR。

    Returns:
        資料根目錄絕對路徑。
    """
    cfg = load_config()
    return cfg.workspace_dir or cfg.data_dir


def shared(ws: Path | None = None) -> Path:
    """取得共用资料夹 shared/ 路径。

    Args:
        ws: 指定工作区，留空使用预设工作区。

    Returns:
        shared 资料夹路径。
    """
    return (ws or workspace()) / "shared"


def vocabulary_path(ws: Path | None = None) -> Path:
    """取得共用词汇表 shared/vocabulary.tsv 路径。

    Args:
        ws: 指定工作区，留空使用预设工作区。

    Returns:
        vocabulary.tsv 路径。
    """
    return shared(ws) / "vocabulary.tsv"


class Job:
    """表示单一制作工作，管理其设定与档案路徑。"""

    def __init__(self, path: Path | str) -> None:
        """初始化 Job 物件并载入 job.toml。

        Args:
            path: 工作资料夹路径。

        Raises:
            JobError: 找不到 job.toml 或 TOML 解析错误。
        """
        self.dir = Path(path).resolve()
        self.config_path: Path = self.dir / "job.toml"
        if not self.config_path.exists():
            raise JobError(f"{self.dir} 不是一份工作（找不到 job.toml）")
        try:
            self.cfg: dict[str, Any] = tomllib.loads(self.config_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise JobError(f"{self.config_path} 格式错误：{e}。请对照 templates/ 里的范本修正。") from e
        self.type: str = str(self.cfg.get("job", {}).get("type", ""))
        self.name: str = self.dir.name
        self.title: str = str(self.cfg.get("job", {}).get("title") or self.name)
        self._data_root: Path | None = self.dir.parent.parent if self.dir.parent.name == "state" else None

    # 资料夹
    @property
    def input(self) -> Path:
        """工作输入资料夹 input/<name>/。

        Returns:
            input 资料夹路径。
        """
        if self._data_root is not None:
            return self._data_root / "input" / self.name
        return self.dir / "input"

    @property
    def review(self) -> Path:
        """工作审核资料夹 needs_review/<name>/。

        Returns:
            needs_review 资料夹路径。
        """
        if self._data_root is not None:
            return self._data_root / "needs_review" / self.name
        return self.dir / "review"

    @property
    def work(self) -> Path:
        """工作中间档资料夹 work/<name>/。

        Returns:
            work 资料夹路径。
        """
        if self._data_root is not None:
            return self._data_root / "work" / self.name
        return self.dir / "work"

    @property
    def output(self) -> Path:
        """工作成品资料夹 output/<name>/。

        Returns:
            output 资料夹路径。
        """
        if self._data_root is not None:
            return self._data_root / "output" / self.name
        return self.dir / "output"

    @property
    def releases(self) -> Path:
        """工作定稿發布資料夾 output/<name>/releases/。

        Returns:
            releases 資料夾路徑。
        """
        return self.output / "releases"

    def input_file(self, key: str, default: str = "") -> Path | None:
        """job.toml [inputs] 里指定的档案（在 input/ 里）；没指定就回传 None。

        Args:
            key: inputs 区块中的设定键名。
            default: 预设档案名称。

        Returns:
            档案路径，若未设定则为 None。
        """
        inputs_cfg = self.cfg.get("inputs", {})
        if not isinstance(inputs_cfg, dict):
            return None
        name = str(inputs_cfg.get(key, default) or "")
        return self.input / name if name else None

    @property
    def script(self) -> Path | None:
        """讲稿档案路徑。

        Returns:
            script.md 路径或自订讲稿路径。
        """
        return self.input_file("script", "script.md")

    @property
    def takes_json(self) -> Path:
        """takes 记录档 takes.json 路径。

        Returns:
            work/takes.json 路径。
        """
        return self.work / "takes.json"

    @property
    def takes_dir(self) -> Path:
        """takes 录音档资料夹 takes/ 路径。

        Returns:
            work/takes 资料夹路径。
        """
        return self.work / "takes"

    def latest_output(self) -> Path | None:
        """取得最新的 output/vN 资料夹。

        Returns:
            最新版本目录，若无成品则回传 None。
        """
        if not self.output.exists():
            return None
        vs = [d for d in self.output.glob("v*") if d.is_dir() and d.name[1:].isdigit()]
        return max(vs, key=lambda d: int(d.name[1:])) if vs else None

    def next_output(self) -> Path:
        """取得下一个可用的 output/vN 资料夹路径。

        Returns:
            下一个版本目录路径。
        """
        n = 1
        while (self.output / f"v{n}").exists():
            n += 1
        return self.output / f"v{n}"

    def __repr__(self) -> str:
        """字串表示。

        Returns:
            工作简短描述。
        """
        return f"Job({self.type}/{self.name})"


def all_jobs(ws: Path | None = None) -> list[Job]:
    """列出資料區內所有有效工作。

    Args:
        ws: 指定資料根目錄，留空使用預設。

    Returns:
        Job 清單。
    """
    ws = ws or workspace()
    out: list[Job] = []
    seen: set[str] = set()
    state_dir = ws / "state"
    if state_dir.exists():
        for d in sorted(state_dir.glob("*")):
            if d.is_dir() and (d / "job.toml").exists():
                job = Job(d)
                out.append(job)
                seen.add(job.name)
    for t in TYPES:
        type_dir = ws / t
        if not type_dir.exists():
            continue
        for d in sorted(type_dir.glob("*")):
            if (d / "job.toml").exists() and d.name not in seen:
                out.append(Job(d))
    return out


def find(name: str, ws: Path | None = None) -> Job:
    """「名稱」「類型/名稱」或完整路徑 → Job。

    Args:
        name: 搜尋的工作名稱或路徑。
        ws: 資料根目錄。

    Returns:
        找到的 Job 實例。

    Raises:
        JobError: 找不到或有多個同名工作時。
    """
    ws = ws or workspace()
    p = Path(name).expanduser()
    if p.is_absolute() or (p / "job.toml").exists():
        return Job(p)
    if "/" in name:
        if (ws / name / "job.toml").exists():
            return Job(ws / name)
        _, short_name = name.split("/", 1)
        state_candidate = ws / "state" / short_name
        if (state_candidate / "job.toml").exists():
            return Job(state_candidate)
        return Job(ws / name)
    state_candidate = ws / "state" / name
    if (state_candidate / "job.toml").exists():
        return Job(state_candidate)
    hits = [ws / t / name for t in TYPES if (ws / t / name / "job.toml").exists()]
    if len(hits) == 1:
        return Job(hits[0])
    names = ", ".join(f"{j.type}/{j.name}" for j in all_jobs(ws)) or "沒有"
    if not hits:
        raise JobError(f"找不到工作「{name}」。資料區 {ws} 裡的工作：{names}")
    hit_names = ", ".join(str(h.relative_to(ws)) for h in hits)
    raise JobError(f"「{name}」不只一個：{hit_names}。請寫成「類型/名稱」。")
