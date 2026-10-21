"""从素材读出内容：海报 PDF 的版面（文字区块、标题、栏位、阅读顺序），以及 pptx 每一页的文字与备忘稿。

海报对位（V3）和起草讲稿（S2、S3）都用这里的结果。座标一律是占海报宽、高的比例（0～1）。
"""
import posixpath
import re
import zipfile
from dataclasses import dataclass, field


@dataclass
class Block:
    box: list                 # [x0, y0, x1, y1]，比例
    text: str
    size: float               # 区块里最大的字级（pt）
    role: str = "body"        # title / heading / body / small
    column: int = 0           # 0 = 横跨整张的区块（例如标题）；1、2… = 第几栏
    order: int = 0            # 阅读顺序

    @property
    def cx(self):
        return (self.box[0] + self.box[2]) / 2

    @property
    def cy(self):
        return (self.box[1] + self.box[3]) / 2


@dataclass
class Section:
    title: str
    parents: list             # 上一层的标题，例如「前言」
    blocks: list = field(default_factory=list)

    @property
    def box(self):
        return union([b.box for b in self.blocks])

    def body(self):
        return "\n".join(b.text for b in self.blocks if b.role == "body")

    def small(self):
        return "\n".join(b.text for b in self.blocks if b.role == "small")


def union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _clean(t):
    t = t.replace("­", "")
    t = re.sub(r"(?<=[一-鿿，。、；：「」（）])\n(?=\S)", "", t)   # 中文换行接起来
    t = re.sub(r"[ \t]*\n[ \t]*", "\n", t)
    return t.strip()


def poster_layout(pdf):
    """回传依阅读顺序排好的 Block 清单；没有文字层（例如扫描的图）时回传 []"""
    import fitz
    page = fitz.open(pdf)[0]
    W, H = page.rect.width, page.rect.height
    blocks = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        spans = [s for ln in b["lines"] for s in ln["spans"] if s["text"].strip()]
        if not spans:
            continue
        text = _clean("\n".join("".join(s["text"] for s in ln["spans"]) for ln in b["lines"]))
        x0, y0, x1, y1 = b["bbox"]
        blocks.append(Block([x0 / W, y0 / H, x1 / W, y1 / H], text, max(s["size"] for s in spans)))
    if not blocks:
        return []
    _roles(blocks)
    _columns(blocks)
    return sorted(blocks, key=lambda b: b.order)


def _roles(blocks):
    """依字级分出：内文（字数最多的字级）、比内文小的（图表里的字）、比内文大的（标题）"""
    weight = {}
    for b in blocks:
        weight[round(b.size, 1)] = weight.get(round(b.size, 1), 0) + len(b.text)
    body = max(weight, key=weight.get)
    top = max(b.size for b in blocks)
    for b in blocks:
        if b.size < body * 0.9:
            b.role = "small"
        elif b.size > body * 1.08 and len(b.text) <= 30:
            b.role = "title" if b.size >= top * 0.95 and b.box[1] < 0.2 else "heading"


def _columns(blocks):
    """宽的内文区块的左缘分群 = 栏；每个区块归到中心点落在的那一栏；比一栏还宽的算横跨（0）"""
    first_y = min((b.box[1] for b in blocks if b.role in ("heading", "body") and b.box[1] > 0.12), default=0.0)
    wide = sorted((b for b in blocks if b.role == "body" and 0.2 < b.box[2] - b.box[0] < 0.75
                   and b.box[1] >= first_y), key=lambda b: b.box[0])
    cols = []
    for b in wide:
        if cols and b.box[0] - cols[-1][0] < 0.05:
            cols[-1][1] = max(cols[-1][1], b.box[2])
        else:
            cols.append([b.box[0], b.box[2]])
    if not cols:
        cols = [[0.0, 1.0]]
    # 每一栏的范围延伸到下一栏的左缘
    bounds = [(c[0] if k else 0.0, cols[k + 1][0] if k + 1 < len(cols) else 1.0) for k, c in enumerate(cols)]
    col_w = min(c[1] - c[0] for c in cols)
    for b in blocks:
        spans_all = b.box[2] - b.box[0] > col_w * 1.3
        if len(cols) > 1 and (spans_all or b.box[3] <= first_y + 0.005):
            b.column = 0
        else:
            b.column = next((k + 1 for k, (lo, hi) in enumerate(bounds) if lo <= b.cx < hi), len(cols))
    for k, b in enumerate(sorted(blocks, key=lambda b: (b.column, round(b.box[1], 3), b.box[0]))):
        b.order = k


