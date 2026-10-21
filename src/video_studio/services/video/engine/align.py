"""海报自动对位（V3）：把讲稿每一幕的文字，对到海报 PDF 上的段落，算出镜头框。

做法（每一步都是固定规则，同样的输入每次结果都一样）：
1. 讲稿和海报都转成简体、去掉标点，切成「两个字一组」（中文）和单字（英文、数字）。
2. 海报上越少出现的词组越有代表性（例如「收敛效度」比「风险」重要）。
3. 每一幕找出对得最好的区块，再把同一栏、上下相邻、也对得上的区块并进来。
4. 补上这一段的标题；图表里的字有对到，就把整张图框进来。
5. 对不上的幕：第一幕用海报标题区，其他沿用上一幕的位置，并标示「低信心」请你确认。
"""
import math
import re

from common.material import union

_cc = None


def _simplify(text):
    global _cc
    if _cc is None:
        from opencc import OpenCC
        _cc = OpenCC("t2s")
    return _cc.convert(text)


def tokens(text):
    t = _simplify(text).lower()
    out = set()
    for run in re.findall(r"[一-鿿]+", t):
        out |= {run[k:k + 2] for k in range(len(run) - 1)}
    out |= {w for w in re.findall(r"[a-z]{2,}|\d+(?:\.\d+)?", t)}
    return out


def _figures(blocks):
    """依阅读顺序，连续的小字区块（图表里的字、图说）算一张图"""
    groups, cur = [], []
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


def _weights(units):
    df = {}
    for ts in units:
        for t in ts:
            df[t] = df.get(t, 0) + 1
    n = len(units)
    return {t: math.log(1 + n / c) for t, c in df.items()}


def _sim(a, b, idf):
    dot = sum(idf.get(t, 0) ** 2 for t in a & b)
    na = math.sqrt(sum(idf.get(t, 0) ** 2 for t in a)) or 1.0
    nb = math.sqrt(sum(idf.get(t, 0) ** 2 for t in b)) or 1.0
    return dot / (na * nb)


def _order(sims):
    """每一幕指定一段，段落顺序不倒退（讲解是依海报的阅读顺序走的），总相似度最大"""
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


def align(slide_texts, blocks, sections, pad=0.012):
    """slide_texts：{slide: 文字}；回传 {slide: {region, confidence, matched, section}}"""
    btoks = [tokens(b.text) for b in blocks]
    idf = _weights(btoks)
    stoks = [tokens("\n".join(b.text for b in s.blocks)) for s in sections]
    slides = sorted(slide_texts)
    ttoks = [tokens(slide_texts[k]) for k in slides]
    sims = [[_sim(t, st, idf) for st in stoks] for t in ttoks]
    path = _order(sims)
    figs = _figures(blocks)
    tok_of = {id(b): t for b, t in zip(blocks, btoks)}

    out, prev_sec, seen = {}, None, set()
    for i, slide in enumerate(slides):
        j, sim = path[i], sims[i][path[i]]
        if sim < MIN_SIM:
            # 对不上（例如开场白、结尾致谢）：第一幕看标题区，其他接着看下一段
            j = 0 if prev_sec is None else min(prev_sec + 1, len(sections) - 1)
            sec = sections[j]
            box = sec.box
            if j == 0:
                box = [0.0, 0.0, 1.0, box[3]]
            out[slide] = {"region": _pad(box, pad), "confidence": "低", "section": sec.title,
                          "matched": f"（对不上，先放「{sec.title}」）"}
            prev_sec = j
            continue
        sec = sections[j]
        chosen = _refine(sec, ttoks[i], tok_of, idf, figs, slide_texts[slide], seen if prev_sec == j else ())
        seen = {id(b) for b in chosen}
        box = union([b.box for b in chosen])
        conf = "高" if sim >= 0.25 else ("中" if sim >= 0.12 else "低")
        out[slide] = {"region": _pad(box, pad), "confidence": conf, "section": sec.title,
                      "matched": sec.title or chosen[0].text.replace("\n", "")[:20]}
        prev_sec = j
    return out


def _pad(box, pad):
    return [max(0.0, box[0] - pad), max(0.0, box[1] - pad), min(1.0, box[2] + pad), min(1.0, box[3] + pad)]


CN_NUM = {c: k for k, c in enumerate("零一二三四五六七八九十")}


def _fig_refs(text):
    """讲稿提到的图号：「图一」「圖 2」→ {1, 2}"""
    refs = set()
    for m in re.finditer(r"[图圖]\s*([0-9]+|[一二三四五六七八九十])", text):
        v = m.group(1)
        refs.add(int(v) if v.isdigit() else CN_NUM[v])
    return refs


def _caption_no(group):
    for b in group:
        m = re.match(r"[圖图]\s*([0-9]+)", b.text)
        if m:
            return int(m.group(1))
    return None


def _refine(sec, slide_tok, tok_of, idf, figs, slide_text="", seen=()):
    """段落很高时，只框这一幕讲到的部分。单位是「一段内文」或「一整张图」，取分数最高的，
    其他单位要有最高分的六成才一起框；上一幕框过的单位分数打对折（镜头往新的内容走）；
    再补上标题，以及夹在中间的区块"""
    box = sec.box
    if box[3] - box[1] <= 0.16:
        return sec.blocks
    groups = [g for g in figs if all(b in sec.blocks for b in g)]
    units = [[b] for b in sec.blocks if b.role == "body"] + groups
    if not units:
        return sec.blocks
    refs = _fig_refs(slide_text)
    top_w = 0.0
    scored = []
    for u in units:
        t = set().union(*(tok_of[id(b)] for b in u))
        w = sum(idf[x] for x in slide_tok & t)
        if len(u) > 1 or u[0].role == "small":
            if _caption_no(u) in refs:
                w += 20.0
        if id(u[0]) in seen:
            w *= 0.5
        scored.append((u, w))
        top_w = max(top_w, w)
    if top_w <= 0:
        return sec.blocks
    chosen = [b for u, w in scored if w >= 0.6 * top_w for b in u]
    top_y = min(b.box[1] for b in chosen)
    heads = [b for b in sec.blocks if b.role == "heading" and b.box[3] <= top_y + 0.001]
    if heads and top_y - max(h.box[3] for h in heads) <= 0.05:
        chosen += heads
    box = union([b.box for b in chosen])
    chosen += [b for b in sec.blocks if b not in chosen and b.box[1] >= box[1] - 0.001 and b.box[3] <= box[3] + 0.001]
    return chosen


def write_scenes(result, slide_intents, out_path, poster_name):
    rows = [f"# 每一幕要看海报的哪一块：依讲稿文字对到 {poster_name} 上的段落（自动起草）",
            "# 请看 scenes_preview.jpg 确认框线；「confidence = 低」的幕特别要看。规则见 templates/generate/input/scenes.toml",
            "# 改完执行 video.py preview <工作> --review；确认后 sv.py approve <工作> scenes.toml", "",
            "[defaults]", 'visual = "poster"', 'callout_prefix = "✓"', ""]
    for slide, r in sorted(result.items()):
        x0, y0, x1, y1 = r["region"]
        intent = slide_intents.get(slide, "").replace('"', "'")
        matched = r["matched"].replace('"', "'")
        rows += ["[[scene]]", f"slide = {slide}", f'intent = "{intent}"',
                 f"region = [{x0:.4f}, {y0:.4f}, {x1 - x0:.4f}, {y1 - y0:.4f}]", 'callout = ""',
                 f'notes = "对到：{matched}；信心：{r["confidence"]}"', ""]
    out_path.write_text("\n".join(rows), encoding="utf-8")
