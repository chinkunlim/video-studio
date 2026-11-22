"""工作管理：建立、检查、列出工作，以及确认 review/ 里的档案。设计见 docs/DESIGN.md。

  uv run sv.py list                                        # 列出所有工作
  uv run sv.py init generate final-report --title "期末报告"  # 建立新工作（类型：extract / dub / generate）
  uv run sv.py check bart-risk-taking                      # 检查设定与输入档
  uv run sv.py approve bart-risk-taking scenes.toml        # 把 review/scenes.toml 确认后移进 input/

工作名称：小写英文、数字、连字号；可以只写名称，也可以写「类型/名称」。
"""

from __future__ import annotations

import logging
import re
import shutil
import time
from pathlib import Path

from video_studio.config.settings import PROJECT_ROOT
from video_studio.services.common import job as J
from video_studio.services.common.check import check_job

logger = logging.getLogger(__name__)

TEMPLATES = PROJECT_ROOT / "templates"
INPUT_README = {
    "extract": "把要提取声音的影片放在这里，档名填进 ../job.toml 的 [inputs] video。",
    "dub": "放影片（必填）和讲稿 script.md（选填）。原片没有人声时，另外放 cues.tsv。范例在 templates/。",
    "generate": "放你有的素材：讲稿 script.md、pptx、海报 PDF、主题说明 brief.md、scenes.toml。"
    "至少要有一样。档名填进 ../job.toml 的 [inputs]。范例在 templates/。",
}


def ensure_shared(ws: Path) -> None:
    """确保 shared/voice/samples 与 vocabulary.tsv 存在。

    Args:
        ws: 工作区路径。
    """
    sh = J.shared(ws)
    (sh / "voice" / "samples").mkdir(parents=True, exist_ok=True)
    voc_path = J.vocabulary_path(ws)
    if not voc_path.exists():
        shared_tpl = TEMPLATES / "shared" / "vocabulary.tsv"
        if shared_tpl.exists():
            shutil.copy2(shared_tpl, voc_path)
        else:
            voc_path.write_text("key\ttype\tsubtitle\ttts\ttts_lang\ttested\tnote\n", encoding="utf-8")


def list_jobs(ws: Path | None = None) -> str:
    """列出工作区内所有工作及其最新成品版本。

    Args:
        ws: 工作区路径（选填）。

    Returns:
        工作清册字串。
    """
    ws_path = ws or J.workspace()
    jobs = J.all_jobs(ws_path)
    rows: list[str] = [f"工作区：{ws_path}\n"]
    if not jobs:
        rows.append("还没有任何工作。用 `sv.py init <类型> <名称>` 建立。")
    for j in jobs:
        out = j.latest_output()
        out_str = f"最新成品：{out.name}" if out else "还没有成品"
        rows.append(f"{j.type:9} {j.name:28} {j.title}　{out_str}")
    return "\n".join(rows)


def _scaffold_job_dir(job_type: str, name: str, title: str, ws_path: Path) -> Path:
    """在 DATA_DIR 角色分層目錄建立工作目錄與 job.toml 範本。

    Args:
        job_type: 類型 ('extract', 'dub', 'generate')。
        name: 識別英文代稱。
        title: 中文標題。
        ws_path: 資料根目錄（DATA_DIR）。

    Returns:
        建立的 state/<name>/job.toml 路徑。
    """
    for sub in ("input", "needs_review", "work", "output", "state"):
        (ws_path / sub / name).mkdir(parents=True, exist_ok=True)
    (ws_path / "output" / name / "releases").mkdir(parents=True, exist_ok=True)
    tpl_file = TEMPLATES / job_type / "job.toml"
    text = (
        tpl_file.read_text(encoding="utf-8")
        if tpl_file.exists()
        else f'[job]\ntype = "{job_type}"\ntitle = "{title or name}"\n'
    )
    if title:
        text = re.sub(r'^title = ".*?"', f'title = "{title}"', text, count=1, flags=re.M)
    cfg_path = ws_path / "state" / name / "job.toml"
    cfg_path.write_text(text, encoding="utf-8")
    return cfg_path


def init_job(job_type: str, name: str, title: str = "", ws: Path | None = None) -> str:
    """建立一份新製作工作目錄與設定檔。

    Args:
        job_type: 類型 ('extract', 'dub', 'generate')。
        name: 識別英文代稱。
        title: 中文標題。
        ws: 資料根目錄路徑。

    Returns:
        建立結果文字說明。

    Raises:
        RuntimeError: 參數不合格或資料夾已存在。
    """
    if job_type not in J.TYPES:
        raise RuntimeError(f"類型要是 {' / '.join(J.TYPES)} 其中一個")
    if not J.NAME_RE.fullmatch(name):
        raise RuntimeError(f"名稱「{name}」不合格：只能用小寫英文、數字、連字號")
    ws_path = ws or J.workspace()
    state_dir = ws_path / "state" / name
    if state_dir.exists():
        raise RuntimeError(f"{state_dir} 已經存在，不會覆蓋")
    cfg_path = _scaffold_job_dir(job_type, name, title, ws_path)
    ensure_shared(ws_path)
    return (
        f"已建立 {job_type}/{name}：{state_dir}\n下一步：\n"
        f"  1. 編輯 {cfg_path}\n"
        f"  2. 把素材放進 {ws_path / 'input' / name}\n"
        f"  3. 執行 check 檢查"
    )


def check_job_status(job_name: str, ws: Path | None = None) -> tuple[bool, str]:
    """检查特定工作的输入档与设定完整性。

    Args:
        job_name: 工作名称。
        ws: 工作区路径。

    Returns:
        (是否通过, 检查报告文字) 元组。
    """
    job = J.find(job_name, ws)
    r = check_job(job)
    header = f"{job.type}/{job.name}（{job.title}）\n"
    return r.ok, header + r.text()


def approve_file(job_name: str, file_name: str, ws: Path | None = None) -> str:
    """将审核通过的草稿自 review/ 移至 input/。

    Args:
        job_name: 工作名称。
        file_name: 草稿档名。
        ws: 工作区路径。

    Returns:
        审核搬移动作报告字串。

    Raises:
        RuntimeError: 草稿档案不存在。
    """
    job = J.find(job_name, ws)
    src = job.review / file_name
    if not src.exists():
        files = sorted(p.name for p in job.review.glob("*") if p.is_file())
        raise RuntimeError(f"review/ 里没有 {file_name}。现有：{', '.join(files) or '没有'}")
    dst = job.input / file_name
    notes: list[str] = []
    if dst.exists():
        bak = job.input / ".previous"
        bak.mkdir(parents=True, exist_ok=True)
        keep = bak / f"{dst.stem}.{time.strftime('%Y%m%d-%H%M%S')}{dst.suffix}"
        shutil.move(dst, keep)
        notes.append(f"原本的 input/{file_name} 备份到 input/.previous/{keep.name}")
    shutil.move(src, dst)
    notes.append(f"已确认：review/{file_name} → input/{file_name}")
    return "\n".join(notes)
