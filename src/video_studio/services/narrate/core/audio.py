"""音讯处理：ffmpeg 包装、音量分析、找静音、检查头尾残留。"""
import array, math, subprocess, wave

FRAME = 0.01          # 分析单位：10ms
QUIET_DB = -45.0      # 低于这个音量才算静音
QUIET_MIN = 0.03      # 静音至少要这么长才能下刀
EDGE_DB = -40.0       # 片段头尾的音量上限
BLOB_MAX = 0.14       # 头尾短于这个长度的孤立声音，视为残留的「始」「结」


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def cut(src, dst, start=None, end=None, rate=24000):
    rng = (["-ss", f"{start:.3f}"] if start is not None else []) + \
          (["-to", f"{end:.3f}"] if end is not None else [])
    ff("-i", src, *rng, "-ar", rate, "-ac", 1, "-c:a", "pcm_s16le", dst)


def frames_db(path):
    """每 10ms 的音量（dBFS）"""
    with wave.open(str(path)) as w:
        sr = w.getframerate()
        pcm = array.array("h", w.readframes(w.getnframes()))
    n = int(sr * FRAME)
    return [10 * math.log10((sum(x * x for x in pcm[k * n:(k + 1) * n]) / n or 1e-9) / 32768 ** 2)
            for k in range(len(pcm) // n)]


def quiet_runs(db, lo, hi):
    """[lo, hi] 秒之间的静音段 [(开始, 结束)]"""
    runs, start = [], None
    a, b = max(0, int(lo / FRAME)), min(len(db), int(hi / FRAME))
    for k in range(a, b):
        if db[k] < QUIET_DB:
            start = k if start is None else start
        else:
            if start is not None and (k - start) * FRAME >= QUIET_MIN:
                runs.append((start * FRAME, k * FRAME))
            start = None
    if start is not None and (b - start) * FRAME >= QUIET_MIN:
        runs.append((start * FRAME, b * FRAME))
    return runs


def edge_problems(path):
    """切好的片段：头尾要是静音，头尾不能有孤立的小块声音"""
    db = frames_db(path)
    probs = []
    if db[:2] and max(db[:2]) > EDGE_DB:
        probs.append("开头贴着声音")
    if db[-2:] and max(db[-2:]) > EDGE_DB:
        probs.append("结尾贴着声音")
    blobs, k = [], 0
    while k < len(db):
        if db[k] > EDGE_DB:
            j = k
            while j < len(db) and db[j] > EDGE_DB:
                j += 1
            if blobs and k * FRAME - blobs[-1][1] < 0.05:
                blobs[-1] = (blobs[-1][0], j * FRAME)
            else:
                blobs.append((k * FRAME, j * FRAME))
            k = j
        else:
            k += 1
    if len(blobs) > 1 and blobs[0][1] - blobs[0][0] < BLOB_MAX:
        probs.append(f"开头有孤立声音 {blobs[0][1] - blobs[0][0]:.2f}s")
    if len(blobs) > 1 and blobs[-1][1] - blobs[-1][0] < BLOB_MAX:
        probs.append(f"结尾有孤立声音 {blobs[-1][1] - blobs[-1][0]:.2f}s")
    return probs


def speech_bounds(path, keep=0.04, threshold=-45.0):
    """有声音的范围（前后各留 keep 秒）"""
    db = frames_db(path)
    on = [k for k, d in enumerate(db) if d > threshold]
    if not on:
        return 0.0, len(db) * FRAME
    return max(0.0, on[0] * FRAME - keep), min(len(db) * FRAME, (on[-1] + 1) * FRAME + keep)
