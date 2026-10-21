"""检查一份工作的设定与输入档：错误讯息要说出哪个档案、第几行／第几幕、哪个栏位、该怎么改。

结果分两级：
  ❌ 错误：不修正就不能执行
  ⚠️ 提醒：可以执行，但可能不是你要的结果
"""
import csv
import importlib.util
import re
import tomllib
import zipfile
from pathlib import Path

from .job import ROOT, TYPES, Job, vocabulary_path


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


script_mod = _load("sv_script", ROOT / "narrate" / "core" / "script.py")
vocab_mod = _load("sv_vocab", ROOT / "narrate" / "core" / "vocab.py")

VISUAL_MODES = ("auto", "pptx-export", "pptx-storyboard", "poster", "html", "none")
SCENE_VISUALS = ("poster", "pptx-slide", "pptx-export", "html", "image", "video", "ai-clip")
SUPPORTED_VISUALS = ("poster",)                       # 目前已经能渲染的
SUB_FORMATS = ("youtube", "powerpoint", "vlc")
BRIEF_HEADINGS = ("主题", "观众", "长度", "用途", "语气", "一定要讲的重点", "资料来源")


class Report:
    def __init__(self):
        self.errors, self.warnings, self.notes = [], [], []

    def err(self, where, msg):
        self.errors.append(f"❌ {where}：{msg}")

    def warn(self, where, msg):
        self.warnings.append(f"⚠️ {where}：{msg}")

    def note(self, msg):
        self.notes.append(msg)

    @property
    def ok(self):
        return not self.errors

    def text(self):
        rows = self.errors + self.warnings + self.notes
        head = "✅ 检查通过" if self.ok and not self.warnings else \
            ("✅ 检查通过（有提醒）" if self.ok else f"有 {len(self.errors)} 个错误要修正")
        return "\n".join([head, *rows])


# ---------- job.toml ----------

def check_job_toml(job, r):
    f = "job.toml"
    c = job.cfg
    t = c.get("job", {}).get("type")
    if t not in TYPES:
        r.err(f, f"[job] type 要是 {' / '.join(TYPES)} 其中一个，现在是「{t}」")
        return
    if job.dir.parent.name != t:
        r.err(f, f"[job] type 是「{t}」，但这份工作放在 {job.dir.parent.name}/ 底下；两者要一致")
    if not c.get("job", {}).get("title"):
        r.warn(f, "[job] title 是空的，成品标题会用资料夹名称")
    inputs = c.get("inputs", {})
    if not isinstance(inputs, dict):
        r.err(f, "[inputs] 区段不见了，请对照范本补上")
        return
    for key, name in inputs.items():
        if name and not (job.input / name).exists():
            if key == "scenes":
                r.warn(f, f"input/{name} 还不存在：先执行 video.py scenes 起草到 review/，确认后 sv.py approve")
            else:
                r.err(f, f"[inputs] {key} = \"{name}\"，但 input/ 里找不到这个档案（没有就写 \"\"）")
    if t == "generate":
        if not any(inputs.get(k) for k in ("script", "brief", "pptx", "poster")):
            r.err(f, "[inputs] script、brief、pptx、poster 至少要有一个")
        mode = c.get("visual", {}).get("mode", "auto")
        if mode not in VISUAL_MODES:
            r.err(f, f"[visual] mode 要是 {' / '.join(VISUAL_MODES)} 其中一个，现在是「{mode}」")
    if t in ("generate", "dub"):
        if not c.get("voice", {}).get("profile"):
            r.err(f, "[voice] profile 要填 Voicebox 里复制声音的名称，例如 \"My Voice\"")
        for fmt in c.get("subtitles", {}).get("formats", []):
            if fmt not in SUB_FORMATS:
                r.err(f, f"[subtitles] formats 里的「{fmt}」不认识，只能用 {', '.join(SUB_FORMATS)}")
        loud = c.get("output", {}).get("loudness", -16)
        if not isinstance(loud, (int, float)) or not -30 <= loud <= -8:
            r.err(f, f"[output] loudness 要是 -30 到 -8 之间的数字（YouTube 用 -14、简报用 -16），现在是 {loud!r}")
    if t in ("extract", "dub") and not inputs.get("video"):
        r.err(f, "[inputs] video 必填：input/ 里的影片档名")
    if t == "dub" and not inputs.get("script") and not inputs.get("cues"):
        r.note("讲稿没有指定：执行时会先用原片逐字稿起草到 review/script.md，校对后再 approve。")


# ---------- vocabulary.tsv ----------

def check_vocabulary(path, r):
    where = f"shared/{path.name}"
    if not path.exists():
        r.err(where, "找不到词汇表。请从 templates/shared/vocabulary.tsv 复制一份")
        return {}
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    if not rows or rows[0][:4] != ["key", "type", "subtitle", "tts"]:
        r.err(where, "第 1 行（表头）要是 key、type、subtitle、tts、tts_lang、tested、note，用 Tab 分隔")
        return {}
    seen = {}
    for n, row in enumerate(rows[1:], 2):
        if not row or not row[0] or row[0].startswith("#"):
            continue
        k = row[0].strip()
        if not re.fullmatch(r"[A-Za-z0-9_]+", k):
            r.err(where, f"第 {n} 行：key「{k}」只能用英文字母、数字、底线")
        if k in seen:
            r.err(where, f"第 {n} 行：key「{k}」跟第 {seen[k]} 行重复")
        seen[k] = n
        if len(row) < 3 or not row[2].strip():
            r.err(where, f"第 {n} 行：「{k}」的 subtitle（字幕显示）是空的")
    return vocab_mod.load(path)


