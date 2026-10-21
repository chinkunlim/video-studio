"""PowerPoint：依配音设定换页时间与点击动画的时间，再让 PowerPoint 自己汇出 mp4（保留动画与转场）。

实测（PowerPoint 16.114 for Mac，2026-10-18）：
- AppleScript 可以设定每页的换页时间（slide show transition 的 advance time），
  「save as movie」会照这个时间汇出；汇出在背景进行，要等档案写完才能关闭简报。
- Mac 版 AppleScript 不能改动画的触发方式，所以直接改 pptx 里的动画时间表：
  把一页所有「点一下才出现」的群组，合并成一个跟着投影片自动开始的群组（onBegin），
  每个点击的延迟 = 它在配音里的秒数（相对于这一页开始）。直接把 indefinite 改成数字没有用（会立刻出现）。
- PowerPoint 只能写入它有权限的位置（例如工作区），不能写进系统暂存资料夹。
"""
import re
import subprocess
import time
import zipfile
from pathlib import Path

from lxml import etree

NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
P = "{%s}" % NS["p"]


def slide_files(z):
    """依简报顺序回传 slide XML 的路径"""
    pres = etree.fromstring(z.read("ppt/presentation.xml"))
    rels = etree.fromstring(z.read("ppt/_rels/presentation.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels.findall("rel:Relationship", NS)}
    out = []
    for sid in pres.findall(".//p:sldIdLst/p:sldId", NS):
        t = target[sid.get("{%s}id" % NS["r"])]
        out.append("ppt/" + t.lstrip("/").removeprefix("ppt/"))
    return out


def _main_seq(root):
    return root.find(".//p:cTn[@nodeType='mainSeq']", NS)


def _is_click_group(par):
    conds = par.findall("./p:cTn/p:stCondLst/p:cond", NS)
    return any(c.get("delay") == "indefinite" for c in conds) and not any(c.get("evt") == "onBegin" for c in conds)


def click_counts(pptx):
    """每一页有几个「点一下才出现」的动画群组"""
    with zipfile.ZipFile(pptx) as z:
        counts = []
        for f in slide_files(z):
            root = etree.fromstring(z.read(f))
            ms = _main_seq(root)
            groups = ms.findall("./p:childTnLst/p:par", NS) if ms is not None else []
            counts.append(sum(1 for g in groups if _is_click_group(g)))
        return counts


def _retime_slide(xml, offsets_ms):
    root = etree.fromstring(xml)
    ms = _main_seq(root)
    lst = ms.find("./p:childTnLst", NS)
    groups = lst.findall("./p:par", NS)
    clicks = [g for g in groups if _is_click_group(g)]
    if len(clicks) != len(offsets_ms):
        raise ValueError(f"动画点击 {len(clicks)} 个，讲稿 [click] {len(offsets_ms)} 个")
    ids = [int(c.get("id")) for c in root.iter(P + "cTn") if c.get("id", "").isdigit()]
    new_par = etree.SubElement(lst, P + "par")
    ctn = etree.SubElement(new_par, P + "cTn", id=str(max(ids) + 1), fill="hold")
    st = etree.SubElement(ctn, P + "stCondLst")
    etree.SubElement(st, P + "cond", delay="indefinite")
    onb = etree.SubElement(st, P + "cond", evt="onBegin", delay="0")
    etree.SubElement(onb, P + "tn", val=ms.get("id"))
    children = etree.SubElement(ctn, P + "childTnLst")
    offs = iter(offsets_ms)
    for g in groups:
        off = next(offs) if g in clicks else 0
        for sub in g.findall("./p:cTn/p:childTnLst/p:par", NS):
            for c in sub.findall("./p:cTn/p:stCondLst/p:cond", NS):
                d = c.get("delay")
                if d and d.isdigit():
                    c.set("delay", str(int(d) + off))
            for node in sub.iter(P + "cTn"):
                if node.get("nodeType") in ("clickEffect", "afterEffect"):
                    node.set("nodeType", "withEffect")
            children.append(sub)
        lst.remove(g)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def retime(src, dst, clicks_per_slide):
    """clicks_per_slide：每页 [click] 在页内第几秒（list of list）。写出调整过动画时间的副本。"""
    with zipfile.ZipFile(src) as zi:
        files = slide_files(zi)
        if len(files) != len(clicks_per_slide):
            raise ValueError(f"pptx 有 {len(files)} 页，讲稿有 {len(clicks_per_slide)} 页（## 投影片），要一样多")
        errors = []
        changed = {}
        for k, (f, clicks) in enumerate(zip(files, clicks_per_slide), 1):
            xml = zi.read(f)
            root = etree.fromstring(xml)
            ms = _main_seq(root)
            n = sum(1 for g in (ms.findall("./p:childTnLst/p:par", NS) if ms is not None else []) if _is_click_group(g))
            if n != len(clicks):
                errors.append(f"第 {k} 页：PowerPoint 有 {n} 个点击动画，讲稿这一页有 {len(clicks)} 个 [click]")
                continue
            if n:
                changed[f] = _retime_slide(xml, [int(round(c * 1000)) for c in clicks])
        if errors:
            raise ValueError("点击动画和讲稿的 [click] 数量对不上：\n" + "\n".join(errors)
                             + "\n请在讲稿对应的那一行开头加上 [click]（念到那一行时触发下一个动画）。")
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
            for it in zi.infolist():
                zo.writestr(it, changed.get(it.filename, zi.read(it.filename)))


def export(pptx, durations, out_mp4, timeout=1800):
    """用 PowerPoint 汇出 mp4：设定每页换页时间 → save as movie → 等档案写完 → 关闭（不存档）"""
    pptx, out_mp4 = Path(pptx).resolve(), Path(out_mp4).resolve()
    if out_mp4.exists():
        out_mp4.unlink()
    durs = "{" + ", ".join(f"{d:.3f}" for d in durations) + "}"
    script = f'''
set durs to {durs}
tell application "Microsoft PowerPoint"
    open POSIX file "{pptx}"
    set pres to active presentation
    if (count of slides of pres) is not (count of durs) then error "页数不对：" & (count of slides of pres)
    repeat with i from 1 to count of slides of pres
        set t to slide show transition of slide i of pres
        set advance on click of t to false
        set advance on time of t to true
        set advance time of t to item i of durs
    end repeat
    save pres in (POSIX file "{out_mp4}") as save as movie
end tell
'''
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("PowerPoint 汇出失败：" + r.stderr.strip()
                           + "\n（如果出现「不允许控制」，请到 系统设定 → 隐私权与安全性 → 自动化，允许控制 Microsoft PowerPoint）")
    last, stable, t0 = -1, 0, time.time()
    try:
        while time.time() - t0 < timeout:
            time.sleep(2)
            size = out_mp4.stat().st_size if out_mp4.exists() else 0
            stable = stable + 1 if size > 0 and size == last else 0
            last = size
            if stable >= 3:
                break
        else:
            raise RuntimeError(f"PowerPoint 汇出超过 {timeout} 秒没完成")
    finally:
        subprocess.run(["osascript", "-e",
                        'tell application "Microsoft PowerPoint" to close active presentation saving no'],
                       capture_output=True, text=True)
    return out_mp4


def strip_media(src, dst):
    """移除每一页内嵌的音档／影片与自动播放它们的动画（避免旧录音跟新配音一起播出）。回传移除了几个。"""
    removed = 0
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for it in zi.infolist():
            data = zi.read(it.filename)
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", it.filename):
                root = etree.fromstring(data)
                media_ids = set()
                for pic in list(root.iter(P + "pic")):
                    nv = pic.find("p:nvPicPr/p:nvPr", NS)
                    if nv is not None and any(etree.QName(c).localname in ("audioFile", "videoFile")
                                              for c in nv.iter()):
                        media_ids.add(pic.find("p:nvPicPr/p:cNvPr", NS).get("id"))
                        pic.getparent().remove(pic)
                        removed += 1
                for par in list(root.iter(P + "par")):
                    ctn = par.find("p:cTn", NS)
                    if ctn is not None and ctn.get("presetClass") == "mediacall" and par.getparent() is not None:
                        par.getparent().remove(par)
                for tag in ("audio", "video"):
                    for node in list(root.iter(P + tag)):
                        node.getparent().remove(node)
                # 清掉因此变空的动画群组
                for par in list(root.iter(P + "par")):
                    lst = par.find("p:cTn/p:childTnLst", NS)
                    if lst is not None and len(lst) == 0 and par.getparent() is not None \
                            and par.find("p:cTn", NS).get("nodeType") != "tmRoot":
                        par.getparent().remove(par)
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            zo.writestr(it, data)
    return removed
