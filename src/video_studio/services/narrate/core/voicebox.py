"""Voicebox 本机 API（0.5.0）。

已知问题（Mac / MLX 版）：
- 模型若由 API 第一次载入，会出现 "There is no Stream(gpu…)"，连 app 里也坏掉。
  一定要先从 Dock 打开 Voicebox、在 app 里生成一句，让模型载入，再跑脚本。
- 不要由脚本重启 Voicebox，从终端机打开的 Voicebox 一样会坏。
- /transcribe 从 API 呼叫会出错，所以检查改用本机 faster-whisper。
- 会忽略 seed：同样的文字每次结果都一样，重试要换文字写法。
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


class VoiceboxBroken(Exception):
    """Voicebox 出错，重试也没用，要请使用者处理（重开 app、在 app 里生成一句）。"""


class Voicebox:
    """Voicebox 本机 API 通讯封装。"""

    def __init__(self, cfg: dict[str, Any]) -> None:
        """初始化 Voicebox 连线配置。

        Args:
            cfg: 包含 url, profile, language 等设定的字典。
        """
        self.url = str(cfg.get("url", "http://127.0.0.1:17493")).rstrip("/")
        self.profile_name = str(cfg.get("profile", ""))
        self.language = str(cfg.get("language", "zh"))
        self.timeout = int(cfg.get("timeout", 180))
        self.cleanup = bool(cfg.get("cleanup", True))
        self._profile: dict[str, Any] | None = None
        self.sent: list[str] = []  # 这次送出的生成 id，结束时再检查一遍有没有漏删

    def _get(self, path: str, timeout: int = 30) -> bytes:
        """送出 GET 请求。

        Args:
            path: 请求路径。
            timeout: 逾时秒数。

        Returns:
            伺服器回应位元组。

        Raises:
            VoiceboxBroken: 连线被拒绝。
        """
        try:
            with urllib.request.urlopen(f"{self.url}{path}", timeout=timeout) as r:
                return bytes(r.read())
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), ConnectionRefusedError):
                raise VoiceboxBroken("连不上 Voicebox：请从 Dock 打开 Voicebox") from e
            raise

    def check_ready(self) -> None:
        """模型没有载入就停下：由 API 载入会让 MLX 坏掉。

        Raises:
            VoiceboxBroken: 模型未载入。
        """
        health = json.loads(self._get("/health", 10).decode("utf-8"))
        if not health.get("model_loaded"):
            raise VoiceboxBroken(
                "Voicebox 的模型没有载入。请先在 Voicebox app 里用声音档生成一句话，再执行。"
            )

    def profile(self) -> dict[str, Any]:
        """查询并取得目前指定的声音档资料。

        Returns:
            声音档 profile 字典。

        Raises:
            RuntimeError: 找不到指定的声音档。
        """
        if self._profile is None:
            raw = self._get("/profiles").decode("utf-8")
            profiles: dict[str, dict[str, Any]] = {p["name"]: p for p in json.loads(raw)}
            if self.profile_name not in profiles:
                names = ", ".join(profiles)
                raise RuntimeError(f"找不到声音档「{self.profile_name}」，现有：{names}")
            self._profile = profiles[self.profile_name]
        return self._profile

    def generate(self, text: str, language: str | None = None) -> bytes:
        """送出生成，轮询到完成，回传 wav bytes。

        Args:
            text: 要念的文字。
            language: 指定发音语言。

        Returns:
            生成的 WAV 位元组资料。

        Raises:
            VoiceboxBroken: Voicebox 崩溃或连线中断。
            TimeoutError: 超过超时时间。
            RuntimeError: 生成出错。
        """
        p = self.profile()
        body = {
            "profile_id": p["id"],
            "text": text,
            "language": language or self.language or p.get("language") or "zh",
        }
        if p.get("default_engine"):
            body["engine"] = p["default_engine"]
        req = urllib.request.Request(
            f"{self.url}/generate",
            json.dumps(body).encode("utf-8"),
            {"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                gid = str(json.loads(r.read().decode("utf-8"))["id"])
            self.sent.append(gid)
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), ConnectionRefusedError):
                raise VoiceboxBroken("连不上 Voicebox：可能已经关闭或崩溃") from e
            raise
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            h = json.loads(self._get(f"/history/{gid}").decode("utf-8"))
            if h.get("status") == "completed":
                wav = self._get(f"/audio/{gid}", 60)
                if self.cleanup:
                    self.delete(gid)  # 音档已经拿到，不留在 Voicebox 的纪录里
                return wav
            if h.get("status") in ("failed", "error", "cancelled"):
                err = str(h.get("error") or h["status"])
                if self.cleanup:
                    self.delete(gid)
                if "no Stream(gpu" in err:
                    raise VoiceboxBroken(
                        f"Voicebox 内部出错（{err}）：请 ⌘Q 后从 Dock 重开，并在 app 里生成一句"
                    )
                raise RuntimeError(err)
            time.sleep(1)
        try:
            cancel_req = urllib.request.Request(f"{self.url}/generate/{gid}/cancel", method="POST")
            urllib.request.urlopen(cancel_req, timeout=10)
            if self.cleanup:
                self.delete(gid)
        except Exception:
            pass
        raise TimeoutError(f"超过 {self.timeout} 秒仍未完成")

    def delete(self, gid: str, tries: int = 3) -> bool:
        """删除一笔生成纪录（连同音档）。刚生成完时 Voicebox 可能还在处理档案，失败就隔一秒再试。

        Args:
            gid: 生成纪录 ID。
            tries: 重试次数。

        Returns:
            若成功删除回传 True。
        """
        for _ in range(tries):
            try:
                req = urllib.request.Request(f"{self.url}/history/{gid}", method="DELETE")
                urllib.request.urlopen(req, timeout=30)
                return True
            except urllib.error.HTTPError as e:
                if e.code == 404:  # 已经删掉了
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def list_history(self) -> list[dict[str, Any]]:
        """取得目前 Voicebox 的历史记录。

        Returns:
            历史记录字典列表。
        """
        raw = self._get("/history").decode("utf-8")
        result: list[dict[str, Any]] = json.loads(raw)
        return result
