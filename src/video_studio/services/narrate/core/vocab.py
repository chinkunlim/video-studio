"""词汇表（vocabulary.tsv）：特殊词的「字幕显示」和「Voicebox 念法」分开定义。

讲稿里写 {{key}}，产生字幕时换成 subtitle 栏，送给 Voicebox 时换成 tts 栏。
以后要换念法，只改表格，所有讲稿都会跟着变。
"""
import csv, re
from pathlib import Path

MARKER = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
FIELDS = ["key", "type", "subtitle", "tts", "tts_lang", "tested", "note"]


def load(path):
    rows = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r.get("key") and not r["key"].startswith("#"):
                rows[r["key"].strip()] = {k: (r.get(k) or "").strip() for k in FIELDS}
    return rows


def expand(raw, vocab, field):
    """把 {{key}} 换成 subtitle 或 tts 栏"""
    def sub(m):
        key = m.group(1)
        if key not in vocab:
            raise KeyError(f"词汇表里没有「{key}」：请在 vocabulary.tsv 加上这一行")
        return vocab[key][field] or vocab[key]["subtitle"]
    return MARKER.sub(sub, raw)


def used_keys(raw):
    return MARKER.findall(raw)


def unmarked_english(raw):
    """没有放进 {{}} 的英文词（可能漏标）"""
    return re.findall(r"[A-Za-z][A-Za-z.\-']*", MARKER.sub("", raw))


def save(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, FIELDS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows.values():
            w.writerow(r)
