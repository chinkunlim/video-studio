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
import os
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # 程式资料夹
TYPES = ("extract", "dub", "generate")
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


class JobError(Exception):
    """找不到工作、设定有误等，讯息直接给使用者看"""


def workspace():
    """工作区位置：环境变数 SPLIT_VOICE_WORKSPACE 优先，其次 narrate/config.toml 的 [paths] workspace"""
    env = os.environ.get("SPLIT_VOICE_WORKSPACE")
    if env:
        return Path(env).expanduser()
    cfg = tomllib.loads((ROOT / "narrate" / "config.toml").read_text(encoding="utf-8"))
    return Path(cfg.get("paths", {}).get("workspace", "~/split-voice-workspace")).expanduser()


def shared(ws=None):
    return (ws or workspace()) / "shared"


def vocabulary_path(ws=None):
    return shared(ws) / "vocabulary.tsv"


class Job:
    def __init__(self, path):
        self.dir = Path(path)
        f = self.dir / "job.toml"
        if not f.exists():
            raise JobError(f"{self.dir} 不是一份工作（找不到 job.toml）")
        try:
            self.cfg = tomllib.loads(f.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise JobError(f"{f} 格式错误：{e}。请对照 templates/ 里的范本修正。") from e
        self.type = self.cfg.get("job", {}).get("type", "")
        self.name = self.dir.name
        self.title = self.cfg.get("job", {}).get("title") or self.name

    # 资料夹
    @property
    def input(self):
        return self.dir / "input"

    @property
    def review(self):
        return self.dir / "review"

    @property
    def work(self):
        return self.dir / "work"

    @property
    def output(self):
        return self.dir / "output"

    def input_file(self, key, default=""):
        """job.toml [inputs] 里指定的档案（在 input/ 里）；没指定就回传 None"""
        name = self.cfg.get("inputs", {}).get(key, default)
        return self.input / name if name else None

    @property
    def script(self):
        return self.input_file("script", "script.md")

    @property
    def takes_json(self):
        return self.work / "takes.json"

    @property
    def takes_dir(self):
        return self.work / "takes"

    def latest_output(self):
        vs = [d for d in self.output.glob("v*") if d.name[1:].isdigit()]
        return max(vs, key=lambda d: int(d.name[1:])) if vs else None

    def next_output(self):
        n = 1
        while (self.output / f"v{n}").exists():
            n += 1
        return self.output / f"v{n}"

    def __repr__(self):
        return f"Job({self.type}/{self.name})"


def all_jobs(ws=None):
    ws = ws or workspace()
    out = []
    for t in TYPES:
        for d in sorted((ws / t).glob("*")):
            if (d / "job.toml").exists():
                out.append(Job(d))
    return out


def find(name, ws=None):
    """「名称」「类型/名称」或完整路径 → Job"""
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
    raise JobError(f"「{name}」不只一个：{', '.join(str(h.relative_to(ws)) for h in hits)}。请写成「类型/名称」。")
