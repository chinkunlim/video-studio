#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""工作管理：建立、检查、列出工作，以及确认 review/ 里的档案。设计见 docs/DESIGN.md。

  uv run sv.py list                                        # 列出所有工作
  uv run sv.py init generate final-report --title "期末报告"  # 建立新工作（类型：extract / dub / generate）
  uv run sv.py check bart-risk-taking                      # 检查设定与输入档
  uv run sv.py approve bart-risk-taking scenes.toml        # 把 review/scenes.toml 确认后移进 input/

工作名称：小写英文、数字、连字号；可以只写名称，也可以写「类型/名称」。
"""
import argparse
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import job as J  # noqa: E402
from common.check import check_job  # noqa: E402

TEMPLATES = HERE / "templates"
INPUT_README = {
    "extract": "把要提取声音的影片放在这里，档名填进 ../job.toml 的 [inputs] video。",
    "dub": "放影片（必填）和讲稿 script.md（选填）。原片没有人声时，另外放 cues.tsv。范例在 templates/。",
    "generate": "放你有的素材：讲稿 script.md、pptx、海报 PDF、主题说明 brief.md、scenes.toml。"
                "至少要有一样。档名填进 ../job.toml 的 [inputs]。范例在 templates/。",
}


def ensure_shared(ws):
    sh = J.shared(ws)
    (sh / "voice" / "samples").mkdir(parents=True, exist_ok=True)
    if not J.vocabulary_path(ws).exists():
        shutil.copy2(TEMPLATES / "shared" / "vocabulary.tsv", J.vocabulary_path(ws))


def cmd_list(a):
    ws = J.workspace()
    jobs = J.all_jobs(ws)
    print(f"工作区：{ws}\n")
    if not jobs:
        print("还没有任何工作。用 `sv.py init <类型> <名称>` 建立。")
    for j in jobs:
        out = j.latest_output()
        print(f"{j.type:9} {j.name:28} {j.title}　{'最新成品：' + out.name if out else '还没有成品'}")


def cmd_init(a):
    if a.type not in J.TYPES:
        sys.exit(f"类型要是 {' / '.join(J.TYPES)} 其中一个")
    if not J.NAME_RE.fullmatch(a.name):
        sys.exit(f"名称「{a.name}」不合格：只能用小写英文、数字、连字号，例如 final-report。中文标题请用 --title")
    ws = J.workspace()
    d = ws / a.type / a.name
    if d.exists():
        sys.exit(f"{d} 已经存在，不会覆盖")
    for sub in ("input", "review", "work", "output"):
        (d / sub).mkdir(parents=True)
    text = (TEMPLATES / a.type / "job.toml").read_text(encoding="utf-8")
    if a.title:
        import re
        text = re.sub(r'^title = ".*?"', f'title = "{a.title}"', text, count=1, flags=re.M)
    (d / "job.toml").write_text(text, encoding="utf-8")
    tdir = TEMPLATES / a.type / "input"
    if tdir.exists():
        shutil.copytree(tdir, d / "input" / "templates")
    (d / "input" / "README.md").write_text(
        f"# input/\n\n{INPUT_README[a.type]}\n\n"
        "templates/ 里是范例（不会被使用）；照着写好之后，存在 input/ 这一层。\n", encoding="utf-8")
    ensure_shared(ws)
    print(f"已建立 {a.type}/{a.name}：{d}")
    print("下一步：")
    print(f"  1. 编辑 {d / 'job.toml'}")
    print(f"  2. 把素材放进 {d / 'input'}（范例在 input/templates/）")
    print(f"  3. uv run sv.py check {a.name}")


def cmd_check(a):
    try:
        job = J.find(a.job)
    except J.JobError as e:
        sys.exit(f"❌ {e}")
    r = check_job(job)
    print(f"{job.type}/{job.name}（{job.title}）")
    print(r.text())
    sys.exit(0 if r.ok else 1)


def cmd_approve(a):
    try:
        job = J.find(a.job)
    except J.JobError as e:
        sys.exit(f"❌ {e}")
    src = job.review / a.file
    if not src.exists():
        files = sorted(p.name for p in job.review.glob("*") if p.is_file())
        sys.exit(f"❌ review/ 里没有 {a.file}。现有：{', '.join(files) or '没有'}")
    dst = job.input / a.file
    if dst.exists():
        bak = job.input / ".previous"
        bak.mkdir(exist_ok=True)
        keep = bak / f"{dst.stem}.{time.strftime('%Y%m%d-%H%M%S')}{dst.suffix}"
        shutil.move(dst, keep)
        print(f"原本的 input/{a.file} 备份到 input/.previous/{keep.name}")
    shutil.move(src, dst)
    print(f"已确认：review/{a.file} → input/{a.file}")


def main():
    p = argparse.ArgumentParser(description="工作管理")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sp = sub.add_parser("init")
    sp.add_argument("type", choices=J.TYPES)
    sp.add_argument("name")
    sp.add_argument("--title", default="")
    sp = sub.add_parser("check")
    sp.add_argument("job")
    sp = sub.add_parser("approve")
    sp.add_argument("job")
    sp.add_argument("file", help="review/ 里的档名，例如 scenes.toml、script.md")
    a = p.parse_args()
    {"list": cmd_list, "init": cmd_init, "check": cmd_check, "approve": cmd_approve}[a.cmd](a)


if __name__ == "__main__":
    main()
