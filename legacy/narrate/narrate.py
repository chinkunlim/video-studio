#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["faster-whisper", "opencc-python-reimplemented"]
# ///
"""工具二：讲稿 → Voicebox 配音 → 拼接 → 字幕（YouTube / PowerPoint / VLC，繁体中文）。

使用前：从 Dock 打开 Voicebox，在 app 里用声音档生成一句话（让模型载入）。
<job> = 工作名称（例如 bart-risk-taking，或 generate/bart-risk-taking），见 docs/DESIGN.md。
讲稿在 <job>/input/script.md；每句音档在 work/takes/；试听版本在 review/audition/；成品在 output/vN/。

  uv run narrate/narrate.py lines    bart-risk-taking       # 列出每一行：字幕文字 vs 送给 Voicebox 的文字
  uv run narrate/narrate.py scan     bart-risk-taking       # 检查词汇表：漏标的英文、表里没有的 key
  uv run narrate/narrate.py build    bart-risk-taking       # 生成缺少的句子 → 拼接 → 字幕，输出到 output/vN/
  uv run narrate/narrate.py audition bart-risk-taking 46 --takes 4   # 某一行生成 4 个版本给你挑
  uv run narrate/narrate.py pick     bart-risk-taking 46 2  # 选用第 2 个版本并锁定
  uv run narrate/narrate.py try "Adjusted bart" "Adjusted Bahrt" --lang en   # 试听词的写法（存到 shared/vocab_tries/）
  uv run narrate/narrate.py format   speech.txt           # 一般讲稿 → 一句一行（印出来，再存成 input/script.md）
  uv run narrate/narrate.py clean                         # 删除 Voicebox 里所有生成纪录（会先问你）
  uv run narrate/narrate.py vocab list                    # 列出词汇表（shared/vocabulary.tsv）
  uv run narrate/narrate.py vocab set Eysenck --subtitle Eysenck --tts 艾森克 --type 人名   # 新增 / 修改
"""
import argparse, csv, json, re, shutil, sys, tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent))

from core import audio, concat, generate, numbers, script, subtitles, vocab, whisper  # noqa: E402
from core.takes import Takes, key as take_key  # noqa: E402
from core.voicebox import Voicebox, VoiceboxBroken  # noqa: E402
from common import job as J  # noqa: E402

VOCAB = None                            # main() 设定：shared/vocabulary.tsv


def load_config(job=None):
    """narrate/config.toml，再套用 job.toml 的 [voice] profile 与 [output] loudness"""
    cfg = tomllib.loads((HERE / "config.toml").read_text(encoding="utf-8"))
    if job:
        if job.cfg.get("voice", {}).get("profile"):
            cfg["voicebox"]["profile"] = job.cfg["voice"]["profile"]
        if "loudness" in job.cfg.get("output", {}):
            cfg["audio"]["loudness"] = job.cfg["output"]["loudness"]
    return cfg


def load_lines(job):
    voc = vocab.load(VOCAB)
    lines = script.parse(job.script.read_text(encoding="utf-8"))
    for ln in lines:
        ln.subtitle = vocab.expand(ln.raw, voc, "subtitle")
        ln.tts = numbers.normalize(vocab.expand(ln.raw, voc, "tts"))
    return lines, voc


def takes_of(job):
    return Takes(job.dir, job.takes_json)


def cmd_lines(a):
    lines, _ = load_lines(a.job)
    takes = takes_of(a.job)
    for ln in lines:
        t = takes.get(ln.tts)
        state = "🔒" if t and t["locked"] else ("✓" if t else "·")
        print(f"{ln.no:>3} [{ln.slide:>2}] {state} {ln.subtitle}")
        if ln.tts != ln.subtitle:
            print(f"{'':10}念法：{ln.tts}")
    print("\n✓ 已有音档  🔒 已锁定  · 还没生成")