# ---------- script.md ----------

def check_script(path, voc, r):
    where = f"input/{path.name}"
    text = path.read_text(encoding="utf-8")
    rows = text.splitlines()
    first_slide = next((i for i, s in enumerate(rows) if s.strip().startswith("## ")), None)
    if first_slide is None:
        r.err(where, "没有任何「## 投影片 N」。每一页前面要有一行「## 投影片 1」「## 投影片 2」…")
        return []
    for i, s in enumerate(rows[:first_slide], 1):
        if s.strip() and s.strip() != "#" and not s.strip().startswith("# "):
            r.err(where, f"第 {i} 行在第一个「## 投影片」之前，不会被念。请移到投影片底下，或改成「# 」开头的注解")
    nums = []
    for i, s in enumerate(rows, 1):
        if s.strip().startswith("## "):
            m = re.search(r"\d+", s)
            if not m:
                r.err(where, f"第 {i} 行「{s.strip()}」没有页码，请写成「## 投影片 {len(nums) + 1}」")
                nums.append(len(nums) + 1)
            else:
                nums.append(int(m.group()))
    if nums != list(range(1, len(nums) + 1)):
        r.err(where, f"投影片编号要从 1 开始连续编号，现在是 {nums}")
    lines = script_mod.parse(text)
    if not lines:
        r.err(where, "没有任何要念的内容")
    for ln in lines:
        for k in vocab_mod.used_keys(ln.raw):
            if k not in voc:
                r.err(where, f"第 {ln.no} 句用到 {{{{{k}}}}}，但词汇表没有这个 key。请在 shared/vocabulary.tsv 加一行")
        for w in vocab_mod.unmarked_english(ln.raw):
            r.warn(where, f"第 {ln.no} 句的英文「{w}」没有放进 {{{{}}}}，念法可能不准")
        body = re.sub(r"[\s\W_]+", "", vocab_mod.MARKER.sub("X", ln.raw))
        if len(body) < 6:
            r.warn(where, f"第 {ln.no} 句「{ln.raw}」太短，容易生成失败，建议跟前一句合并")
    slides = sorted({ln.slide for ln in lines})
    clicks = {s: sum(1 for ln in lines if ln.slide == s and ln.click) for s in slides}
    r.note(f"讲稿：{len(slides)} 页、{len(lines)} 句；有 [click] 的页：" +
           (", ".join(f"第 {s} 页 {n} 个" for s, n in clicks.items() if n) or "没有"))
    return lines


# ---------- scenes.toml ----------

def check_scenes(path, slides, pptx_pages, job, r):
    where = f"{path.parent.name}/{path.name}"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        r.err(where, f"格式错误：{e}。常见原因：文字没加双引号、逗号用了中文全形、括号没成对")
        return
    default_visual = data.get("defaults", {}).get("visual", "poster")
    scenes = data.get("scene", [])
    if not isinstance(scenes, list) or not scenes:
        r.err(where, "没有任何 [[scene]] 区块")
        return
    seen = {}
    for k, s in enumerate(scenes, 1):
        tag = f"{where} 第 {k} 个 [[scene]]"
        n = s.get("slide")
        if not isinstance(n, int):
            r.err(tag, "slide 必填，要是整数（对应 script.md 的「## 投影片 N」）")
            continue
        tag = f"{where} 投影片 {n}"
        if n in seen:
            r.err(tag, f"重复了（第 {seen[n]} 个和第 {k} 个 [[scene]] 都是 slide = {n}）")
        seen[n] = k
        v = s.get("visual", default_visual)
        if v not in SCENE_VISUALS:
            r.err(tag, f"visual「{v}」不认识，只能用 {', '.join(SCENE_VISUALS)}")
            continue
        if v not in SUPPORTED_VISUALS:
            r.err(tag, f"visual「{v}」还没有实作，目前只能用 {', '.join(SUPPORTED_VISUALS)}")
        if v == "poster":
            reg = s.get("region")
            if not (isinstance(reg, list) and len(reg) == 4 and all(isinstance(x, (int, float)) for x in reg)):
                r.err(tag, "region 要 4 个数字 [x, y, 宽, 高]，例如 [0.0, 0.1, 1.0, 0.2]")
            else:
                x, y, w, h = reg
                if w <= 0 or h <= 0:
                    r.err(tag, f"region 的宽、高要大于 0，现在是 {reg}")
                if x < -0.5 or y < -0.5 or x + w > 1.5 or y + h > 1.5:
                    r.err(tag, f"region {reg} 超出海报太多（数值是占海报宽、高的比例，0～1）")
                elif x < -0.01 or y < -0.01 or x + w > 1.01 or y + h > 1.01:
                    r.warn(tag, f"region {reg} 有一部分在海报外面，超出的地方会显示底色")
        if v in ("pptx-slide", "pptx-export"):
            p = s.get("pptx_slide")
            if not isinstance(p, int):
                r.err(tag, "pptx_slide 必填（pptx 的第几页）")
            elif pptx_pages and not 1 <= p <= pptx_pages:
                r.err(tag, f"pptx_slide = {p}，但 pptx 只有 {pptx_pages} 页")
        if v == "html" and not s.get("on_screen"):
            r.err(tag, "on_screen 必填：画面上要出现的文字，例如 [\"标题\", \"重点一\"]")
        if v in ("image", "video"):
            m = s.get("media", "")
            if not m:
                r.err(tag, "media 必填：input/ 里的档名")
            elif not (job.input / m).exists():
                r.err(tag, f"media「{m}」在 input/ 里找不到")
        if v == "ai-clip" and not s.get("prompt"):
            r.err(tag, "prompt 必填：要生成的画面描述（英文效果较好）")
        callout = s.get("callout", "")
        if callout and len(callout.replace("\n", "")) > 40:
            r.warn(tag, f"callout 有 {len(callout)} 个字，提示栏可能放不下，建议 30 字以内")
    if slides:
        missing = [n for n in slides if n not in seen]
        extra = [n for n in seen if n not in slides]
        if missing:
            r.err(where, f"少了这些投影片：{missing}（讲稿的每一页都要有一个 [[scene]]）")
        if extra:
            r.warn(where, f"讲稿没有这些投影片，会被忽略：{extra}")