def sections(blocks):
    """依阅读顺序，以「最小一层的标题」切成段落；只有更大的标题（例如「前言」）的会并进下一段的 parents"""
    heads = [b for b in blocks if b.role == "heading" and b.column]
    if not heads:
        return [Section("", [], [b for b in blocks if b.role != "title"])]
    leaf = min(round(b.size, 1) for b in heads)
    out, pending = [], []
    intro = Section("标题", [], [b for b in blocks if b.role == "title" or b.column == 0])
    for b in blocks:
        if b in intro.blocks:
            continue
        if b.role == "heading" and round(b.size, 1) > leaf and b.column:
            pending.append(b)
            continue
        if b.role == "heading" and b.column:
            out.append(Section(b.text, [p.text for p in pending], pending + [b]))
            pending = []
        elif pending:
            out.append(Section(pending[-1].text, [p.text for p in pending[:-1]], pending + [b]))
            pending = []
        elif out:
            out[-1].blocks.append(b)
        else:
            intro.blocks.append(b)
    return ([intro] if intro.blocks else []) + out


def poster_text(blocks):
    return "\n".join(b.text for b in blocks)


# ---------- pptx ----------

def pptx_pages(pptx):
    """每一页的 {slide, title, texts, notes}；不改动 pptx"""
    from lxml import etree
    ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
          "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
          "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
    z = zipfile.ZipFile(pptx)
    pres = etree.fromstring(z.read("ppt/presentation.xml"))
    rels = etree.fromstring(z.read("ppt/_rels/presentation.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels.findall("rel:Relationship", ns)}
    out = []
    for n, s in enumerate(pres.findall(".//p:sldIdLst/p:sldId", ns), 1):
        f = "ppt/" + target[s.get("{%s}id" % ns["r"])].lstrip("/").removeprefix("ppt/")
        root = etree.fromstring(z.read(f))
        title, texts = "", []
        for sp in root.iter("{%s}sp" % ns["p"]):
            paras = ["".join(t.text or "" for t in p.iter("{%s}t" % ns["a"])) for p in sp.iter("{%s}p" % ns["a"])]
            txt = "\n".join(p for p in paras if p.strip())
            if not txt:
                continue
            ph = sp.find(".//p:nvPr/p:ph", ns)
            if ph is not None and ph.get("type") in ("title", "ctrTitle") and not title:
                title = txt
            else:
                texts.append(txt)
        notes = ""
        rel_name = f.replace("slides/", "slides/_rels/") + ".rels"
        if rel_name in z.namelist():
            for r in etree.fromstring(z.read(rel_name)).findall("rel:Relationship", ns):
                if r.get("Type", "").endswith("/notesSlide"):
                    nf = posixpath.normpath(posixpath.join(posixpath.dirname(f), r.get("Target")))
                    if nf in z.namelist():
                        nroot = etree.fromstring(z.read(nf))
                        parts = []
                        for sp in nroot.iter("{%s}sp" % ns["p"]):
                            ph = sp.find(".//p:nvPr/p:ph", ns)
                            if ph is not None and ph.get("type") == "body":
                                parts += ["".join(t.text or "" for t in p.iter("{%s}t" % ns["a"]))
                                          for p in sp.iter("{%s}p" % ns["a"])]
                        notes = "\n".join(p for p in parts if p.strip())
        out.append({"slide": n, "title": title, "texts": texts, "notes": notes})
    return out
