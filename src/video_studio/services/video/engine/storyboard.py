"""把 pptx 当分镜（V2）：每一页都是同一张海报图、不同裁切／位置，再加提示栏与外框。

从 pptx 读出：
- 每一页镜头看海报的哪一块：投影片画面 → 透过图片的位置、大小、裁切（srcRect）换算回海报座标
- 底部提示栏的文字（多段落用换行分开）与样式：高度、底色、字色、字级、开头的 ✓
- 外框（盖在海报上、中间挖空的形状）：内缩比例与颜色
再用高解析海报（PDF）重新渲染，时间跟着新配音走；pptx 本身不会被修改。
"""

from __future__ import annotations

import logging
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from lxml import etree

logger = logging.getLogger(__name__)

NS: dict[str, str] = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
EMU_PER_PT = 12700
SYMBOL_BULLETS: dict[tuple[str, str], str] = {
    ("Wingdings", "ü"): "✓",
    ("Wingdings", "Ÿ"): "•",
    ("Wingdings", "§"): "■",
}


def _slide_files(z: zipfile.ZipFile) -> tuple[list[str], int, int]:
    """读取简报内投影片档案清册与其尺寸。

    Args:
        z: PPTX zipfile 物件。

    Returns:
        (投影片 XML 档案列表, 画面宽度 EMU, 画面高度 EMU) 元组。
    """
    pres = etree.fromstring(z.read("ppt/presentation.xml"))
    rels = etree.fromstring(z.read("ppt/_rels/presentation.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels.findall("rel:Relationship", NS)}
    files = [
        "ppt/" + str(target.get(s.get("{%s}id" % NS["r"]))).lstrip("/").removeprefix("ppt/")
        for s in pres.findall(".//p:sldIdLst/p:sldId", NS)
    ]
    size = pres.find("p:sldSz", NS)
    cx_val = size.get("cx") if size is not None else None
    cy_val = size.get("cy") if size is not None else None
    cx = int(cx_val) if cx_val is not None else 9144000
    cy = int(cy_val) if cy_val is not None else 5143500
    return files, cx, cy


def _theme_colors(z: zipfile.ZipFile) -> dict[str, str]:
    """从布景主题读取颜色对照表。

    Args:
        z: PPTX zipfile 物件。

    Returns:
        颜色代码字典。
    """
    names = [n for n in z.namelist() if n.startswith("ppt/theme/theme") and n.endswith(".xml")]
    if not names:
        return {}
    root = etree.fromstring(z.read(sorted(names)[0]))
    out: dict[str, str] = {}
    scheme = root.find(".//a:clrScheme", NS)
    for el in scheme if scheme is not None else []:
        c = el.find("a:srgbClr", NS)
        s = el.find("a:sysClr", NS)
        val = c.get("val") if c is not None else (s.get("lastClr") if s is not None else None)
        if val:
            out[etree.QName(el).localname] = "#" + val
    out.setdefault("lt1", out.get("lt1", "#FFFFFF"))
    out["bg1"], out["tx1"] = out.get("lt1", "#FFFFFF"), out.get("dk1", "#000000")
    return out


def _color(fill_parent: Any, theme: dict[str, str], default: str) -> str:
    """解析图元填色。

    Args:
        fill_parent: 父 XML 节点。
        theme: 布景主题色彩字典。
        default: 找不到时的预设色码。

    Returns:
        十六进位色码字串。
    """
    if fill_parent is None:
        return default
    sf = fill_parent.find("a:solidFill", NS)
    if sf is None:
        return default
    c = sf.find("a:srgbClr", NS)
    if c is not None and c.get("val"):
        return "#" + str(c.get("val"))
    sc = sf.find("a:schemeClr", NS)
    if sc is not None and sc.get("val"):
        return theme.get(str(sc.get("val")), default)
    return default


def _xfrm(el: Any) -> tuple[int, int, int, int] | None:
    """读取图元 2D 变形位置 (x, y, cx, cy)。

    Args:
        el: XML 图元节点。

    Returns:
        (x, y, 宽, 高) EMU 元组，若无则回传 None。
    """
    x = el.find(".//a:xfrm", NS)
    if x is None:
        return None
    off, ext = x.find("a:off", NS), x.find("a:ext", NS)
    if off is None or ext is None:
        return None
    return int(off.get("x", 0)), int(off.get("y", 0)), int(ext.get("cx", 0)), int(ext.get("cy", 0))


def _is_media(pic: Any) -> bool:
    """判断图片是否为内嵌多媒体。

    Args:
        pic: 图片 XML 节点。

    Returns:
        若为音讯或影片多媒体则回传 True。
    """
    nv = pic.find("p:nvPicPr/p:nvPr", NS)
    return nv is not None and any(
        etree.QName(c).localname in ("audioFile", "videoFile") or "media" in etree.QName(c).localname
        for c in nv.iter()
    )


def _main_picture(slide: Any) -> Any:
    """寻找投影片上占据最大面积的主海报图片。

    Args:
        slide: 投影片根节点。

    Returns:
        主要图片节点或 None。
    """
    pics = [p for p in slide.iter("{%s}pic" % NS["p"]) if not _is_media(p) and _xfrm(p)]
    if not pics:
        return None
    return max(pics, key=lambda p: (_xfrm(p) or (0, 0, 0, 0))[2] * (_xfrm(p) or (0, 0, 0, 0))[3])


def _region(pic: Any, width: int, height: int) -> list[float]:
    """换算海报上的镜头区域 [x, y, 宽, 高]（比例 0~1）。

    Args:
        pic: 主图片节点。
        width: 投影片总宽度。
        height: 投影片总高度。

    Returns:
        [x, y, 宽, 高] 比例列表。
    """
    xf = _xfrm(pic) or (0, 0, width, height)
    ox, oy, ex, ey = xf
    sr = pic.find(".//a:srcRect", NS)
    left, top, right, bottom = (
        (int(sr.get(k, 0)) / 100000.0 if sr is not None and sr.get(k) else 0.0) for k in ("l", "t", "r", "b")
    )

    def u(x_pos: float) -> float:
        """映射投影片 X 坐标至原始海报比例坐标。

        Args:
            x_pos: 投影片 X 坐标。

        Returns:
            海报 X 轴比例浮点数。
        """
        return left + (x_pos - ox) / ex * (1.0 - left - right)

    def v(y_pos: float) -> float:
        """映射投影片 Y 坐标至原始海报比例坐标。

        Args:
            y_pos: 投影片 Y 坐标。

        Returns:
            海报 Y 轴比例浮点数。
        """
        return top + (y_pos - oy) / ey * (1.0 - top - bottom)

    x0, x1, y0, y1 = u(0.0), u(float(width)), v(0.0), v(float(height))
    return [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]


def _text_shapes(slide: Any) -> Iterator[tuple[Any, list[str]]]:
    """迭代投影片上的文字方块及其段落文字。

    Args:
        slide: 投影片根节点。

    Yields:
        (方块节点, 段落文字列表) 元组。
    """
    for sp in slide.iter("{%s}sp" % NS["p"]):
        body = sp.find("p:txBody", NS)
        if body is None or _xfrm(sp) is None:
            continue
        paras = [
            "".join(t.text or "" for t in p.iter("{%s}t" % NS["a"])).strip() for p in body.findall("a:p", NS)
        ]
        valid_paras = [x for x in paras if x]
        if valid_paras:
            yield sp, valid_paras


def _frame(slide: Any, width: int, height: int, theme: dict[str, str]) -> dict[str, Any] | None:
    """盖满整页、中间挖空的形状（外框）：内缩比例 [左, 上, 右, 下] 与颜色。

    Args:
        slide: 投影片根节点。
        width: 投影片宽。
        height: 投影片高。
        theme: 色彩字典。

    Returns:
        外框描述字典，若无则回传 None。
    """
    for sp in slide.iter("{%s}sp" % NS["p"]):
        g = sp.find(".//a:custGeom", NS)
        xf = _xfrm(sp)
        if g is None or not xf or xf[2] < width * 0.98 or xf[3] < height * 0.98:
            continue
        pts = [(int(p.get("x", 0)), int(p.get("y", 0))) for p in g.iter("{%s}pt" % NS["a"])]
        inner = [(x, y) for x, y in pts if 0 < x < xf[2] and 0 < y < xf[3]]
        if len(inner) < 4:
            continue
        xs, ys = [p[0] for p in inner], [p[1] for p in inner]
        return {
            "inset": [
                round(min(xs) / xf[2], 4),
                round(min(ys) / xf[3], 4),
                round(1.0 - max(xs) / xf[2], 4),
                round(1.0 - max(ys) / xf[3], 4),
            ],
            "color": _color(sp.find("p:spPr", NS), theme, "#FFFFFF"),
        }
    return None


def _image_target(z: zipfile.ZipFile, slide_file: str, pic: Any) -> str | None:
    """取得图片在 PPTX 内部的媒体档名。

    Args:
        z: PPTX zipfile。
        slide_file: 投影片路径。
        pic: 图片节点。

    Returns:
        图片档案名称。
    """
    blip = pic.find(".//a:blip", NS)
    rid = blip.get("{%s}embed" % NS["r"]) if blip is not None else None
    rels_name = slide_file.replace("slides/", "slides/_rels/") + ".rels"
    if not rid or rels_name not in z.namelist():
        return None
    rels = etree.fromstring(z.read(rels_name))
    t = next((r.get("Target") for r in rels.findall("rel:Relationship", NS) if r.get("Id") == rid), None)
    return Path(t).name if t else None


def _extract_callout_style(
    sp: Any,
    paras: list[str],
    style: dict[str, Any],
    theme: dict[str, str],
    height: int,
    width: int,
) -> str:
    """从底部文字框抽取提示栏文字与样式。

    Args:
        sp: 文字框节点。
        paras: 段落文字列表。
        style: 样式收集字典。
        theme: 主题色彩字典。
        height: 投影片高度。
        width: 投影片宽度。

    Returns:
        提示栏多行文字。
    """
    callout = "\n".join(paras)
    if "callout_color" not in style:
        xf = _xfrm(sp) or (0, 0, width, height)
        style["callout_height"] = round(xf[3] / height, 4)
        style["callout_color"] = _color(sp.find("p:spPr", NS), theme, "#D9692E")
        rpr = sp.find(".//a:rPr", NS)
        sz = int(rpr.get("sz")) / 100.0 if rpr is not None and rpr.get("sz") else 24.0
        style["callout_font_size"] = round(sz * EMU_PER_PT / height, 4)
        fref = sp.find(".//p:style/a:fontRef/a:schemeClr", NS)
        style["callout_text_color"] = (
            theme.get(fref.get("val", ""), "#FFFFFF") if fref is not None else "#FFFFFF"
        )
        ppr = sp.find(".//a:pPr", NS)
        bu = sp.find(".//a:buChar", NS)
        bf = sp.find(".//a:buFont", NS)
        if bu is not None and bu.get("char"):
            typeface = bf.get("typeface") if bf is not None else ""
            char_key = bu.get("char", "")
            style["callout_prefix"] = SYMBOL_BULLETS.get((typeface, char_key), char_key)
        if ppr is not None and ppr.get("marL"):
            style["callout_text_x"] = round(int(ppr.get("marL")) / width, 4)
            style["callout_bullet_x"] = round((int(ppr.get("marL")) + int(ppr.get("indent", 0))) / width, 4)
    return callout


def read(pptx_path: Path | str) -> dict[str, Any]:
    """回传 {"pages": [...], "style": {...}, "storyboard_like": bool, "image": 海报图档名}。

    Args:
        pptx_path: PPTX 档案路径。

    Returns:
        解析出的分镜设定资讯字典。
    """
    with zipfile.ZipFile(pptx_path) as z:
        files, width, height = _slide_files(z)
        theme = _theme_colors(z)
        pages: list[dict[str, Any]] = []
        style: dict[str, Any] = {}
        images: list[str | None] = []
        for k, f in enumerate(files, 1):
            root = etree.fromstring(z.read(f))
            pic = _main_picture(root)
            images.append(_image_target(z, f, pic) if pic is not None else None)
            callout: str = ""
            note: list[str] = []
            extra: dict[str, Any] = {}
            for sp, paras in _text_shapes(root):
                xf = _xfrm(sp) or (0, 0, width, height)
                _, y, w, _ = xf
                if y > height * 0.6 and w > width * 0.6:  # 底部、横跨画面的文字方块 = 提示栏
                    callout = _extract_callout_style(sp, paras, style, theme, height, width)
                else:
                    note.append(" / ".join(paras))
            fr = _frame(root, width, height, theme)
            if fr and "frame_inset" not in style:
                style["frame_inset"], style["frame_color"] = fr["inset"], fr["color"]
            pages.append(
                {
                    "pptx_slide": k,
                    "region": _region(pic, width, height) if pic is not None else None,
                    "callout": callout,
                    "other_text": note,
                    "overlay": extra.get("overlay"),
                }
            )
        same = bool(images) and None not in images and len(set(images)) == 1
        return {
            "pages": pages,
            "style": style,
            "slide_size": (width, height),
            "storyboard_like": same,
            "image": images[0] if same else None,
        }


def _q(s: str) -> str:
    """包装 TOML 字串并跳脱特殊字元。

    Args:
        s: 待包装字串。

    Returns:
        引注后的字串。
    """
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def write_scenes(info: dict[str, Any], out_path: Path | str, pptx_name: str) -> None:
    """依 pptx 分镜写出 scenes.toml（放在 review/）。

    Args:
        info: 分镜资讯字典。
        out_path: 输出 TOML 路径。
        pptx_name: PPTX 来源名称。
    """
    st = info.get("style", {})
    rows: list[str] = [
        "# ============================================================",
        f"# 每一幕要怎样（scenes.toml）—— 由 {pptx_name} 自动产生，请确认后执行：",
        "#   uv run sv.py approve <工作名称> scenes.toml",
        "# region、callout 都可以改；规则见 templates/generate/input/scenes.toml",
        "# ============================================================",
        "",
        "[defaults]",
        'visual = "poster"',
        f"callout_prefix = {_q(st.get('callout_prefix', '✓'))}",
        "",
        "[style]                           # 从 pptx 读出的样式；数字都是占画面宽／高的比例",
    ]
    for k in (
        "callout_height",
        "callout_color",
        "callout_text_color",
        "callout_font_size",
        "callout_text_x",
        "callout_bullet_x",
        "frame_inset",
        "frame_color",
    ):
        if k in st:
            v = st[k]
            rows.append(f"{k} = {_q(v) if isinstance(v, str) else v}")
    for p in info.get("pages", []):
        slide_no = p["pptx_slide"]
        rows.extend(
            [
                "",
                "[[scene]]",
                f"slide = {slide_no}",
                f"intent = {_q('（从 pptx 第 ' + str(slide_no) + ' 页读出）')}",
                'visual = "poster"',
            ]
        )
        if p.get("region"):
            rows.append(f"region = {p['region']}")
        else:
            rows.append("region = [0.0, 0.0, 1.0, 1.0]   # 这页找不到海报图片，先用整张")
        rows.append(f"callout = {_q(p.get('callout', ''))}")
        note_str = "pptx 第 %d 页" % slide_no
        if p.get("other_text"):
            note_str += "；其他文字：" + "；".join(p["other_text"])
        rows.append(f"notes = {_q(note_str)}")
    Path(out_path).write_text("\n".join(rows) + "\n", encoding="utf-8")
