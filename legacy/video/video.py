#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow", "pymupdf", "opencc-python-reimplemented", "lxml"]
# ///
"""工具三：配音 + 画面 → 完整影片。先用 narrate.py build 产生配音（output/vN/）。

<job> = 工作名称（例如 bart-risk-taking）。素材由 job.toml 的 [inputs] 指定（pptx、poster、scenes）。

  uv run video/video.py timing  <job>                 # 每一页的起止时间与长度
  uv run video/video.py scenes  <job>                 # 起草分镜到 review/scenes.toml + review/scenes_preview.jpg
                                                       #   pptx 是「同一张海报不同裁切」→ 从 pptx 读（V2）；
                                                       #   否则海报 PDF 有文字 → 依讲稿对到段落（V3）；都不行才平均分配
  uv run video/video.py preview <job> [--review]      # 把每一幕的区域画在海报上（预设看 input/，--review 看 review/）
  uv run video/video.py poster  <job>                 # 海报影片（用 input/scenes.toml）：渲染 → 合成配音 → 烧字幕 → 验收
  uv run video/video.py pptx    <job>                 # PowerPoint 汇出：移除内嵌录音 → 依配音设定换页与 [click] → 汇出 → 合成
  uv run video/video.py mux     <job> --video x.mp4   # 外部画面 + 配音
  uv run video/video.py check   <job>                 # 验收最新的 video.mp4

成品放在配音同一个版本资料夹：<job>/output/vN/
  video.mp4、video_subtitled.mp4、video_check.txt、video_contact_sheet.jpg、slide_timing.tsv
"""
import argparse, csv, importlib.util, shutil, sys, time, tomllib
from types import SimpleNamespace
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent))

from engine import align, media, poster, pptx, storyboard, timing  # noqa: E402
from common import job as J, material  # noqa: E402

_spec = importlib.util.spec_from_file_location("sv_vocab", HERE.parent / "narrate" / "core" / "vocab.py")
vocab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vocab)


def load_cfg():
    cfg = tomllib.loads((HERE / "config.toml").read_text(encoding="utf-8"))
    cfg["fixes_path"] = str(HERE.parent / "narrate" / "traditional_fixes.tsv")
    return cfg


def get_job(name):
    try:
        return J.find(name)
    except J.JobError as e:
        sys.exit(f"❌ {e}")


def context(a):
    cfg = load_cfg()
    job = get_job(a.job)
    try:
        v = timing.latest_version(job.output, getattr(a, "version", None))
        nd = media.duration(v / "narration.wav")
        slides = timing.slides(v, nd, cfg["output"]["tail"])
    except (FileNotFoundError, ValueError) as e:
        sys.exit(f"❌ {e}")
    return cfg, job, v, nd, slides


def need_input(job, key, label):
    p = job.input_file(key)
    if not p:
        sys.exit(f"❌ job.toml 的 [inputs] {key} 是空的：请把{label}放进 input/，并填上档名")
    if not p.exists():
        sys.exit(f"❌ 找不到{label}：{p}（job.toml 的 [inputs] {key}）")
    return p


