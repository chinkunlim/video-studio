"""拼接：每句切掉头尾静音，依停顿种类补静音，记录每句在成品里的起止时间（给字幕用）。"""
from . import audio

RATE = 24000


def build(items, pause, out_wav, tmp, loudness=-16, sample_rate=48000):
    """items: [{no, slide, clip, brk}] 依序。回传 timeline [{no, start, end, trim_start}]"""
    tmp.mkdir(parents=True, exist_ok=True)
    listing, timeline, t = [], [], 0.0
    for k, it in enumerate(items):
        s, e = audio.speech_bounds(it["clip"])
        piece = tmp / f"{it['no']:03d}.wav"
        audio.cut(it["clip"], piece, s, e, RATE)
        d = audio.duration(piece)
        timeline.append({"no": it["no"], "start": round(t, 3), "end": round(t + d, 3), "trim_start": round(s, 3)})
        listing.append(piece)
        t += d
        if k + 1 < len(items):
            g = pause[it["brk"]] if it["brk"] in pause else pause["comma"]
            if items[k + 1]["slide"] != it["slide"]:
                g = max(g, pause["slide"])
            gap = tmp / f"gap_{g:.2f}.wav"
            if not gap.exists():
                audio.ff("-f", "lavfi", "-i", f"anullsrc=r={RATE}:cl=mono", "-t", f"{g:.3f}",
                         "-c:a", "pcm_s16le", gap)
            listing.append(gap)
            t += audio.duration(gap)
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in listing))
    audio.ff("-f", "concat", "-safe", "0", "-i", lst, "-af",
             f"loudnorm=I={loudness}:TP=-1.5:LRA=11", "-ar", sample_rate, out_wav)
    return timeline
