"""Voicebox 本机 API（0.5.0）。

已知问题（Mac / MLX 版）：
- 模型若由 API 第一次载入，会出现 "There is no Stream(gpu…)"，连 app 里也坏掉。
  一定要先从 Dock 打开 Voicebox、在 app 里生成一句，让模型载入，再跑脚本。
- 不要由脚本重启 Voicebox，从终端机打开的 Voicebox 一样会坏。
- /transcribe 从 API 呼叫会出错，所以检查改用本机 faster-whisper。
- 会忽略 seed：同样的文字每次结果都一样，重试要换文字写法。
"""
import json, sys, time, urllib.error, urllib.request


class VoiceboxBroken(Exception):
    """Voicebox 出错，重试也没用，要请使用者处理（重开 app、在 app 里生成一句）"""


class Voicebox:
    def __init__(self, cfg):
        self.url = cfg["url"].rstrip("/")
        self.profile_name = cfg["profile"]
        self.language = cfg.get("language", "zh")
        self.timeout = cfg.get("timeout", 180)
        self.cleanup = cfg.get("cleanup", True)
        self._profile = None
        self.sent = []                          # 这次送出的生成 id，结束时再检查一遍有没有漏删

    def _get(self, path, timeout=30):
        try:
            with urllib.request.urlopen(f"{self.url}{path}", timeout=timeout) as r:
                return r.read()
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), ConnectionRefusedError):
                raise VoiceboxBroken("连不上 Voicebox：请从 Dock 打开 Voicebox") from e
            raise

    def check_ready(self):
        """模型没有载入就停下：由 API 载入会让 MLX 坏掉"""
        health = json.loads(self._get("/health", 10))
        if not health.get("model_loaded"):
            raise VoiceboxBroken("Voicebox 的模型没有载入。请先在 Voicebox app 里用声音档生成一句话，再执行。")

    def profile(self):
        if self._profile is None:
            profiles = {p["name"]: p for p in json.loads(self._get("/profiles"))}
            if self.profile_name not in profiles:
                sys.exit(f"找不到声音档「{self.profile_name}」，现有：{', '.join(profiles)}")
            self._profile = profiles[self.profile_name]
        return self._profile

    def generate(self, text, language=None):
        """送出生成，轮询到完成，回传 wav bytes"""
        p = self.profile()
        body = {"profile_id": p["id"], "text": text,
                "language": language or self.language or p.get("language") or "zh"}
        if p.get("default_engine"):
            body["engine"] = p["default_engine"]
        req = urllib.request.Request(f"{self.url}/generate", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                gid = json.loads(r.read())["id"]
            self.sent.append(gid)
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), ConnectionRefusedError):
                raise VoiceboxBroken("连不上 Voicebox：可能已经关闭或崩溃") from e
            raise
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            h = json.loads(self._get(f"/history/{gid}"))
            if h.get("status") == "completed":
                wav = self._get(f"/audio/{gid}", 60)
                if self.cleanup:
                    self.delete(gid)            # 音档已经拿到，不留在 Voicebox 的纪录里
                return wav
            if h.get("status") in ("failed", "error", "cancelled"):
                err = h.get("error") or h["status"]
                if self.cleanup:
                    self.delete(gid)
                if "no Stream(gpu" in err:
                    raise VoiceboxBroken(f"Voicebox 内部出错（{err}）：请 ⌘Q 后从 Dock 重开，并在 app 里生成一句")
                raise RuntimeError(err)
            time.sleep(1)
        try:
            urllib.request.urlopen(urllib.request.Request(f"{self.url}/generate/{gid}/cancel",
                                                          method="POST"), timeout=10)
            if self.cleanup:
                self.delete(gid)
        except Exception:
            pass
        raise TimeoutError(f"超过 {self.timeout} 秒仍未完成")

    def delete(self, gid, tries=3):
        """删除一笔生成纪录（连同音档）。刚生成完时 Voicebox 可能还在处理档案，失败就隔一秒再试"""
        for k in range(tries):
            try:
                urllib.request.urlopen(urllib.request.Request(f"{self.url}/history/{gid}", method="DELETE"),
                                       timeout=30)
                return True
            except urllib.error.HTTPError as e:
                if e.code == 404:               # 已经删掉了
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def sweep(self):
        """把这次送出、但还留在 Voicebox 里的生成补删掉。回传补删的数量"""
        if not self.cleanup or not self.sent:
            return 0
        try:
            left = {h["id"] for h in self.history() if h.get("status") != "generating"}
        except Exception:
            return 0
        n = sum(self.delete(g) for g in self.sent if g in left)
        self.sent.clear()
        return n

    def history(self, limit=100):
        """列出所有生成纪录"""
        items, offset = [], 0
        while True:
            page = json.loads(self._get(f"/history?limit={limit}&offset={offset}"))
            batch = page.get("items", page) if isinstance(page, dict) else page
            items += batch
            if len(batch) < limit:
                return items
            offset += limit

    def clear(self, keep_favorites=False, log=print):
        """删除 Voicebox 里所有生成纪录；生成中的跳过。回传 (删除数, 跳过数)"""
        done = skipped = 0
        for h in self.history():
            if h.get("status") == "generating" or (keep_favorites and h.get("is_favorited")):
                skipped += 1
                continue
            done += self.delete(h["id"])
        try:
            urllib.request.urlopen(urllib.request.Request(f"{self.url}/history/failed", method="DELETE"),
                                   timeout=30)
        except Exception:
            pass
        return done, skipped
