"""把 pptx 当分镜（V2）：每一页都是同一张海报图、不同裁切／位置，再加提示栏与外框。

从 pptx 读出：
- 每一页镜头看海报的哪一块：投影片画面 → 透过图片的位置、大小、裁切（srcRect）换算回海报座标
- 底部提示栏的文字（多段落用换行分开）与样式：高度、底色、字色、字级、开头的 ✓
- 外框（盖在海报上、中间挖空的形状）：内缩比例与颜色
再用高解析海报（PDF）重新渲染，时间跟着新配音走；pptx 本身不会被修改。
"""
import zipfile
from pathlib import Path

from lxml import etree

NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
EMU_PER_PT = 12700
SYMBOL_BULLETS = {("Wingdings", "ü"): "✓", ("Wingdings", "Ÿ"): "•", ("Wingdings", "§"): "■"}


def _slide_files(z):
    pres = etree.fromstring(z.read("ppt/presentation.xml"))
    rels = etree.fromstring(z.read("ppt/_rels/presentation.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels.findall("rel:Relationship", NS)}
    files = ["ppt/" + target[s.get("{%s}id" % NS["r"])].lstrip("/").removeprefix("ppt/")
             for s in pres.findall(".//p:sldIdLst/p:sldId", NS)]
    size = pres.find("p:sldSz", NS)
    return files, int(size.get("cx")), int(size.get("cy"))


def _theme_colors(z):
    names = [n for n in z.namelist() if n.startswith("ppt/theme/theme") and n.endswith(".xml")]
    if not names:
        return {}
    root = etree.fromstring(z.read(sorted(names)[0]))
    out = {}
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


def _color(fill_parent, theme, default):
    if fill_parent is None:
        return default
    sf = fill_parent.find("a:solidFill", NS)
    if sf is None:
        return default
    c = sf.find("a:srgbClr", NS)
    if c is not None:
        return "#" + c.get("val")
    sc = sf.find("a:schemeClr", NS)
    if sc is not None:
        return theme.get(sc.get("val"), default)
    return default


def _xfrm(el):
    x = el.find(".//a:xfrm", NS)
    if x is None:
        return None
    off, ext = x.find("a:off", NS), x.find("a:ext", NS)
    return int(off.get("x")), int(off.get("y")), int(ext.get("cx")), int(ext.get("cy"))


def _is_media(pic):
    nv = pic.find("p:nvPicPr/p:nvPr", NS)
    return nv is not None and any(etree.QName(c).localname in ("audioFile", "videoFile")
                                  or "media" in etree.QName(c).localname for c in nv.iter())


def _main_picture(slide):
    pics = [p for p in slide.iter("{%s}pic" % NS["p"]) if not _is_media(p) and _xfrm(p)]
    if not pics:
        return None
    return max(pics, key=lambda p: _xfrm(p)[2] * _xfrm(p)[3])


def _region(pic, W, H):
    """整个投影片画面 → 海报上的区域 [x, y, 宽, 高]（占海报宽、高的比例）"""
    ox, oy, ex, ey = _xfrm(pic)
    sr = pic.find(".//a:srcRect", NS)
    L, T, R, B = ((int(sr.get(k, 0)) / 100000 if sr is not None else 0.0) for k in ("l", "t", "r", "b"))
    def u(X):
        return L + (X - ox) / ex * (1 - L - R)
    def v(Y):
        return T + (Y - oy) / ey * (1 - T - B)
    x0, x1, y0, y1 = u(0), u(W), v(0), v(H)
    return [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]


def _text_shapes(slide):
    for sp in slide.iter("{%s}sp" % NS["p"]):
        body = sp.find("p:txBody", NS)
        if body is None or _xfrm(sp) is None:
            continue
        paras = ["".join(t.text or "" for t in p.iter("{%s}t" % NS["a"])).strip()
                 for p in body.findall("a:p", NS)]
        paras = [x for x in paras if x]
        if paras:
            yield sp, paras


def _frame(slide, W, H, theme):
    """盖满整页、中间挖空的形状（外框）：内缩比例 [左, 上, 右, 下] 与颜色"""
    for sp in slide.iter("{%s}sp" % NS["p"]):
        g = sp.find(".//a:custGeom", NS)
        xf = _xfrm(sp)
        if g is None or not xf or xf[2] < W * 0.98 or xf[3] < H * 0.98:
            continue
        pts = [(int(p.get("x")), int(p.get("y"))) for p in g.iter("{%s}pt" % NS["a"])]
        inner = [(x, y) for x, y in pts if 0 < x < xf[2] and 0 < y < xf[3]]
        if len(inner) < 4:
            continue
        xs, ys = [p[0] for p in inner], [p[1] for p in inner]
        return {"inset": [round(min(xs) / xf[2], 4), round(min(ys) / xf[3], 4),
                          round(1 - max(xs) / xf[2], 4), round(1 - max(ys) / xf[3], 4)],
                "color": _color(sp.find("p:spPr", NS), theme, "#FFFFFF")}
    return None


def _image_target(z, slide_file, pic):
    """这张图片在 pptx 里的档案（ppt/media/…），用来判断每一页是不是同一张海报"""
    blip = pic.find(".//a:blip", NS)
    rid = blip.get("{%s}embed" % NS["r"]) if blip is not None else None
    rels_name = slide_file.replace("slides/", "slides/_rels/") + ".rels"
    if not rid or rels_name not in z.namelist():
        return None
    rels = etree.fromstring(z.read(rels_name))
    t = next((r.get("Target") for r in rels.findall("rel:Relationship", NS) if r.get("Id") == rid), None)
    return Path(t).name if t else None


def read(pptx_path):
    """回传 {"pages": [...], "style": {...}, "storyboard_like": bool, "image": 海报图档名}"""
    with zipfile.ZipFile(pptx_path) as z:
        files, W, H = _slide_files(z)
        theme = _theme_colors(z)
        pages, style, images = [], {}, []
        for k, f in enumerate(files, 1):
            root = etree.fromstring(z.read(f))
            pic = _main_picture(root)
            images.append(_image_target(z, f, pic) if pic is not None else None)
            callout, note, extra = "", [], {}
            for sp, paras in _text_shapes(root):
                x, y, w, h = _xfrm(sp)
                if y > H * 0.6 and w > W * 0.6:                      # 底部、横跨画面的文字方块 = 提示栏
                    callout = "\n".join(paras)
                    if "callout_color" not in style:
                        style["callout_height"] = round(h / H, 4)
                        style["callout_color"] = _color(sp.find("p:spPr", NS), theme, "#D9692E")
                        rpr = sp.find(".//a:rPr", NS)
                        sz = int(rpr.get("sz")) / 100 if rpr is not None and rpr.get("sz") else 24
                        style["callout_font_size"] = round(sz * EMU_PER_PT / H, 4)   # 占画面高度的比例
                        fref = sp.find(".//p:style/a:fontRef/a:schemeClr", NS)
                        style["callout_text_color"] = theme.get(fref.get("val"), "#FFFFFF") if fref is not None else "#FFFFFF"
                        ppr = sp.find(".//a:pPr", NS)
                        bu = sp.find(".//a:buChar", NS)
                        bf = sp.find(".//a:buFont", NS)
                        if bu is not None:
                            style["callout_prefix"] = SYMBOL_BULLETS.get(
                                (bf.get("typeface") if bf is not None else "", bu.get("char")), bu.get("char"))
                        if ppr is not None and ppr.get("marL"):
                            style["callout_text_x"] = round(int(ppr.get("marL")) / W, 4)
                            style["callout_bullet_x"] = round((int(ppr.get("marL")) + int(ppr.get("indent", 0))) / W, 4)
                else:
                    note.append(" / ".join(paras))
                    if "overlay" not in extra:              # 其他文字方块（例如结尾的「匯報完畢」）
                        rpr = sp.find(".//a:rPr", NS)
                        font = sp.find(".//a:rPr/a:ea", NS)
                        if font is None:
                            font = sp.find(".//a:rPr/a:latin", NS)
                        sz = int(rpr.get("sz")) / 100 if rpr is not None and rpr.get("sz") else 32
                        extra["overlay"] = {
                            "text": "\n".join(paras),
                            "box": [round(x / W, 4), round(y / H, 4), round(w / W, 4), round(h / H, 4)],
                            "font_size": round(sz * EMU_PER_PT / H, 4),
                            "font": font.get("typeface") if font is not None else "",
                            "color": _color(rpr, theme, theme.get("tx1", "#000000")) if rpr is not None else "#000000"}
            fr = _frame(root, W, H, theme)
            if fr and "frame_inset" not in style:
                style["frame_inset"], style["frame_color"] = fr["inset"], fr["color"]
            pages.append({"pptx_slide": k, "region": _region(pic, W, H) if pic is not None else None,
                          "callout": callout, "other_text": note, "overlay": extra.get("overlay")})
        same = bool(images) and None not in images and len(set(images)) == 1
        return {"pages": pages, "style": style, "slide_size": (W, H),
                "storyboard_like": same, "image": images[0] if same else None}


def _q(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def write_scenes(info, out_path, pptx_name):
    """依 pptx 分镜写出 scenes.toml（放在 review/，你确认后再 approve 到 input/）"""
    st = info["style"]
    rows = [
        "# ============================================================",
        f"# 每一幕要怎样（scenes.toml）—— 由 {pptx_name} 自动产生，请确认后执行：",
        "#   uv run sv.py approve <工作名称> scenes.toml",
        "# region、callout 都可以改；规则见 templates/generate/input/scenes.toml",
        "# ============================================================",
        "",
        "[defaults]",
        'visual = "poster"',
        f'callout_prefix = {_q(st.get("callout_prefix", "✓"))}',
        "",
        "[style]                           # 从 pptx 读出的样式；数字都是占画面宽／高的比例",
    ]
    for k in ("callout_height", "callout_color", "callout_text_color", "callout_font_size",
              "callout_text_x", "callout_bullet_x", "frame_inset", "frame_color"):
        if k in st:
            v = st[k]
            rows.append(f"{k} = {_q(v) if isinstance(v, str) else v}")
    for p in info["pages"]:
        rows += ["", "[[scene]]", f"slide = {p['pptx_slide']}",
                 f"intent = {_q('（从 pptx 第 ' + str(p['pptx_slide']) + ' 页读出）')}",
                 'visual = "poster"']
        rows.append(f"region = {p['region']}" if p["region"] else "region = [0.0, 0.0, 1.0, 1.0]   # 这页找不到海报图片，先用整张")
        rows.append(f"callout = {_q(p['callout'])}")
        ov = p.get("overlay")
        if ov:
            rows += [f"overlay_text = {_q(ov['text'])}             # 画面上的大字（从 pptx 读出）",
                     f"overlay_box = {ov['box']}",
                     f"overlay_font_size = {ov['font_size']}",
                     f"overlay_font = {_q(ov['font'])}",
                     f"overlay_color = {_q(ov['color'])}"]
        rows.append(f"notes = {_q('pptx 第 %d 页' % p['pptx_slide'] + ('；其他文字：' + '；'.join(p['other_text']) if p['other_text'] else ''))}")
    Path(out_path).write_text("\n".join(rows) + "\n", encoding="utf-8")
