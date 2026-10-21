"""本机 faster-whisper：逐字时间戳、听写比对、残留检查。"""
import difflib, re, subprocess, tempfile
from pathlib import Path

PAD = 0.5                                     # 听写前前后补的静音，短句才听得出来
HEAD_RESIDUE = ("开始", "始", "开", "是", "死", "此", "次", "使", "时", "思", "似", "事", "十", "10", "1")
TAIL_RESIDUE = ("结束", "结", "束")
MARKER_CHARS = set("结束节目介绍接下来谢了现在")   # 「结束」常被听成这些
DIGITS = dict(zip("零〇一二三四五六七八九十", "001234567891"))

_model = _t2s = None


def _load(model_name):
    global _model, _t2s
    if _model is None:
        from faster_whisper import WhisperModel
        from opencc import OpenCC
        _model = WhisperModel(model_name, device="cpu", compute_type="int8")
        _t2s = OpenCC("t2s")
    return _model, _t2s


def words(wav, model_name="small", language="zh"):
    """[(词, 开始秒, 结束秒)]，简体"""
    model, t2s = _load(model_name)
    padded = Path(tempfile.gettempdir()) / "narrate_pad.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-af",
                    f"adelay={int(PAD * 1000)}:all=1,apad=pad_dur={PAD}", str(padded)], check=True)
    kw = {"initial_prompt": "以下是普通话的句子。"} if language == "zh" else {}
    segs, _ = model.transcribe(str(padded), language=language, word_timestamps=True,
                               condition_on_previous_text=False, **kw)
    return [(t2s.convert(w.word).strip(" ,，。!！?？…"), float(w.start) - PAD, float(w.end) - PAD)
            for s in segs for w in s.words]


def norm(t):
    return re.sub(r"[\s\W_]+", "", t.lower())


def similarity(ref, hyp):
    """相似度：取「直接比」和「去掉英文再比」的较高者（bart 常被听成 爸 / Bud）"""
    plain = lambda s: re.sub(r"[a-z]+", "", s)
    a, b = norm(ref), norm(hyp)
    a, b = "".join(c for c in a if c not in DIGITS and not c.isdigit()), \
        "".join(c for c in b if c not in DIGITS and not c.isdigit())
    return max(difflib.SequenceMatcher(None, a, b).ratio(),
               difflib.SequenceMatcher(None, plain(a), plain(b)).ratio())


def same_last(word, body):
    """Whisper 把数字写成阿拉伯数字（四 → 4、4%），比对最后一个字时视为相同"""
    w = word.rstrip("%％.。")
    return bool(w) and bool(body) and (w[-1] == body[-1] or DIGITS.get(body[-1]) == w[-1])


def is_marker(word):
    return bool(word) and all(c in MARKER_CHARS for c in word)


def english_ok(text, hyp):
    """原文的英文要大致都在；一个多出来的中文字（bart → 爸）算 3 个字母"""
    want = len(re.findall(r"[A-Za-z]", text))
    if not want:
        return True
    got = len(re.findall(r"[A-Za-z]", hyp))
    extra = len([c for c in hyp if "一" <= c <= "鿿" and c not in text])
    return got + 3 * extra >= 0.6 * want


def residue(text, hyp):
    """回传 (开头残留, 结尾问题)；句子本身就以这些字开头/结尾时不算"""
    h, body = norm(hyp), norm(text)
    head = next((w for w in HEAD_RESIDUE if h.startswith(w) and not body.startswith(w)), "")
    tail = next((w for w in TAIL_RESIDUE if h.endswith(w) and not body.endswith(w)), "")
    if not tail and h and not same_last(h, body) and not (body[-1:].isascii() and not is_marker(h[-1:])):
        tail = f"缺尾字「{body[-1]}」"
    if not tail and not english_ok(text, hyp):
        tail = "英文不完整"
    return head, tail
