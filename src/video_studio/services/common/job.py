"""工作（job）：工作区里的一份工作，以及它的资料夹结构。设计见 docs/DESIGN.md。

<workspace>/
├── shared/vocabulary.tsv、shared/voice/samples/、shared/vocab_tries/
└── <type>/<name>/                 type = extract | dub | generate
    ├── job.toml                   这份工作的设定
    ├── input/                     你提供或确认过的东西（程式不会改）
    ├── review/                    等你确认的东西（AI 起草、预览图、试听档）
    ├── work/                      中间档（takes、暂存），可以删、可以重算
    └── output/v1, v2, …           成品，不覆盖
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
    """工作区位置：优先由 config 取得，其次预设路径。

    Returns:
        工作区根目录绝对路径。
    """
    cfg = load_config()
    return cfg.workspace_dir or (cfg.data_dir / "workspace")


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
        f = self.dir / "job.toml"
        if not f.exists():
            raise JobError(f"{self.dir} 不是一份工作（找不到 job.toml）")
        try:
            self.cfg: dict[str, Any] = tomllib.loads(f.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise JobError(f"{f} 格式错误：{e}。请对照 templates/ 里的范本修正。") from e
        self.type: str = str(self.cfg.get("job", {}).get("type", ""))
        self.name: str = self.dir.name
        self.title: str = str(self.cfg.get("job", {}).get("title") or self.name)

    # 资料夹
    @property
    def input(self) -> Path:
        """工作输入资料夹 input/。

        Returns:
            input 资料夹路径。
        """
        return self.dir / "input"

    @property
    def review(self) -> Path:
        """工作审核资料夹 review/。

        Returns:
            review 资料夹路径。
        """
        return self.dir / "review"

    @property
    def work(self) -> Path:
        """工作中间档资料夹 work/。

        Returns:
            work 资料夹路径。
        """
        return self.dir / "work"

    @property
    def output(self) -> Path:
        """工作成品资料夹 output/。

        Returns:
            output 资料夹路径。
        """
        return self.dir / "output"

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
    """列出工作区内所有有效工作。

    Args:
        ws: 指定工作区路径，留空使用预设。

    Returns:
        Job 清单。
    """
    ws = ws or workspace()
    out: list[Job] = []
    for t in TYPES:
        type_dir = ws / t
        if not type_dir.exists():
            continue
        for d in sorted(type_dir.glob("*")):
            if (d / "job.toml").exists():
                out.append(Job(d))
    return out


def find(name: str, ws: Path | None = None) -> Job:
    """「名称」「类型/名称」或完整路径 → Job。

    Args:
        name: 搜寻的工作名称或路径。
        ws: 工作区路径。

    Returns:
        找到的 Job 实例。

    Raises:
        JobError: 找不到或有多个同名工作时。
    """
    ws = ws or workspace()
    p = Path(name).expanduser()
    if p.is_absolute() or (p / "job.toml").exists():
        return Job(p)
    if "/" in name:
        return Job(ws / name)
    hits = [ws / t / name for t in TYPES if (ws / t / name / "job.toml").exists()]
    if len(hits) == 1:
        return Job(hits[0])
    names = ", ".join(f"{j.type}/{j.name}" for j in all_jobs(ws)) or "没有"
    if not hits:
        raise JobError(f"找不到工作「{name}」。工作区 {ws} 里的工作：{names}")
    hit_names = ", ".join(str(h.relative_to(ws)) for h in hits)
    raise JobError(f"「{name}」不只一个：{hit_names}。请写成「类型/名称」。")
