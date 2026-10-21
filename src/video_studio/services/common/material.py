"""从素材读出内容：海报 PDF 的版面（文字区块、标题、栏位、阅读顺序），以及 pptx 每一页的文字与备忘稿。

海报对位（V3）和起草讲稿（S2、S3）都用这里的结果。座标一律是占海报宽、高的比例（0～1）。
"""

from __future__ import annotations

import logging
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Block:
    """海报上的单一文字区块。"""

    box: list[float]  # [x0, y0, x1, y1]，比例
    text: str
    size: float  # 区块里最大的字级（pt）
    role: str = "body"  # title / heading / body / small
    column: int = 0  # 0 = 横跨整张的区块（例如标题）；1、2… = 第几栏
    order: int = 0  # 阅读顺序

    @property
    def cx(self) -> float:
        """中心点 X 轴坐标。

        Returns:
            X 中心点比例。
        """
        return (self.box[0] + self.box[2]) / 2

    @property
    def cy(self) -> float:
        """中心点 Y 轴坐标。

        Returns:
            Y 中心点比例。
        """
        return (self.box[1] + self.box[3]) / 2


@dataclass
class Section:
    """海报上的逻辑段落或分栏。"""

    title: str
    parents: list[str]  # 上一层的标题，例如「前言」
    blocks: list[Block] = field(default_factory=list)

    @property
    def box(self) -> list[float]:
        """段落的整体外框范围。

        Returns:
            [min_x, min_y, max_x, max_y] 边界列表。
        """
        return union([b.box for b in self.blocks])

    def body(self) -> str:
        """取得段落内的主要内文文字。

        Returns:
            合并后的内文字串。
        """
        return "\n".join(b.text for b in self.blocks if b.role == "body")

    def small(self) -> str:
        """取得段落内的注释或补充小字。

        Returns:
            合并后的小字字串。
        """
        return "\n".join(b.text for b in self.blocks if b.role == "small")


def union(boxes: list[list[float]]) -> list[float]:
    """计算多个外框的并集外框。

    Args:
        boxes: 外框列表。

    Returns:
        包含所有外框的最小外框。
    """
    if not boxes:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def _clean(t: str) -> str:
    """清理文字中的软连字号与中文字换行。

    Args:
        t: 原始文字。

    Returns:
        清理后的文字。
    """
    t = t.replace("\xad", "")
    t = re.sub(r"(?<=[一-鿿，。、；：「」（）])\n(?=\S)", "", t)  # 中文换行接起来
    t = re.sub(r"[ \t]*\n[ \t]*", "\n", t)
    return t.strip()


def poster_layout(pdf: Path | str) -> list[Block]:
    """回传依阅读顺序排好的 Block 清单；没有文字层（例如扫描的图）时回传 []。

    Args:
        pdf: PDF 档案路径。

    Returns:
        排好序的 Block 列表。
    """
    import fitz

    doc = fitz.open(pdf)
    if not doc:
        return []
    page = doc[0]
    width, height = page.rect.width, page.rect.height
    blocks: list[Block] = []
    text_dict = page.get_text("dict")
    raw_blocks: list[dict[str, Any]] = text_dict.get("blocks", [])
    for b in raw_blocks:
        if b.get("type") != 0:
            continue
        lines: list[dict[str, Any]] = b.get("lines", [])
        spans: list[dict[str, Any]] = [
            s for ln in lines for s in ln.get("spans", []) if s.get("text", "").strip()
        ]
        if not spans:
            continue
        text = _clean("\n".join("".join(s.get("text", "") for s in ln.get("spans", [])) for ln in lines))
        x0, y0, x1, y1 = b.get("bbox", (0, 0, 0, 0))
        max_size = max(float(s.get("size", 10.0)) for s in spans)
        blocks.append(Block([x0 / width, y0 / height, x1 / width, y1 / height], text, max_size))
    if not blocks:
        return []
    _roles(blocks)
    _columns(blocks)
    return sorted(blocks, key=lambda b: b.order)


def _roles(blocks: list[Block]) -> None:
    """依字级分出：内文（字数最多的字级）、比内文小的（图表里的字）、比内文大的（标题）。

    Args:
        blocks: 待分类的 Block 清单。
    """
    weight: dict[float, int] = {}
    for b in blocks:
        sz = round(b.size, 1)
        weight[sz] = weight.get(sz, 0) + len(b.text)
    body = max(weight, key=lambda k: weight[k]) if weight else 12.0
    top = max(b.size for b in blocks) if blocks else body
    for b in blocks:
        if b.size < body * 0.9:
            b.role = "small"
        elif b.size > body * 1.08 and len(b.text) <= 30:
            b.role = "title" if b.size >= top * 0.95 and b.box[1] < 0.2 else "heading"


def _columns(blocks: list[Block]) -> None:
    """宽的内文区块的左缘分群 = 栏；每个区块归到中心点落在的那一栏；比一栏还宽的算横跨（0）。

    Args:
        blocks: 待划分栏位的 Block 清单。
    """
    first_y = min(
        (b.box[1] for b in blocks if b.role in ("heading", "body") and b.box[1] > 0.12),
        default=0.0,
    )
    wide = sorted(
        (b for b in blocks if b.role == "body" and 0.2 < b.box[2] - b.box[0] < 0.75 and b.box[1] >= first_y),
        key=lambda b: b.box[0],
    )
    cols: list[float] = []
    for b in wide:
        if not any(abs(b.box[0] - c) < 0.06 for c in cols):
            cols.append(b.box[0])
    cols.sort()
    for b in blocks:
        w = b.box[2] - b.box[0]
        if w > 0.7 or b.role == "title":
            b.column = 0
        else:
            nearest = min(range(len(cols)), key=lambda i: abs(b.cx - (cols[i] + 0.15))) if cols else 0
            b.column = nearest + 1

    curr = 0
    for b in sorted(blocks, key=lambda b: (b.column, b.box[1])):
        curr += 1
        b.order = curr


def pptx_slides_text(pptx_path: Path | str) -> list[dict[str, Any]]:
    """从 PowerPoint 档案解开每一页的文字与备忘稿。

    Args:
        pptx_path: PPTX 档案路径。

    Returns:
        包含每一页 slide_idx, text, notes 的字典列表。
    """
    p = Path(pptx_path)
    if not p.exists():
        return []
    slides: list[dict[str, Any]] = []

    def _slide_sort_key(n: str) -> int:
        """从 slide xml 档案名解析投影片编号作为排序键值。

        Args:
            n: 档案名称字串。

        Returns:
            投影片序号整数字。
        """
        match = re.search(r"\d+", posixpath.basename(n))
        return int(match.group()) if match else 0

    with zipfile.ZipFile(p, "r") as z:
        slide_files = sorted(
            [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")],
            key=_slide_sort_key,
        )
        for i, sf in enumerate(slide_files, start=1):
            xml_data = z.read(sf).decode("utf-8", "ignore")
            texts = re.findall(r"<a:t[^>]*>(.*?)</a:t>", xml_data)
            notes_file = f"ppt/notesSlides/notesSlide{i}.xml"
            notes_text = ""
            if notes_file in z.namelist():
                n_xml = z.read(notes_file).decode("utf-8", "ignore")
                n_texts = re.findall(r"<a:t[^>]*>(.*?)</a:t>", n_xml)
                notes_text = "".join(n_texts).strip()
            slides.append(
                {
                    "slide": i,
                    "text": "".join(texts).strip(),
                    "notes": notes_text,
                }
            )
    return slides
