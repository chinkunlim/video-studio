"""海报自动对位（V3）：把讲稿每一幕的文字，对到海报 PDF 上的段落，算出镜头框。

做法（每一步都是固定规则，同样的输入每次结果都一样）：
1. 讲稿和海报都转成简体、去掉标点，切成「两个字一组」（中文）和单字（英文、数字）。
2. 海报上越少出现的词组越有代表性（例如「收敛效度」比「风险」重要）。
3. 每一幕找出对得最好的区块，再把同一栏、上下相邻、也对得上的区块并进来。
4. 补上这一段的标题；图表里的字有对到，就把整张图框进来。
5. 对不上的幕：第一幕用海报标题区，其他沿用上一幕的位置，并标示「低信心」请你确认。
"""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import Any

from video_studio.services.common.material import Block, Section, union

logger = logging.getLogger(__name__)

_cc: Any = None


def _simplify(text: str) -> str:
    """将文字转为简体中文以利特征比对。

    Args:
        text: 原始中文文字。

    Returns:
        简体中文字串。
    """
    global _cc
    if _cc is None:
        from opencc import OpenCC

        _cc = OpenCC("t2s")
    return str(_cc.convert(text))


def tokens(text: str) -> set[str]:
    """将文本切成两个字一组的特征词集合。

    Args:
        text: 待分析文字。

    Returns:
        特征 token 集合。
    """
    t = _simplify(text).lower()
    out: set[str] = set()
    for run in re.findall(r"[一-鿿]+", t):
        out |= {run[k : k + 2] for k in range(len(run) - 1)}
    out |= set(re.findall(r"[a-z]{2,}|\d+(?:\.\d+)?", t))
    return out


def _figures(blocks: list[Block]) -> list[list[Block]]:
    """依阅读顺序，连续的小字区块（图表里的字、图说）算一张图。

    Args:
        blocks: 区块列表。

    Returns:
        图表区块群组列表。
    """
    groups: list[list[Block]] = []
    cur: list[Block] = []
    for b in blocks:
        if b.role == "small":
            cur.append(b)
        else:
            if cur:
                groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def _weights(units: list[set[str]]) -> dict[str, float]:
    """计算各词的逆向文件频率（IDF）权重。

    Args:
        units: 各单元包含的 token 集合。

    Returns:
        token 与 IDF 权重的字典。
    """
    df: dict[str, int] = {}
    for ts in units:
        for t in ts:
            df[t] = df.get(t, 0) + 1
    n = len(units)
    return {t: math.log(1.0 + n / float(c)) for t, c in df.items()}


def _sim(a: set[str], b: set[str], idf: dict[str, float]) -> float:
    """计算基于 IDF 权重的加权余弦相似度。

    Args:
        a: 集合 A。
        b: 集合 B。
        idf: IDF 权重字典。

    Returns:
        相似度浮点数。
    """
    dot = sum(idf.get(t, 0.0) ** 2 for t in a & b)
    na = math.sqrt(sum(idf.get(t, 0.0) ** 2 for t in a)) or 1.0
    nb = math.sqrt(sum(idf.get(t, 0.0) ** 2 for t in b)) or 1.0
    return dot / (na * nb)


def _order(sims: list[list[float]]) -> list[int]:
    """动态规划找出总相似度最大且顺序不倒退的分镜段落对齐路径。

    Args:
        sims: 相似度二维阵列 [幕索引][段落索引]。

    Returns:
        每一幕对应的段落索引路径。
    """
    n, m = len(sims), len(sims[0])
    dp = [[0.0] * m for _ in range(n)]
    back = [[0] * m for _ in range(n)]
    for j in range(m):
        dp[0][j] = sims[0][j]
    for i in range(1, n):
        best, arg = -1.0, 0
        for j in range(m):
            if dp[i - 1][j] > best:
                best, arg = dp[i - 1][j], j
            dp[i][j] = best + sims[i][j]
            back[i][j] = arg
    j = max(range(m), key=lambda k: dp[-1][k])
    path = [j]
    for i in range(n - 1, 0, -1):
        j = back[i][j]
        path.append(j)
    return path[::-1]


MIN_SIM = 0.06
CN_NUM = {c: k for k, c in enumerate("零一二三四五六七八九十")}


def _pad(box: list[float], pad: float) -> list[float]:
    """为外框四周增加缓冲边距。

    Args:
        box: [x0, y0, x1, y1] 外框。
        pad: 边距比例。

    Returns:
        扩张后的外框列表。
    """
    return [max(0.0, box[0] - pad), max(0.0, box[1] - pad), min(1.0, box[2] + pad), min(1.0, box[3] + pad)]


def _fig_refs(text: str) -> set[int]:
    """找出讲稿提到的图号。

    Args:
        text: 讲稿文字。

    Returns:
        引用的图号集合。
    """
    refs: set[int] = set()
    for m in re.finditer(r"[图圖]\s*([0-9]+|[一二三四五六七八九十])", text):
        v = m.group(1)
        refs.add(int(v) if v.isdigit() else CN_NUM.get(v, 0))
    return refs


def _caption_no(group: list[Block]) -> int | None:
    """从图表说明区块中提取图号。

    Args:
        group: 区块群组。

    Returns:
        图号整数或 None。
    """
    for b in group:
        m = re.match(r"[圖图]\s*([0-9]+)", b.text)
        if m:
            return int(m.group(1))
    return None


