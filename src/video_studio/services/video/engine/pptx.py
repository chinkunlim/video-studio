"""PowerPoint：依配音设定换页时间与点击动画的时间，再让 PowerPoint 自己汇出 mp4（保留动画与转场）。

实测（PowerPoint 16.114 for Mac，2026-10-18）：
- AppleScript 可以设定每页的换页时间（slide show transition 的 advance time），
  「save as movie」会照这个时间汇出；汇出在背景进行，要等档案写完才能关闭简报。
- Mac 版 AppleScript 不能改动画的触发方式，所以直接改 pptx 里的动画时间表：
  把一页所有「点一下才出现」的群组，合并成一个跟着投影片自动开始的群组（onBegin），
  每个点击的延迟 = 它在配音里的秒数（相对于这一页开始）。直接把 indefinite 改成数字没有用（会立刻出现）。
- PowerPoint 只能写入它有权限的位置（例如工作区），不能写进系统暂存资料夹。
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

logger = logging.getLogger(__name__)

NS: dict[str, str] = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
P = "{%s}" % NS["p"]


def slide_files(z: zipfile.ZipFile) -> list[str]:
    """依简报顺序回传 slide XML 的路径。

    Args:
        z: PPTX zipfile 物件。

    Returns:
        投影片 XML 档案路径列表。
    """
    pres = etree.fromstring(z.read("ppt/presentation.xml"))
    rels = etree.fromstring(z.read("ppt/_rels/presentation.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels.findall("rel:Relationship", NS)}
    out: list[str] = []
    for sid in pres.findall(".//p:sldIdLst/p:sldId", NS):
        target_id = sid.get("{%s}id" % NS["r"])
        t = str(target.get(target_id, "")).lstrip("/").removeprefix("ppt/")
        out.append("ppt/" + t)
    return out


def _main_seq(root: Any) -> Any:
    """找出主要的动画时间轴序列节点。

    Args:
        root: 投影片根节点。

    Returns:
        mainSeq 节点或 None。
    """
    return root.find(".//p:cTn[@nodeType='mainSeq']", NS)


def _is_click_group(par: Any) -> bool:
    """判断是否为点击触发动画群组。

    Args:
        par: 动画群组节点。

    Returns:
        若为点击触发群组回传 True。
    """
    conds = par.findall("./p:cTn/p:stCondLst/p:cond", NS)
    return any(c.get("delay") == "indefinite" for c in conds) and not any(
        c.get("evt") == "onBegin" for c in conds
    )


def click_counts(pptx: Path | str) -> list[int]:
    """计算每一页有几个「点一下才出现」的动画群组。

    Args:
        pptx: PPTX 档案路径。

    Returns:
        每页点击动画数量列表。
    """
    with zipfile.ZipFile(pptx) as z:
        counts: list[int] = []
        for f in slide_files(z):
            root = etree.fromstring(z.read(f))
            ms = _main_seq(root)
            groups = ms.findall("./p:childTnLst/p:par", NS) if ms is not None else []
            counts.append(sum(1 for g in groups if _is_click_group(g)))
        return counts


def _retime_slide(xml: bytes, offsets_ms: list[int]) -> bytes:
    """重算并改写单一投影片内点击动画的时间偏移。

    Args:
        xml: 原始投影片 XML 位元组。
        offsets_ms: 每个点击动画的毫秒偏移量。

    Returns:
        修改后的投影片 XML 位元组。

    Raises:
        ValueError: 动画数量与偏移数量不符。
    """
    root = etree.fromstring(xml)
    ms = _main_seq(root)
    if ms is None:
        return xml
    lst = ms.find("./p:childTnLst", NS)
    if lst is None:
        return xml
    groups = lst.findall("./p:par", NS)
    clicks = [g for g in groups if _is_click_group(g)]
    if len(clicks) != len(offsets_ms):
        raise ValueError(f"动画点击 {len(clicks)} 个，讲稿 [click] {len(offsets_ms)} 个")
    ids = [int(val) for c in root.iter(P + "cTn") if (val := c.get("id")) and val.isdigit()]
    max_id = max(ids) if ids else 100
    new_par = etree.SubElement(lst, P + "par")
    ctn = etree.SubElement(new_par, P + "cTn", id=str(max_id + 1), fill="hold")
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
    result_bytes: bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    return result_bytes


def retime(src: Path | str, dst: Path | str, clicks_per_slide: list[list[float]]) -> None:
    """写出调整过动画时间的 PPTX 副本。

    Args:
        src: 来源 PPTX 路径。
        dst: 输出修改后的 PPTX 路径。
        clicks_per_slide: 每页 [click] 在页内第几秒（嵌套列表）。

    Raises:
        ValueError: 投影片页数或动画点击数量不一致。
    """
    with zipfile.ZipFile(src) as zi:
        files = slide_files(zi)
        if len(files) != len(clicks_per_slide):
            raise ValueError(f"pptx 有 {len(files)} 页，讲稿有 {len(clicks_per_slide)} 页，要一样多")
        errors: list[str] = []
        changed: dict[str, bytes] = {}
        for k, (f, clicks) in enumerate(zip(files, clicks_per_slide, strict=False), 1):
            xml = zi.read(f)
            root = etree.fromstring(xml)
            ms = _main_seq(root)
            groups = ms.findall("./p:childTnLst/p:par", NS) if ms is not None else []
            n = sum(1 for g in groups if _is_click_group(g))
            if n != len(clicks):
                errors.append(
                    f"第 {k} 页：PowerPoint 有 {n} 个点击动画，讲稿这一页有 {len(clicks)} 个 [click]"
                )
                continue
            if n:
                changed[f] = _retime_slide(xml, [int(round(c * 1000.0)) for c in clicks])
        if errors:
            raise ValueError("点击动画和讲稿的 [click] 数量对不上：\n" + "\n".join(errors))
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
            for it in zi.infolist():
                zo.writestr(it, changed.get(it.filename, zi.read(it.filename)))


def export(
    pptx: Path | str,
    durations: list[float],
    out_mp4: Path | str,
    timeout: int = 1800,
) -> Path:
    """用 PowerPoint 汇出 mp4：设定每页换页时间 → save as movie。

    Args:
        pptx: PPTX 档案路径。
        durations: 每页播放秒数列表。
        out_mp4: 输出 MP4 路径。
        timeout: 最长等待完成秒数。

    Returns:
        汇出完成的 MP4 路径。

    Raises:
        RuntimeError: 汇出失败或逾时。
    """
    pptx_path = Path(pptx).resolve()
    out_path = Path(out_mp4).resolve()
    if out_path.exists():
        out_path.unlink()
    durs = "{" + ", ".join(f"{d:.3f}" for d in durations) + "}"
    script = f'''
set durs to {durs}
tell application "Microsoft PowerPoint"
    open POSIX file "{pptx_path}"
    set pres to active presentation
    if (count of slides of pres) is not (count of durs) then error "页数不对：" & (count of slides of pres)
    repeat with i from 1 to count of slides of pres
        set t to slide show transition of slide i of pres
        set advance on click of t to false
        set advance on time of t to true
        set advance time of t to item i of durs
    end repeat
    save pres in (POSIX file "{out_path}") as save as movie
end tell
'''
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        tail = r.stderr.strip()
        raise RuntimeError(f"PowerPoint 汇出失败：{tail}")
    last, stable, t0 = -1, 0, time.time()
    try:
        while time.time() - t0 < timeout:
            time.sleep(2)
            size = out_path.stat().st_size if out_path.exists() else 0
            stable = stable + 1 if size > 0 and size == last else 0
            last = size
            if stable >= 3:
                break
        else:
            raise RuntimeError(f"PowerPoint 汇出超过 {timeout} 秒没完成")
    finally:
        close_script = 'tell application "Microsoft PowerPoint" to close active presentation saving no'
        subprocess.run(
            ["osascript", "-e", close_script],
            capture_output=True,
            text=True,
        )
    return out_path


def strip_media(src: Path | str, dst: Path | str) -> int:
    """移除每一页内嵌的音档／影片与自动播放它们的动画。

    Args:
        src: 来源 PPTX 档案路径。
        dst: 清除后输出的 PPTX 路径。

    Returns:
        移除的多媒体档案数。
    """
    removed = 0
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for it in zi.infolist():
            data = zi.read(it.filename)
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", it.filename):
                root = etree.fromstring(data)
                for pic in list(root.iter(P + "pic")):
                    nv = pic.find("p:nvPicPr/p:nvPr", NS)
                    if nv is not None and any(
                        etree.QName(c).localname in ("audioFile", "videoFile") for c in nv.iter()
                    ):
                        parent = pic.getparent()
                        if parent is not None:
                            parent.remove(pic)
                        removed += 1
                for par in list(root.iter(P + "par")):
                    ctn = par.find("p:cTn", NS)
                    par_parent = par.getparent()
                    if ctn is not None and ctn.get("presetClass") == "mediacall" and par_parent is not None:
                        par_parent.remove(par)
                for tag in ("audio", "video"):
                    for node in list(root.iter(P + tag)):
                        node_parent = node.getparent()
                        if node_parent is not None:
                            node_parent.remove(node)
                for par in list(root.iter(P + "par")):
                    lst = par.find("p:cTn/p:childTnLst", NS)
                    par_parent = par.getparent()
                    ctn_node = par.find("p:cTn", NS)
                    if (
                        lst is not None
                        and len(lst) == 0
                        and par_parent is not None
                        and (ctn_node is None or ctn_node.get("nodeType") != "tmRoot")
                    ):
                        par_parent.remove(par)
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            zo.writestr(it, data)
    return removed
