"""Subprocess runner and environment helper for Open WebUI tool adapter.

Handles path discovery, environment setup, streaming process logs,
and Voicebox API readiness checks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import urllib.request
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from video_studio.config.settings import PROJECT_ROOT, load_config

logger = logging.getLogger(__name__)

PRIVACY_HINT = (
    "macOS 拒绝 Open WebUI 读取这个资料夹（Operation not permitted）。Open WebUI 由 launchd 在背景执行，"
    "预设没有读取「桌面」「文件」「下载」的权限。处理方式二选一：\n"
    "1. 把专案搬到不受保护的位置（例如 ~/Projects/video-studio），再到工具的「阀门」更新 project_dir；\n"
    "2. 系统设定 → 隐私权与安全性 → 完全取用磁碟 → ＋，按 ⌘⇧G 输入 "
    "~/.local/share/uv/tools/open-webui/bin/ 选 python，之后重启 Open WebUI 服务。"
)

EventEmitter = Callable[[dict[str, Any]], Awaitable[None]]


class ToolValves(BaseModel):
    """Configuration valves exposed to Open WebUI admin interface."""

    project_dir: str = Field(
        default=str(PROJECT_ROOT),
        description="video-studio 程式资料夹的完整路径",
    )
    workspace_dir: str = Field(
        default="",
        description="工作区（讲稿、音档、成品）的完整路径；留空表示由设定档读取",
    )
    extra_path: str = Field(
        default="/opt/homebrew/bin:/usr/local/bin:~/.local/bin:~/.cargo/bin",
        description="找 uv、ffmpeg 用的额外路径（Open WebUI 的环境里常常找不到 Homebrew 装的程式）",
    )
    voicebox_url: str = Field(default="http://127.0.0.1:17493", description="Voicebox 本机 API")
    timeout_minutes: int = Field(default=90, description="单一工作最长执行几分钟（build 可能要很久）")


class OpenWebUIRunner:
    """Helper class managing execution environment, process runner, and status emission."""

    def __init__(self, valves: ToolValves) -> None:
        """Initialize runner with given valves.

        Args:
            valves: Configured tool valves.
        """
        self.valves = valves

    def env(self) -> dict[str, str]:
        """Construct the subprocess environment variables.

        Returns:
            Dictionary of environment variables with PATH and workspace overrides.
        """
        cfg = load_config()
        env_dict = cfg.process_env()
        extra = ":".join(str(Path(p).expanduser()) for p in self.valves.extra_path.split(":") if p)
        env_dict["PATH"] = f"{extra}:{env_dict.get('PATH', '')}"
        env_dict["PYTHONUNBUFFERED"] = "1"
        if self.valves.workspace_dir:
            env_dict["SPLIT_VOICE_WORKSPACE"] = str(Path(self.valves.workspace_dir).expanduser())
        return env_dict

    def project(self) -> Path:
        """Locate and validate the project root directory.

        Returns:
            The Path pointing to the project directory.

        Raises:
            RuntimeError: If directory cannot be accessed or project files are missing.
        """
        p = Path(self.valves.project_dir).expanduser()
        try:
            found = (p / "pyproject.toml").exists()
            if found:
                next(iter(p.iterdir()), None)  # 实际读一次，才会碰到 macOS 的隐私权限制
        except PermissionError as e:
            raise RuntimeError(f"{p}：{PRIVACY_HINT}") from e
        if not found:
            hint = f"\n（也可能是 {PRIVACY_HINT}）" if "Desktop" in str(p) or "Documents" in str(p) else ""
            raise RuntimeError(f"找不到专案：{p}。请到工具的「阀门」设定 project_dir。{hint}")
        return p

    def workspace(self) -> Path:
        """Locate and validate the workspace directory.

        Returns:
            The Path pointing to the workspace root.

        Raises:
            RuntimeError: If permission is denied.
        """
        if self.valves.workspace_dir:
            ws = Path(self.valves.workspace_dir).expanduser()
        else:
            cfg = load_config()
            ws = cfg.workspace_dir or (cfg.data_dir / "workspace")
        try:
            ws.mkdir(parents=True, exist_ok=True)
            next(iter(ws.iterdir()), None)
        except PermissionError as e:
            raise RuntimeError(f"{ws}：{PRIVACY_HINT}") from e
        return ws

    def which(self, name: str) -> str:
        """Find an executable in the environment PATH.

        Args:
            name: The binary name, e.g. `uv` or `ffmpeg`.

        Returns:
            The resolved executable path.

        Raises:
            RuntimeError: If the binary is not found.
        """
        found = shutil.which(name, path=self.env().get("PATH"))
        if not found:
            hint = f"找不到 {name}。请先安装（brew install {name}），或在「阀门」的 extra_path 加上它的路径。"
            raise RuntimeError(hint)
        return found

    def job_dirs(self) -> list[str]:
        """List existing jobs in the workspace.

        Returns:
            List of job identifiers in format `type/name`.
        """
        ws = self.workspace()
        out: list[str] = []
        for t in ("extract", "dub", "generate"):
            d = ws / t
            if d.exists():
                out.extend([f"{t}/{j.name}" for j in sorted(d.iterdir()) if (j / "job.toml").exists()])
        return out

    def resolve_job(self, job: str) -> str:
        """检查工作存在；回传原名称（交给指令自己解析「名称」或「类型/名称」）。

        Args:
            job: 工作名称，例如 bart-risk-taking。

        Returns:
            原工作名称字串。

        Raises:
            RuntimeError: 当找不到工作时。
        """
        names = self.job_dirs()
        if job in names or any(n.split("/", 1)[1] == job for n in names):
            return job
        names_str = ", ".join(names) or "没有"
        raise RuntimeError(f"找不到工作「{job}」。现有工作：{names_str}。新工作请先用 create_job 建立。")

    def check_voicebox_ready(self) -> None:
        """模型没有载入就停下：由 API 载入会让 MLX 坏掉。

        Raises:
            RuntimeError: 当连不上 Voicebox 或模型尚未载入时。
        """
        url = self.valves.voicebox_url.rstrip("/")
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=5) as r:
                health: dict[str, Any] = json.loads(r.read())
        except Exception as e:
            msg = "连不上 Voicebox。请从 Dock 打开 Voicebox，在 app 里用声音档生成一句话，再试一次。"
            raise RuntimeError(msg) from e
        if not health.get("model_loaded"):
            msg = "Voicebox 的模型还没载入。请先在 Voicebox app 里用声音档生成一句话，再试一次。"
            raise RuntimeError(msg)

    @staticmethod
    async def emit_status(
        emitter: EventEmitter | None,
        text: str,
        done: bool = False,
        error: bool = False,
    ) -> None:
        """Emit a status event to Open WebUI.

        Args:
            emitter: Open WebUI event emitter callback.
            text: Status description message.
            done: Whether the execution has finished.
            error: Whether this status represents a failure.
        """
        if emitter:
            data: dict[str, Any] = {"description": text, "done": done, "hidden": False}
            if error:
                data["error"] = True
            await emitter({"type": "status", "data": data})

    async def _stream_reader(
        self,
        stream: asyncio.StreamReader | None,
        lines: list[str],
        emitter: EventEmitter | None,
        label: str,
    ) -> None:
        """Stream process stdout and notify status emitter.

        Args:
            stream: Process stdout stream reader.
            lines: Accumulator list for collected output lines.
            emitter: Status event emitter.
            label: Human-readable action label.
        """
        if not stream:
            return
        async for raw in stream:
            line = raw.decode("utf-8", "replace").rstrip()
            if line.startswith(("Installed ", "Downloaded ", "Resolved ", "Prepared ")) or "HF Hub" in line:
                continue
            lines.append(line)  # 空行也保留：讲稿里空行代表段落
            if line and line.lstrip().startswith(("[", "第", "完成", "要生成", "停止")):
                await self.emit_status(emitter, f"{label}：{line.strip()[:90]}")

    async def run_command(
        self,
        args: list[str],
        emitter: EventEmitter | None,
        label: str,
        stdin_text: str | None = None,
    ) -> str:
        """在专案资料夹执行指令，进度即时显示在状态列；失败就丢出错误（附最后几行输出）。

        Args:
            args: 命令列参数。
            emitter: 状态回报函式。
            label: 动作名称标签。
            stdin_text: 输入文字。

        Returns:
            执行的标准输出内容。

        Raises:
            RuntimeError: 执行逾时或非 0 结束代码时。
        """
        proj = self.project()
        uv = self.which("uv")
        self.which("ffmpeg")
        await self.emit_status(emitter, f"{label}…")
        full_cmd = [uv, "run", "python", "-m", "video_studio.entrypoints.cli", *args]
        proc = await asyncio.create_subprocess_exec(
            *full_cmd,
            cwd=proj,
            env=self.env(),
            stdin=asyncio.subprocess.PIPE if stdin_text is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        if stdin_text is not None and proc.stdin:
            proc.stdin.write(stdin_text.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
        lines: list[str] = []
        try:
            await asyncio.wait_for(
                asyncio.gather(self._stream_reader(proc.stdout, lines, emitter, label), proc.wait()),
                self.valves.timeout_minutes * 60,
            )
        except asyncio.TimeoutError as e:
            proc.kill()
            tail_lines = "\n".join(lines[-15:])
            raise RuntimeError(
                f"{label}超过 {self.valves.timeout_minutes} 分钟没完成，已中止。最后的输出：\n{tail_lines}"
            ) from e
        if proc.returncode != 0:
            tail = "\n".join(lines[-20:])
            if "Operation not permitted" in tail or "PermissionError" in tail:
                tail += f"\n\n{PRIVACY_HINT}"
            raise RuntimeError(f"{label}失败（结束代码 {proc.returncode}）：\n{tail}")
        await self.emit_status(emitter, f"{label}完成", done=True)
        return "\n".join(lines)

    async def guard(
        self,
        emitter: EventEmitter | None,
        action: Callable[[], Awaitable[str]],
    ) -> str:
        """统一的错误回报：在状态列标示失败，并回传「❌ 错误」让模型转告使用者。

        Args:
            emitter: Open WebUI 状态回报器。
            action: 执行操作非同步函式。

        Returns:
            执行文字或错误提示。
        """
        try:
            return await action()
        except Exception as e:
            msg = str(e).splitlines()[0][:100]
            await self.emit_status(emitter, f"错误：{msg}", done=True, error=True)
            return f"❌ 错误：{e}\n\n（请把这个错误原样告诉使用者，不要自行假设已经完成。）"

    async def run_ok(self, args: list[str], emitter: EventEmitter | None, label: str) -> str:
        """检查类指令：有错误时结束代码不是 0，但结果本身就是要给使用者看的报告。

        Args:
            args: 命令参数。
            emitter: 状态回报函式。
            label: 标签。

        Returns:
            指令输出字串。
        """
        try:
            return await self.run_command(args, emitter, label)
        except RuntimeError as e:
            return str(e).split("：", 1)[-1]