# ---------- pptx ----------

def pptx_info(path):
    """页数，以及有几个会自动播放的内嵌音档"""
    with zipfile.ZipFile(path) as z:
        slides = [n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
        media_calls = sum(z.read(n).decode("utf-8", "ignore").count('presetClass="mediacall"') for n in slides)
        return {"pages": len(slides), "media_calls": media_calls}


def check_pptx(path, script_slides, r):
    where = f"input/{path.name}"
    try:
        info = pptx_info(path)
    except zipfile.BadZipFile:
        r.err(where, "不是有效的 pptx 档案")
        return 0
    n = info["pages"]
    if script_slides and n != len(script_slides):
        r.err(where, f"pptx 有 {n} 页，讲稿有 {len(script_slides)} 页；两者要一样多（或在 scenes.toml 用 pptx_slide 指定对应）")
    if info["media_calls"]:
        r.note(f"pptx 有 {info['media_calls']} 个内嵌音档会自动播放；用 PowerPoint 汇出时会先移除，避免和新配音重叠")
    return n


# ---------- cues.tsv（dub） ----------

def _sec(t):
    t = t.strip()
    if ":" in t:
        m, s = t.split(":", 1)
        return int(m) * 60 + float(s)
    return float(t)


def check_cues(path, n_lines, r):
    where = f"input/{path.name}"
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    if not rows or rows[0][:2] != ["line", "start"]:
        r.err(where, "第 1 行（表头）要是 line、start、note，用 Tab 分隔")
        return
    prev = -1.0
    for i, row in enumerate(rows[1:], 2):
        if not row or not row[0].strip():
            continue
        try:
            no, t = int(row[0]), _sec(row[1])
        except (ValueError, IndexError):
            r.err(where, f"第 {i} 行：line 要是整数、start 要是秒数或「分:秒」，例如 1	0:05.5")
            continue
        if t <= prev:
            r.err(where, f"第 {i} 行：时间 {row[1]} 没有比上一行晚")
        prev = t
        if n_lines and not 1 <= no <= n_lines:
            r.err(where, f"第 {i} 行：line = {no}，讲稿只有 {n_lines} 句")


# ---------- brief.md ----------

def check_brief(path, r):
    where = f"input/{path.name}"
    text = path.read_text(encoding="utf-8")
    heads = {m.group(1).strip(): m.end() for m in re.finditer(r"^##\s*(.+)$", text, re.M)}
    for h in BRIEF_HEADINGS:
        if h not in heads:
            r.err(where, f"少了「## {h}」这一节（标题文字不要改，没有内容就写「无」）")


# ---------- 整份工作 ----------

def check_job(job: Job):
    r = Report()
    check_job_toml(job, r)
    if job.type not in TYPES:
        return r
    voc = check_vocabulary(vocabulary_path(), r) if job.type in ("dub", "generate") else {}
    lines = []
    if job.script and job.script.exists():
        lines = check_script(job.script, voc, r)
    slides = sorted({ln.slide for ln in lines})
    pages = 0
    p = job.input_file("pptx")
    if p and p.exists():
        pages = check_pptx(p, slides, r)
    for sc in (job.input_file("scenes"), job.review / "scenes.toml"):
        if sc and sc.exists():
            check_scenes(sc, slides, pages, job, r)
    c = job.input_file("cues")
    if c and c.exists():
        check_cues(c, len(lines), r)
    b = job.input_file("brief")
    if b and b.exists():
        check_brief(b, r)
    return r