def write_timing(v, slides):
    with open(v / "slide_timing.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["slide", "start", "end", "duration", "lines", "clicks_from_slide_start"])
        for s in slides:
            w.writerow([s.slide, f"{s.start:.2f}", f"{s.end:.2f}", f"{s.duration:.2f}", len(s.lines),
                        " ".join(f"{c:.2f}" for c in s.clicks)])


def cmd_timing(a):
    cfg, job, v, nd, slides = context(a)
    write_timing(v, slides)
    print(f"配音：{v / 'narration.wav'}（{nd:.2f} 秒）\n")
    print("投影片  开始     结束    长度(秒)  句数  [click] 在页内第几秒")
    for s in slides:
        print(f"{s.slide:>4}  {s.start:7.2f}  {s.end:7.2f}  {s.duration:7.2f}  {len(s.lines):>4}  "
              f"{', '.join(f'{c:.2f}' for c in s.clicks) or '-'}")
    print(f"\n已存成 {v / 'slide_timing.tsv'}")


def script_slides(job):
    """讲稿每一页的文字（字幕显示的写法）；起草分镜只需要讲稿，不需要先配音"""
    if not job.script or not job.script.exists():
        sys.exit("❌ 还没有讲稿 input/script.md：先写讲稿，或用 `sv.py draft` 起草后确认")
    voc = vocab.load(J.vocabulary_path())
    texts = {}
    for ln in timing.parse(job.script.read_text(encoding="utf-8")):
        texts.setdefault(ln.slide, []).append(vocab.expand(ln.raw, voc, "subtitle"))
    return texts


def cmd_scenes(a):
    cfg = load_cfg()
    job = get_job(a.job)
    texts = script_slides(job)
    slides = [SimpleNamespace(slide=n) for n in sorted(texts)]
    dst = job.review / "scenes.toml"
    job.review.mkdir(exist_ok=True)
    if dst.exists() and not a.force:
        sys.exit(f"❌ {dst} 已经存在，不会覆盖（要重做请加 --force）")
    p = job.input_file("pptx")
    pf = job.input_file("poster")
    source = a.source
    if source == "auto":
        if p and p.exists() and storyboard.read(p)["storyboard_like"]:
            source = "pptx"
        elif pf and pf.exists() and pf.suffix.lower() == ".pdf" and material.poster_layout(pf):
            source = "text"
        else:
            source = "even"
    if source == "pptx":
        p = need_input(job, "pptx", " pptx")
        info = storyboard.read(p)
        if not info["storyboard_like"]:
            print("⚠️ 这份 pptx 不是「每一页都是同一张图」的分镜型，读出来的区域可能不对；有动画的简报建议用 video.py pptx")
        if len(info["pages"]) != len(slides):
            sys.exit(f"❌ pptx 有 {len(info['pages'])} 页，讲稿有 {len(slides)} 页，要一样多")
        storyboard.write_scenes(info, dst, p.name)
        print(f"已从 {p.name} 读出 {len(info['pages'])} 幕的镜头位置与提示栏 → {dst}")
    elif source == "text":
        pf = need_input(job, "poster", "海报")
        blocks = material.poster_layout(pf)
        if not blocks:
            sys.exit(f"❌ {pf.name} 没有文字层（可能是扫描或转成图片的 PDF），没办法对位；改用 --source even")
        result = align.align({n: "".join(t) for n, t in texts.items()}, blocks, material.sections(blocks))
        intents = {n: t[0][:30] for n, t in texts.items()}
        align.write_scenes(result, intents, dst, pf.name)
        low = [n for n, r in result.items() if r["confidence"] == "低"]
        print(f"已依讲稿文字对到 {pf.name} 的段落，起草 {len(slides)} 幕 → {dst}")
        for n, r in sorted(result.items()):
            print(f"  投影片 {n:2}：{r['matched']}（信心：{r['confidence']}）")
        if low:
            print(f"⚠️ 投影片 {', '.join(map(str, low))} 信心低，请特别看预览图")
    else:
        pf = need_input(job, "poster", "海报")
        img = poster.load_poster(pf, cfg["camera"]["raster_width"])
        poster.write_template(dst, slides, img.size)
        print(f"已起草 {dst}（{len(slides)} 幕，先把海报由上到下平均分配，需要调整）")
    _preview(cfg, job, dst)
    print(f"\n请确认 review/scenes.toml 与 review/scenes_preview.jpg，没问题就执行：\n  uv run sv.py approve {job.name} scenes.toml")


def _preview(cfg, job, scenes_path):
    pf = need_input(job, "poster", "海报")
    scenes, _ = poster.read_scenes(scenes_path)
    img = poster.load_poster(pf, cfg["camera"]["raster_width"])
    out = job.review / "scenes_preview.jpg"
    poster.preview(img, {n: s for n, s in scenes.items() if s.get("visual", "poster") == "poster"}, out)
    print(f"区域预览：{out}")


def cmd_preview(a):
    cfg = load_cfg()
    job = get_job(a.job)
    sp = job.review / "scenes.toml" if a.review else (job.input_file("scenes") or job.input / "scenes.toml")
    try:
        _preview(cfg, job, sp)
    except FileNotFoundError as e:
        sys.exit(f"❌ {e}")


def finish(cfg, job, v, slides, picture, bottom_reserved):
    """画面 → 合成配音 → 烧字幕 → 验收"""
    work = job.work / "video"
    out = v / "video.mp4"
    print("合成配音…", flush=True)
    media.mux(picture, v / "narration.wav", out, slides[-1].end, cfg)
    burn = job.cfg.get("subtitles", {}).get("burn_in", True)
    if burn:
        print("烧字幕…", flush=True)
        media.burn_subtitles(out, v / "subtitles_vlc.srt", v / "video_subtitled.mp4", cfg, work / "subs",
                             bottom_reserved)
    print("验收…", flush=True)
    ok, report = media.check(out, v / "narration.wav", slides, v / "video_contact_sheet.jpg", work / "thumbs")
    (v / "video_check.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    write_timing(v, slides)
    shutil.rmtree(work, ignore_errors=True)
    backup = job.cfg.get("output", {}).get("backup_dir", "")
    if backup:
        dst = Path(backup).expanduser() / job.name / v.name
        dst.mkdir(parents=True, exist_ok=True)
        for f in ("video.mp4", "video_subtitled.mp4"):
            if (v / f).exists():
                shutil.copy2(v / f, dst / f)
        report.append(f"已复制成品到备份资料夹：{dst}")
    print("\n".join(report))
    print(f"\n{'完成' if ok else '完成，但验收有问题'}：{v}/")
    print("  video.mp4（不含字幕）" + ("、video_subtitled.mp4（字幕烧进画面）" if burn else ""))
    print("  video_check.txt、video_contact_sheet.jpg（请用眼睛检查）、slide_timing.tsv")
    if not backup:
        print("提醒：把成品复制到你会备份的地方（或在 job.toml 设定 [output] backup_dir）。")
    if not ok:
        sys.exit(1)


def cmd_poster(a):
    cfg, job, v, nd, slides = context(a)
    sp = job.input_file("scenes") or job.input / "scenes.toml"
    try:
        scenes, style = poster.read_scenes(sp)
    except FileNotFoundError as e:
        sys.exit(f"❌ {e}")
    pf = need_input(job, "poster", "海报")
    print(f"海报：{pf}")
    img = poster.load_poster(pf, cfg["camera"]["raster_width"])
    o = cfg["output"]
    cfg = poster.apply_style(cfg, style, (o["width"], o["height"]))
    work = job.work / "video"
    work.mkdir(parents=True, exist_ok=True)
    picture = work / "picture.mp4"
    t0 = time.time()
    print(f"渲染画面（{slides[-1].end:.0f} 秒，{len(slides)} 幕）…", flush=True)
    try:
        n = poster.render(cfg, img, scenes, slides, picture)
    except ValueError as e:
        sys.exit(f"❌ {e}")
    print(f"  {n} 格，{time.time() - t0:.0f} 秒", flush=True)
    has_bar = any(s.get("callout") for s in scenes.values())
    finish(cfg, job, v, slides, picture, cfg["callout"]["height"] if has_bar else 0)


def cmd_pptx(a):
    cfg, job, v, nd, slides = context(a)
    src = need_input(job, "pptx", " pptx")
    work = job.work / "video"
    work.mkdir(parents=True, exist_ok=True)
    clean, timed, exported = work / "slides_nomedia.pptx", work / "slides_timed.pptx", work / "pptx_export.mp4"
    try:
        n = pptx.strip_media(src, clean)
        if n:
            print(f"已移除 {n} 个内嵌音档／影片（避免旧录音跟新配音一起播出）")
        counts = pptx.click_counts(clean)
        print(f"pptx：{src.name}（{len(counts)} 页，点击动画 {sum(counts)} 个）")
        pptx.retime(clean, timed, [s.clicks for s in slides])
    except ValueError as e:
        sys.exit(f"❌ {e}")
    print("PowerPoint 汇出影片中（PowerPoint 会自动打开，请不要操作它）…", flush=True)
    t0 = time.time()
    try:
        pptx.export(timed, [s.duration for s in slides], exported)
    except RuntimeError as e:
        sys.exit(f"❌ {e}")
    print(f"  汇出完成，{media.duration(exported):.2f} 秒（{time.time() - t0:.0f} 秒）", flush=True)
    finish(cfg, job, v, slides, exported, a.reserve_bottom)


def cmd_mux(a):
    cfg, job, v, nd, slides = context(a)
    pic = Path(a.video).expanduser()
    if not pic.is_absolute():
        pic = job.input / pic
    if not pic.exists():
        sys.exit(f"❌ 找不到影片：{pic}")
    pd = media.duration(pic)
    print(f"画面：{pic}（{pd:.2f} 秒）；配音 {nd:.2f} 秒，影片会是 {slides[-1].end:.2f} 秒")
    if abs(pd - slides[-1].end) > 2:
        print(f"⚠️ 画面和配音长度差了 {pd - slides[-1].end:+.1f} 秒，画面和声音可能对不上。")
    finish(cfg, job, v, slides, pic, a.reserve_bottom)


def cmd_check(a):
    cfg, job, v, nd, slides = context(a)
    if not (v / "video.mp4").exists():
        sys.exit(f"❌ {v} 里还没有 video.mp4")
    ok, report = media.check(v / "video.mp4", v / "narration.wav", slides, v / "video_contact_sheet.jpg",
                             job.work / "video" / "thumbs")
    print("\n".join(report))
    sys.exit(0 if ok else 1)


def main():
    p = argparse.ArgumentParser(description="配音 + 画面 → 完整影片")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("timing", "poster", "check"):
        sp = sub.add_parser(name)
        sp.add_argument("job")
        sp.add_argument("--version", help="用哪个配音版本，例如 v2（预设最新）")
    sp = sub.add_parser("scenes")
    sp.add_argument("job")
    sp.add_argument("--source", choices=["auto", "pptx", "text", "even"], default="auto",
                    help="auto：pptx 是分镜型就从 pptx 读；否则海报 PDF 有文字就依讲稿对位（text）；都不行才平均分配（even）")
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--version")
    sp = sub.add_parser("preview")
    sp.add_argument("job")
    sp.add_argument("--review", action="store_true", help="看 review/scenes.toml（还没确认的草稿）")
    sp = sub.add_parser("pptx")
    sp.add_argument("job")
    sp.add_argument("--reserve-bottom", type=int, default=0, help="字幕要避开画面底部几像素")
    sp.add_argument("--version")
    sp = sub.add_parser("mux")
    sp.add_argument("job")
    sp.add_argument("--video", required=True, help="画面影片（完整路径，或 input/ 里的档名）")
    sp.add_argument("--reserve-bottom", type=int, default=0, help="字幕要避开画面底部几像素（例如有提示栏）")
    sp.add_argument("--version")
    a = p.parse_args()
    {"timing": cmd_timing, "scenes": cmd_scenes, "preview": cmd_preview, "poster": cmd_poster,
     "pptx": cmd_pptx, "mux": cmd_mux, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    main()