def _refine(
    sec: Section,
    slide_tok: set[str],
    tok_of: dict[int, set[str]],
    idf: dict[str, float],
    figs: list[list[Block]],
    slide_text: str = "",
    seen: Any = (),
) -> list[Block]:
    """段落很高时，只框这一幕讲到的部分。

    Args:
        sec: 段落 Section 物件。
        slide_tok: 投影片 token 集合。
        tok_of: 每个 Block 的 token 对照。
        idf: IDF 权重字典。
        figs: 图表区块列表。
        slide_text: 投影片讲稿原文。
        seen: 上一幕已看过的区块 ID 集合。

    Returns:
        精选后的 Block 列表。
    """
    box = sec.box
    if box[3] - box[1] <= 0.16:
        return sec.blocks
    groups = [g for g in figs if all(b in sec.blocks for b in g)]
    units = [[b] for b in sec.blocks if b.role == "body"] + groups
    if not units:
        return sec.blocks
    refs = _fig_refs(slide_text)
    top_w = 0.0
    scored: list[tuple[list[Block], float]] = []
    for u in units:
        t: set[str] = set().union(*(tok_of[id(b)] for b in u))
        w = sum(idf.get(x, 0.0) for x in slide_tok & t)
        if (len(u) > 1 or u[0].role == "small") and _caption_no(u) in refs:
            w += 20.0
        if id(u[0]) in seen:
            w *= 0.5
        scored.append((u, w))
        top_w = max(top_w, w)
    if top_w <= 0:
        return sec.blocks
    chosen = [b for u, score in scored if score >= 0.6 * top_w for b in u]
    top_y = min(b.box[1] for b in chosen)
    heads = [b for b in sec.blocks if b.role == "heading" and b.box[3] <= top_y + 0.001]
    if heads and top_y - max(h.box[3] for h in heads) <= 0.05:
        chosen.extend(heads)
    chosen_box = union([b.box for b in chosen])
    chosen.extend(
        [
            b
            for b in sec.blocks
            if b not in chosen and b.box[1] >= chosen_box[1] - 0.001 and b.box[3] <= chosen_box[3] + 0.001
        ]
    )
    return chosen


def align(
    slide_texts: dict[int, str],
    blocks: list[Block],
    sections: list[Section],
    pad: float = 0.012,
) -> dict[int, dict[str, Any]]:
    """比对每一幕讲稿与海报段落并计算出镜头范围。

    Args:
        slide_texts: {slide: 文字} 字典。
        blocks: 海报所有 Block 列表。
        sections: 海报所有 Section 列表。
        pad: 镜头外框缓冲距离比例。

    Returns:
        {slide: {region, confidence, matched, section}} 对齐结果字典。
    """
    btoks = [tokens(b.text) for b in blocks]
    idf = _weights(btoks)
    stoks = [tokens("\n".join(b.text for b in s.blocks)) for s in sections]
    slides = sorted(slide_texts)
    ttoks = [tokens(slide_texts[k]) for k in slides]
    sims = [[_sim(t, st, idf) for st in stoks] for t in ttoks]
    path = _order(sims)
    figs = _figures(blocks)
    tok_of = {id(b): t for b, t in zip(blocks, btoks, strict=False)}

    out: dict[int, dict[str, Any]] = {}
    prev_sec: int | None = None
    seen: set[int] = set()

    for i, slide in enumerate(slides):
        j, sim = path[i], sims[i][path[i]]
        if sim < MIN_SIM:
            j = 0 if prev_sec is None else min(prev_sec + 1, len(sections) - 1)
            sec = sections[j]
            box = sec.box
            if j == 0:
                box = [0.0, 0.0, 1.0, box[3]]
            out[slide] = {
                "region": _pad(box, pad),
                "confidence": "低",
                "section": sec.title,
                "matched": f"（对不上，先放「{sec.title}」）",
            }
            prev_sec = j
            continue
        sec = sections[j]
        chosen = _refine(
            sec,
            ttoks[i],
            tok_of,
            idf,
            figs,
            slide_texts[slide],
            seen if prev_sec == j else (),
        )
        seen = {id(b) for b in chosen}
        box = union([b.box for b in chosen])
        conf = "高" if sim >= 0.25 else ("中" if sim >= 0.12 else "低")
        out[slide] = {
            "region": _pad(box, pad),
            "confidence": conf,
            "section": sec.title,
            "matched": sec.title or chosen[0].text.replace("\n", "")[:20],
        }
        prev_sec = j
    return out


def write_scenes(
    result: dict[int, dict[str, Any]],
    slide_intents: dict[int, str],
    out_path: Path,
    poster_name: str,
) -> None:
    """将对位结果输出为 scenes.toml 草稿。

    Args:
        result: align 产生的结果字典。
        slide_intents: 每一幕讲稿说明字典。
        out_path: 目标档案路径。
        poster_name: 海报来源档名。
    """
    rows: list[str] = [
        f"# 每一幕要看海报的哪一块：依讲稿文字对到 {poster_name} 上的段落（自动起草）",
        (
            "# 请看 scenes_preview.jpg 确认框线；「confidence = 低」的幕特别要看。"
            "规则见 templates/generate/input/scenes.toml"
        ),
        "# 改完执行 video.py preview <工作> --review；确认后 sv.py approve <工作> scenes.toml",
        "",
        "[defaults]",
        'visual = "poster"',
        'callout_prefix = "✓"',
        "",
    ]
    for slide, r in sorted(result.items()):
        x0, y0, x1, y1 = r["region"]
        intent = slide_intents.get(slide, "").replace('"', "'")
        matched = str(r["matched"]).replace('"', "'")
        rows.extend(
            [
                "[[scene]]",
                f"slide = {slide}",
                f'intent = "{intent}"',
                f"region = [{x0:.4f}, {y0:.4f}, {x1 - x0:.4f}, {y1 - y0:.4f}]",
                'callout = ""',
                f'notes = "对到：{matched}；信心：{r["confidence"]}"',
                "",
            ]
        )
    out_path.write_text("\n".join(rows), encoding="utf-8")