def cmd_scan(a):
    voc = vocab.load(VOCAB)
    used, problems = {}, 0
    for ln in script.parse(a.job.script.read_text(encoding="utf-8")):
        for k in vocab.used_keys(ln.raw):
            used.setdefault(k, []).append(ln.no)
            if k not in voc:
                print(f"第 {ln.no} 行：词汇表没有「{k}」")
                problems += 1
        for w in vocab.unmarked_english(ln.raw):
            print(f"第 {ln.no} 行：英文「{w}」没有放进 {{{{}}}}，可能漏标")
            problems += 1
    print("\n用到的词汇：")
    for k, nos in used.items():
        v = voc.get(k, {})
        print(f"  {{{{{k}}}}} 字幕「{v.get('subtitle', '?')}」念「{v.get('tts', '?')}」"
              f"{'' if v.get('tested') else '（未试听）'}  第 {', '.join(map(str, nos))} 行")
    print(f"\n{'没有问题' if not problems else f'有 {problems} 个地方要检查'}")


def cmd_build(a):
    job = a.job
    cfg = load_config(job)
    lines, voc = load_lines(job)
    takes = takes_of(job)
    missing = [ln for ln in lines if not takes.get(ln.tts)]
    if missing:
        print(f"要生成 {len(missing)} 句：{', '.join(str(ln.no) for ln in missing)}")
        vb = Voicebox(cfg["voicebox"])
        try:
            vb.check_ready()
            for ln in missing:
                print(f"[{ln.no}] {ln.tts}", flush=True)
                res = generate.take(vb, ln.tts, job.work / "gen" / take_key(ln.tts), cfg)
                if not res:
                    print("    全部失败：这句之后可用 audition 多试几次，或改写法")
                    continue
                dest = generate.store(res[0], job.takes_dir / f"{take_key(ln.tts)}.wav")
                takes.put(ln.tts, dest, res[0]["words"], f"build 写法{res[0]['wrap']}", res[0]["sim"])
        except VoiceboxBroken as e:
            sys.exit(f"\n停止：{e}\n已完成的句子都保留了，处理好之后再执行一次 build。")
        finally:
            vb.sweep()
    still = [ln.no for ln in lines if not takes.get(ln.tts)]
    if still:
        sys.exit(f"还有 {len(still)} 句没有音档（{', '.join(map(str, still))}），先处理再拼接。")

    out = job.next_output()
    out.mkdir(parents=True)
    items = [{"no": ln.no, "slide": ln.slide, "brk": ln.brk, "clip": job.dir / takes.get(ln.tts)["clip"]}
             for ln in lines]
    timeline = concat.build(items, cfg["pause"], out / "narration.wav", out / "tmp",
                            cfg["audio"]["loudness"], cfg["audio"]["sample_rate"])
    shutil.rmtree(out / "tmp")
    sub_lines = []
    for ln, tl in zip(lines, timeline):
        t = takes.get(ln.tts)
        if not t.get("words"):                          # 汇入的旧音档没有逐字时间戳 → 补上
            t["words"] = whisper.words(job.dir / t["clip"], cfg["whisper"]["model"])
            takes.save()
        sub_lines.append({"text": ln.subtitle, "words": t["words"], **tl})
    cues = subtitles.to_traditional(subtitles.build_cues(sub_lines, cfg), cfg, HERE / "traditional_fixes.tsv")
    files = subtitles.write_all(cues, out, cfg, job.title)
    with open(out / "tts_vs_subtitle.tsv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["行", "投影片", "开始", "结束", "字幕（讲稿）", "Voicebox 念法", "不同", "来源", "Whisper 听写"])
        for ln, tl in zip(lines, timeline):
            t = takes.get(ln.tts)
            hyp = "".join(x[0] for x in t["words"])
            w.writerow([ln.no, ln.slide, tl["start"], tl["end"], ln.subtitle, ln.tts,
                        "是" if ln.tts != ln.subtitle else "", t["source"], hyp])
    (out / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.copy2(job.script, out / "script.md")
    shutil.copy2(VOCAB, out / "vocabulary.tsv")
    print(f"\n完成：{out}/")
    print(f"  narration.wav（配音，{audio.duration(out / 'narration.wav') / 60:.1f} 分钟，{len(lines)} 句）")
    print(f"  字幕 {len(cues)} 条：{'、'.join(files)}")
    print("  tts_vs_subtitle.tsv（字幕与念法对照）、timeline.json，以及这次用的 script.md / vocabulary.tsv")


def cmd_audition(a):
    job = a.job
    cfg = load_config(job)
    lines, _ = load_lines(job)
    if not 1 <= a.line <= len(lines):
        sys.exit(f"没有第 {a.line} 行（讲稿共 {len(lines)} 行）")
    ln = lines[a.line - 1]
    vb = Voicebox(cfg["voicebox"])
    try:
        vb.check_ready()
    except VoiceboxBroken as e:
        sys.exit(str(e))
    print(f"[{ln.no}] {ln.tts}")
    try:
        res = generate.take(vb, ln.tts, job.work / "gen" / take_key(ln.tts), cfg,
                            tries=len(generate.WRAPS), keep_all=True)[:a.takes]
    finally:
        vb.sweep()
    dest_dir = job.review / "audition" / f"line{ln.no:03d}"
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True)
    meta = []
    for k, r in enumerate(res, 1):
        dest = generate.store(r, dest_dir / f"{k}.wav")
        meta.append({"take": k, "file": str(dest.relative_to(job.dir)), "words": r["words"],
                     "sim": r["sim"], "wrap": r["wrap"], "hyp": r["hyp"]})
        print(f"  {dest}  ｜{r['hyp']}")
    (dest_dir / "takes.json").write_text(json.dumps({"tts": ln.tts, "takes": meta}, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    print(f"\n听完后：uv run narrate/narrate.py pick {job.name} {ln.no} <编号>")


def cmd_pick(a):
    job = a.job
    lines, _ = load_lines(job)
    if not 1 <= a.line <= len(lines):
        sys.exit(f"没有第 {a.line} 行（讲稿共 {len(lines)} 行）")
    ln = lines[a.line - 1]
    d = job.review / "audition" / f"line{ln.no:03d}"
    if not (d / "takes.json").exists():
        sys.exit(f"第 {ln.no} 行还没有试听版本，请先 audition")
    meta = json.loads((d / "takes.json").read_text(encoding="utf-8"))
    if meta["tts"] != ln.tts:
        sys.exit("这一行的念法在试听后改过了，请重新 audition")
    m = next((x for x in meta["takes"] if x["take"] == a.take), None)
    if m is None:
        sys.exit(f"没有第 {a.take} 个版本（共 {len(meta['takes'])} 个）")
    dest = job.takes_dir / f"{take_key(ln.tts)}.wav"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(job.dir / m["file"], dest)
    takes_of(job).put(ln.tts, dest, m["words"], f"audition 第{a.take}个", m["sim"], locked=True)
    print(f"第 {ln.no} 行改用第 {a.take} 个版本，并锁定。下次 build 会用它。")


def cmd_try(a):
    cfg = load_config()
    vb = Voicebox(cfg["voicebox"])
    try:
        vb.check_ready()
    except VoiceboxBroken as e:
        sys.exit(str(e))
    out = Path(a.out).expanduser() if a.out else J.shared() / "vocab_tries"
    out.mkdir(parents=True, exist_ok=True)
    carrier = a.carrier or ("我们把它叫做 {}，请记住。" if a.lang == "zh" else "We call it the {}, okay.")
    try:
        for k, spelling in enumerate(a.spellings, 1):
            f = out / f"{a.lang}{k:02d}.wav"
            f.write_bytes(vb.generate(carrier.format(spelling), language=a.lang))
            print(f"{f}  {carrier.format(spelling)}")
    finally:
        vb.sweep()
    print("\n挑好之后：uv run narrate/narrate.py vocab set <key> --tts <写法> --tested <日期>")


def cmd_clean(a):
    """删除 Voicebox 里所有生成纪录（音档都已经存在专案里了）"""
    vb = Voicebox(load_config()["voicebox"])
    items = vb.history()
    busy = sum(1 for h in items if h.get("status") == "generating")
    if not items:
        print("Voicebox 里没有生成纪录。")
        return
    print(f"Voicebox 里有 {len(items)} 笔生成纪录（生成中 {busy} 笔会跳过）。")
    if not a.yes and input("全部删除？删除后无法复原 [y/N] ").strip().lower() != "y":
        print("取消。")
        return
    done, skipped = vb.clear(keep_favorites=a.keep_favorites)
    print(f"已删除 {done} 笔，跳过 {skipped} 笔。")


def cmd_vocab(a):
    """列出词汇表，或新增 / 修改一个词"""
    path = VOCAB
    voc = vocab.load(path)
    if a.action == "list":
        for k, v in voc.items():
            print(f"{{{{{k}}}}}\t{v['type']}\t字幕「{v['subtitle']}」\t念「{v['tts']}」\t"
                  f"{'试听 ' + v['tested'] if v['tested'] else '未试听'}\t{v['note']}")
        return
    if not a.key or not re.fullmatch(r"[A-Za-z0-9_]+", a.key):
        sys.exit("key 只能用英文字母、数字、底线，例如 Adjusted_BART")
    old = voc.get(a.key)
    if old is None and not a.subtitle:
        sys.exit(f"新词「{a.key}」至少要给 --subtitle（字幕显示的文字）")
    row = old or {k: "" for k in vocab.FIELDS}
    row["key"] = a.key
    for f in ("type", "subtitle", "tts", "tested", "note"):
        if getattr(a, f) is not None:
            row[f] = getattr(a, f)
    row["tts"] = row["tts"] or row["subtitle"]
    row["tts_lang"] = row["tts_lang"] or "zh"
    voc[a.key] = row
    vocab.save(path, voc)
    print(f"{'修改' if old else '新增'}：{{{{{a.key}}}}} 字幕「{row['subtitle']}」念「{row['tts']}」")
    print("讲稿里写 {{" + a.key + "}} 就会套用；改了念法的句子，下次 build 会自动重做。")


def cmd_format(a):
    print(script.split_sentences(Path(a.file).read_text(encoding="utf-8")))


def main():
    p = argparse.ArgumentParser(description="讲稿 → Voicebox 配音 + 字幕")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("lines", "scan", "build"):
        sp = sub.add_parser(name)
        sp.add_argument("job")
    sp = sub.add_parser("audition")
    sp.add_argument("job")
    sp.add_argument("line", type=int)
    sp.add_argument("--takes", type=int, default=4)
    sp = sub.add_parser("pick")
    sp.add_argument("job")
    sp.add_argument("line", type=int)
    sp.add_argument("take", type=int)
    sp = sub.add_parser("try")
    sp.add_argument("spellings", nargs="+")
    sp.add_argument("--lang", default="zh")
    sp.add_argument("--carrier", help="句型，用 {} 代表词，例如「这个分数就叫 {}。」")
    sp.add_argument("--out", help="存放试听档的资料夹（预设：工作区的 shared/vocab_tries/）")
    sp = sub.add_parser("clean", help="删除 Voicebox 里所有生成纪录")
    sp.add_argument("--yes", action="store_true", help="不再询问，直接删除")
    sp.add_argument("--keep-favorites", action="store_true", help="保留在 Voicebox 里加星号的")
    sp = sub.add_parser("format")
    sp.add_argument("file")
    sp = sub.add_parser("vocab", help="列出词汇表，或新增 / 修改一个词")
    sp.add_argument("action", choices=["list", "set"])
    sp.add_argument("key", nargs="?")
    sp.add_argument("--subtitle", help="字幕显示的文字")
    sp.add_argument("--tts", help="送给 Voicebox 念的文字（预设同字幕）")
    sp.add_argument("--type", help="缩写 / 人名 / 术语…")
    sp.add_argument("--tested", help="试听通过的日期，例如 2026-10-18")
    sp.add_argument("--note")
    a = p.parse_args()
    global VOCAB
    VOCAB = J.vocabulary_path()
    if a.cmd in ("lines", "scan", "build", "audition", "pick", "vocab") and not VOCAB.exists():
        sys.exit(f"找不到词汇表 {VOCAB}。请从 templates/shared/vocabulary.tsv 复制一份，或执行 sv.py init 建立工作区")
    if getattr(a, "job", None):
        try:
            a.job = J.find(a.job)
        except J.JobError as e:
            sys.exit(f"❌ {e}")
        if not a.job.script or not a.job.script.exists():
            sys.exit(f"❌ 找不到讲稿 {a.job.script}（job.toml 的 [inputs] script）")
    {"lines": cmd_lines, "scan": cmd_scan, "build": cmd_build, "audition": cmd_audition,
     "pick": cmd_pick, "try": cmd_try, "clean": cmd_clean, "format": cmd_format,
     "vocab": cmd_vocab}[a.cmd](a)


if __name__ == "__main__":
    main()
