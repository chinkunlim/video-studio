"""数字的念法：只用在送给 Voicebox 的文字，字幕照讲稿显示。

  二〇〇二年 → 二零零二年      2002年 → 二零零二年（年份逐字念）
  86 → 八十六                 5.7% → 百分之五点七        29 → 二十九
英文字母旁边的数字不动（例如 H1），交给词汇表处理。
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

D = "零一二三四五六七八九"


def integer(n: int) -> str:
    """0–99999999 的中文念法。

    Args:
        n: 待转换的整数。

    Returns:
        中文字串。
    """
    if n == 0:
        return "零"
    if n >= 10000:
        hi, lo = divmod(n, 10000)
        prefix = "两" if hi == 2 else integer(hi)
        suffix = "" if lo == 0 else ("零" if lo < 1000 else "") + integer(lo)
        return prefix + "万" + suffix
    out, zero = "", False
    for unit, val in (("千", 1000), ("百", 100), ("十", 10), ("", 1)):
        q, n = divmod(n, val)
        if q:
            if zero:
                out += "零"
            out += ("两" if q == 2 and unit == "千" else D[q]) + unit
            zero = False
        elif out:
            zero = True
    return out[1:] if out.startswith("一十") else out


def number(s: str) -> str:
    """浮点数或整数字串转中文念法。

    Args:
        s: 包含数字的字串（如 "5.7" 或 "86"）。

    Returns:
        转换后的中文念法字串。
    """
    if "." in s:
        a, b = s.split(".", 1)
        return integer(int(a)) + "点" + "".join(D[int(c)] for c in b)
    return integer(int(s))


def normalize(text: str) -> str:
    """将讲稿文本中的阿拉伯数字转为 Voicebox 发音中文。

    Args:
        text: 原始讲稿文字。

    Returns:
        转换数字后的文字。
    """
    text = text.replace("〇", "零")
    text = re.sub(
        r"(?<![A-Za-z\d])(\d{4})(?=\s*年)",
        lambda m: "".join(D[int(c)] for c in m.group(1)),
        text,
    )
    text = re.sub(
        r"(?<![A-Za-z\d])(\d+(?:\.\d+)?)\s*%",
        lambda m: "百分之" + number(m.group(1)),
        text,
    )
    text = re.sub(
        r"(?<![A-Za-z\d.])(\d+(?:\.\d+)?)(?![A-Za-z\d])",
        lambda m: number(m.group(1)),
        text,
    )
    text = re.sub(r"(?<=[一-鿿]) +(?=[一-鿿])", "", text)  # 中文之间多余的空格
    return text
