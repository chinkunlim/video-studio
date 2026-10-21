"""讲稿格式（script.md）：

    ## 投影片 1
    大家好，我是锦坤。
    今天要来介绍一篇关于心理学家如何使用一个打气球游戏，测量人有多爱冒险的研究。

    ## 投影片 2
    这篇是 {{Lejuez}} 等人在二〇〇二年发表的文献。

规则：
- 「## 」开头的行：换投影片（标题文字随意，取其中的数字当编号）。
- 每一个非空行 = Voicebox 生成一次的单位（一句，或一句的一部分）。
- 空行 = 段落结束（停顿较长）。
- {{key}} = 词汇表里的特殊词，字幕和念法分开定义（见 vocabulary.tsv）。
- 「# 」开头（一个井号加空格）的行是注解，不会念。
- 「[click]」开头的行：念到这一行时，PowerPoint 触发下一个点击动画（影片工具用）。
  这个标记不会被念出来，也不会出现在字幕里。
"""
import re
from dataclasses import dataclass

CLICK = re.compile(r"^\s*\[click\]\s*", re.I)


@dataclass
class Line:
    no: int            # 行号（从 1 开始，给使用者指定用）
    slide: int
    raw: str           # 含 {{key}} 的原文
    brk: str           # 这行后面的停顿种类：paragraph / sentence / semicolon / comma / end
    click: bool = False  # 这行开头有 [click]：PowerPoint 在这里触发下一个点击动画


def parse(text):
    lines, slide, para = [], 0, []

    def close_para():
        for k, raw in enumerate(para):
            if k == len(para) - 1:
                brk = "paragraph"
            elif re.search(r"[。！？!?]\s*$", raw):
                brk = "sentence"
            elif re.search(r"[；：;:]\s*$", raw):
                brk = "semicolon"
            else:
                brk = "comma"
            click = bool(CLICK.match(raw))
            lines.append(Line(len(lines) + 1, slide, CLICK.sub("", raw), brk, click))
        para.clear()

    for row in text.splitlines():
        s = row.strip()
        if s.startswith("## "):
            close_para()
            m = re.search(r"\d+", s)
            slide = int(m.group()) if m else slide + 1
        elif s == "#" or s.startswith("# "):         # 注解（单独一个 # 也算）
            continue
        elif not s:
            close_para()
        else:
            para.append(s)
    close_para()
    if lines:
        lines[-1].brk = "end"
    return lines


def split_sentences(text, max_len=45):
    """把一般的讲稿（一段一段）整理成 script.md 的「一句一行」。太长的句子从逗号断开。"""
    out = []
    for para in [p.strip() for p in text.split("\n\n") if p.strip()]:
        para = para.replace("\n", "")
        for sent in re.findall(r"[^。！？；]+[。！？；]?", para):
            sent = sent.strip()
            if len(sent) <= max_len:
                out.append(sent)
                continue
            cur = ""
            for part in re.findall(r"[^，、]+[，、]?", sent):
                if cur and len(cur + part) > max_len:
                    out.append(cur)
                    cur = part
                else:
                    cur += part
            out.append(cur)
        out.append("")
    return "\n".join(out)
