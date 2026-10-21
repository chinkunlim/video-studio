"""
title: Split Voice 讲稿配音
description: 讲稿配音与影片：依工作（extract / dub / generate）管理素材，
用 Voicebox 配音、产生繁体字幕，并用 pptx 分镜或海报做成影片。
version: 2.0.0
"""
# 安装：Open WebUI → 工作区（Workspace）→ 工具（Tools）→ 新增，把整个档案贴上并储存，
# 再到「阀门」（Valves）设定 project_dir。说明见 openwebui/README.md。

from __future__ import annotations

import logging
import re
from pathlib import Path

from video_studio.adapters.openwebui_runner import EventEmitter, OpenWebUIRunner, ToolValves

logger = logging.getLogger(__name__)


class Tools:
    """Open WebUI integration tools for video studio."""

    Valves = ToolValves

    def __init__(self) -> None:
        """Initialize the Open WebUI tools adapter."""
        self.valves = self.Valves()
        self._runner = OpenWebUIRunner(self.valves)

    # ---------- 共用 ----------

    def _env(self) -> dict[str, str]:
        """Construct the subprocess environment variables.

        Returns:
            Dictionary of environment variables with PATH and workspace overrides.
        """
        return self._runner.env()

    def _project(self) -> Path:
        """Locate and validate the project root directory.

        Returns:
            The Path pointing to the project directory.
        """
        return self._runner.project()

    def _workspace(self) -> Path:
        """Locate and validate the workspace directory.

        Returns:
            The Path pointing to the workspace root.
        """
        return self._runner.workspace()

    def _which(self, name: str) -> str:
        """Find an executable in the environment PATH.

        Args:
            name: The binary name, e.g. uv or ffmpeg.

        Returns:
            The resolved executable path.
        """
        return self._runner.which(name)

    def _job_dirs(self) -> list[str]:
        """List existing jobs in the workspace.

        Returns:
            List of job identifiers in format type/name.
        """
        return self._runner.job_dirs()

    def _job(self, job: str) -> str:
        """检查工作存在；回传原名称（交给指令自己解析「名称」或「类型/名称」）。

        Args:
            job: 工作名称，例如 bart-risk-taking。

        Returns:
            原工作名称字串。
        """
        return self._runner.resolve_job(job)

    def _voicebox_ready(self) -> None:
        """模型没有载入就停下：由 API 载入会让 MLX 坏掉。"""
        self._runner.check_voicebox_ready()

    # ---------- 环境与工作 ----------

    async def check_environment(self, __event_emitter__: EventEmitter | None = None) -> str:
        """检查执行环境：程式、工作区、uv、ffmpeg、Voicebox 是否开着、模型是否已载入，并列出所有工作。

        Args:
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            环境检查总结报告。
        """

        async def action() -> str:
            """执行环境检查。"""
            proj = self._project()
            report = [
                f"✅ 程式：{proj}",
                f"✅ 工作区：{self._workspace()}",
                f"✅ uv：{self._which('uv')}",
                f"✅ ffmpeg：{self._which('ffmpeg')}",
            ]
            try:
                self._voicebox_ready()
                report.append("✅ Voicebox：已开启，模型已载入")
            except RuntimeError as e:
                report.append(f"⚠️ Voicebox：{e}（提取音档、查看与检查工作不需要 Voicebox）")
            report.append(f"工作：{', '.join(self._job_dirs()) or '还没有'}")
            await self._runner.emit_status(__event_emitter__, "环境检查完成", done=True)
            return "\n".join(report)

        return await self._runner.guard(__event_emitter__, action)

    async def list_jobs(self, __event_emitter__: EventEmitter | None = None) -> str:
        """列出所有工作：类型（extract / dub / generate）、名称、标题、最新成品版本。

        Args:
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            所有工作的清单文字。
        """
        return await self._runner.guard(
            __event_emitter__,
            lambda: self._runner.run_command(["job", "list"], __event_emitter__, "列出工作"),
        )

    async def _write_script_md(
        self,
        job_type: str,
        name: str,
        title: str,
        script_text: str,
        emitter: EventEmitter | None,
    ) -> str:
        """Write speech script and format it to script.md.

        Args:
            job_type: Job type (dub / generate).
            name: Job slug name.
            title: Job title.
            script_text: Raw input script text.
            emitter: Status emitter.

        Returns:
            Formatted script note.
        """
        d = self._workspace() / job_type / name / "input"
        d.mkdir(parents=True, exist_ok=True)
        raw = d / "speech_script.txt"
        raw.write_text(script_text, encoding="utf-8")
        body = await self._runner.run_command(["narrate", "format", str(raw)], emitter, "整理讲稿格式")
        text = body if "## " in script_text else "## 投影片 1\n" + body
        (d / "script.md").write_text(f"# 讲稿：{title or name}\n\n{text}\n", encoding="utf-8")
        note = "\n\n已存成 input/script.md（原文在 input/speech_script.txt）。"
        if "## " not in script_text:
            note += "没有标示投影片，全部先放在「投影片 1」，请依实际页数加上「## 投影片 N」。"
        return note

    async def create_job(
        self,
        job_type: str,
        name: str,
        title: str = "",
        script_text: str = "",
        __event_emitter__: EventEmitter | None = None,
    ) -> str:
        """建立一份新工作（资料夹含 job.toml、input/、review/、work/、output/，以及范本）。

        Args:
            job_type: extract（只提取声音）、dub（给影片，用 Voicebox 重新配音）、generate（完整生成）。
            name: 资料夹名称，只能用小写英文、数字、连字号，例如 final-report。
            title: 中文标题，例如「期末报告」。
            script_text: 讲稿全文（选填）。可用「## 投影片 N」标示换页；空行分段落。
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            建立结果与检查报告。
        """

        async def action() -> str:
            """执行建立工作与讲稿格式化。"""
            if job_type not in ("extract", "dub", "generate"):
                raise RuntimeError("job_type 只能是 extract、dub、generate 其中一个")
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
                msg = (
                    f"名称「{name}」不合格：只能用小写英文、数字、连字号，例如 final-report。中文放在 title。"
                )
                raise RuntimeError(msg)
            out = await self._runner.run_command(
                ["job", "init", job_type, name, "--title", title or name],
                __event_emitter__,
                "建立工作",
            )
            if script_text.strip() and job_type in ("dub", "generate"):
                note = await self._write_script_md(job_type, name, title, script_text, __event_emitter__)
                out += note
            chk = await self._runner.run_ok(["job", "check", name], __event_emitter__, "检查工作")
            return f"{out}\n\n检查结果：\n{chk}"

        return await self._runner.guard(__event_emitter__, action)

    async def check_job(self, job: str, __event_emitter__: EventEmitter | None = None) -> str:
        """检查一份工作的设定与所有输入档（job.toml、script.md、scenes.toml、词汇表、pptx…）。

        Args:
            job: 工作名称，例如 bart-risk-taking。
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            检查结果。
        """
        return await self._runner.guard(
            __event_emitter__,
            lambda: self._runner.run_ok(["job", "check", self._job(job)], __event_emitter__, "检查工作"),
        )

    async def approve_review(
        self,
        job: str,
        file: str,
        __event_emitter__: EventEmitter | None = None,
    ) -> str:
        """使用者确认 review/ 里的草稿后，把它移进 input/（原本的会备份到 input/.previous/）。

        Args:
            job: 工作名称。
            file: review/ 里的档名，例如 scenes.toml、script.md。
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            草稿审核结果。
        """
        cmd = ["job", "approve", self._job(job), file]
        return await self._runner.guard(
            __event_emitter__,
            lambda: self._runner.run_command(cmd, __event_emitter__, "确认草稿"),
        )

    # ---------- 只提取声音 ----------

    async def extract_audio(
        self,
        video_path: str,
        make_voice_samples: bool = False,
        __event_emitter__: EventEmitter | None = None,
    ) -> str:
        """从影片（mp4 等）提取音档，存成同名的 .wav（单声道 48kHz）。

        Args:
            video_path: 影片的完整路径，例如 /Users/me/Movies/talk.mp4。
            make_voice_samples: 是否另外切成 10–20 秒的声音样本（给 Voicebox 建复制声音）。
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            提取输出文字。
        """

        async def action() -> str:
            """执行音讯提取。"""
            v = Path(video_path).expanduser()
            if not v.exists():
                raise RuntimeError(f"找不到影片：{v}")
            args = ["extract", str(v)]
            if make_voice_samples:
                args.extend(["--samples", str(v.with_name(v.stem + "_samples"))])
            return await self._runner.run_command(args, __event_emitter__, "提取音档")

        return await self._runner.guard(__event_emitter__, action)

    # ---------- 配音 ----------

    async def list_lines(self, job: str, __event_emitter__: EventEmitter | None = None) -> str:
        """列出讲稿的每一行：行号、投影片、字幕文字、送给 Voicebox 的念法，以及有没有音档。

        Args:
            job: 工作名称。
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            每一行的讲稿资讯。
        """
        cmd = ["narrate", "lines", self._job(job)]
        return await self._runner.guard(
            __event_emitter__,
            lambda: self._runner.run_command(cmd, __event_emitter__, "列出讲稿"),
        )

    async def scan_vocabulary(self, job: str, __event_emitter__: EventEmitter | None = None) -> str:
        """检查讲稿的词汇：没有放进 {{}} 的英文、词汇表里没有的 key，以及每个词用在哪几行、是否试听过。

        Args:
            job: 工作名称。
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            词汇检查结果。
        """
        cmd = ["narrate", "scan", self._job(job)]
        return await self._runner.guard(
            __event_emitter__,
            lambda: self._runner.run_command(cmd, __event_emitter__, "检查词汇"),
        )

    async def list_vocabulary(self, __event_emitter__: EventEmitter | None = None) -> str:
        """列出共用词汇表（shared/vocabulary.tsv）：key、类型、字幕显示、Voicebox 念法、是否试听过、备注。

        Args:
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            词汇表内容。
        """
        return await self._runner.guard(
            __event_emitter__,
            lambda: self._runner.run_command(["narrate", "vocab", "list"], __event_emitter__, "读取词汇表"),
        )

    async def set_vocabulary(
        self,
        key: str,
        subtitle: str = "",
        tts: str = "",
        word_type: str = "",
        tested: str = "",
        note: str = "",
        __event_emitter__: EventEmitter | None = None,
    ) -> str:
        """新增或修改词汇表的一个特殊词。字幕显示和 Voicebox 念法可以不同（例如字幕 BART、念 bart）。

        Args:
            key: 讲稿里 {{key}} 的名称，只能用英文字母、数字、底线。
            subtitle: 字幕显示的文字（新词必填）。
            tts: 送给 Voicebox 念的文字；留空表示同字幕。
            word_type: 类型，例如 缩写、人名、术语。
            tested: 试听通过的日期，例如 2026-10-18。
            note: 备注。
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            词汇设定结果。
        """

        async def action() -> str:
            """执行更新词汇表。"""
            args = ["narrate", "vocab", "set", key]
            flags = [
                ("--subtitle", subtitle),
                ("--tts", tts),
                ("--type", word_type),
                ("--tested", tested),
                ("--note", note),
            ]
            for flag, val in flags:
                if val:
                    args.extend([flag, val])
            return await self._runner.run_command(args, __event_emitter__, "更新词汇表")

        return await self._runner.guard(__event_emitter__, action)

    async def build_narration(self, job: str, __event_emitter__: EventEmitter | None = None) -> str:
        """产生配音和字幕：生成还没有音档的句子（Voicebox）→ 检查 → 拼接 → 字幕。

        Args:
            job: 工作名称。
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            产生配音结果。
        """

        async def action() -> str:
            """执行配音生成。"""
            name = self._job(job)
            self._voicebox_ready()
            out = await self._runner.run_command(["narrate", "build", name], __event_emitter__, "产生配音")
            failed = [ln for ln in out.splitlines() if "全部失败" in ln]
            note = "\n\n⚠️ 句子生成失败：可用 audition_line 多试几次。" if failed else ""
            return out[-3000:] + note

        return await self._runner.guard(__event_emitter__, action)

    async def audition_line(
        self,
        job: str,
        line: int,
        takes: int = 4,
        __event_emitter__: EventEmitter | None = None,
    ) -> str:
        """某一行念得不好时，生成几个版本给使用者试听。

        Args:
            job: 工作名称。
            line: 行号（list_lines 列出的编号）。
            takes: 要几个版本，预设 4。
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            试听生成结果。
        """

        async def action() -> str:
            """执行试听生成。"""
            name = self._job(job)
            self._voicebox_ready()
            cmd = ["narrate", "audition", name, str(line), "--takes", str(takes)]
            return await self._runner.run_command(cmd, __event_emitter__, f"试听第 {line} 行")

        return await self._runner.guard(__event_emitter__, action)

    async def pick_take(
        self,
        job: str,
        line: int,
        take: int,
        __event_emitter__: EventEmitter | None = None,
    ) -> str:
        """选用 audition_line 产生的某个版本并锁定。

        Args:
            job: 工作名称。
            line: 行号。
            take: 版本编号（1、2、3…）。
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            版本选用结果。
        """
        cmd = ["narrate", "pick", self._job(job), str(line), str(take)]
        return await self._runner.guard(
            __event_emitter__,
            lambda: self._runner.run_command(cmd, __event_emitter__, "选用版本"),
        )

    async def try_spellings(
        self,
        spellings: str,
        language: str = "zh",
        carrier: str = "",
        __event_emitter__: EventEmitter | None = None,
    ) -> str:
        """试听一个词的几种写法，存在工作区 shared/vocab_tries/。

        Args:
            spellings: 几种写法，用「|」分隔，例如「Adjusted bart|Adjusted Bahrt|Adjusted 巴特」。
            language: zh（中文模式）或 en（英文模式）。
            carrier: 句型，用 {} 代表这个词。
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            试听结果。
        """

        async def action() -> str:
            """执行试听写法。"""
            self._voicebox_ready()
            words = [w.strip() for w in spellings.split("|") if w.strip()]
            if not words:
                raise RuntimeError("没有写法：请用「|」分隔，例如「Adjusted bart|Adjusted Bahrt」")
            args = ["narrate", "try", *words, "--lang", language]
            if carrier:
                args.extend(["--carrier", carrier])
            return await self._runner.run_command(args, __event_emitter__, "试听写法")

        return await self._runner.guard(__event_emitter__, action)

    async def clean_voicebox_history(
        self,
        confirm: bool = False,
        __event_emitter__: EventEmitter | None = None,
    ) -> str:
        """删除 Voicebox 里所有生成纪录（音档都已经存在工作里；复制声音的样本不会动）。

        Args:
            confirm: 使用者已经明确同意删除时才设为 true。
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            清除结果。
        """

        async def action() -> str:
            """执行清除 Voicebox 生成纪录。"""
            if not confirm:
                msg = "这会删除 Voicebox 里所有生成纪录，而且无法复原。请先确认同意后以 confirm=true 呼叫。"
                raise RuntimeError(msg)
            cmd = ["narrate", "clean", "--yes"]
            return await self._runner.run_command(cmd, __event_emitter__, "清除 Voicebox 纪录")

        return await self._runner.guard(__event_emitter__, action)

    # ---------- 影片 ----------

    async def video_slide_timing(
        self,
        job: str,
        __event_emitter__: EventEmitter | None = None,
    ) -> str:
        """列出每一页在配音里的起止时间、长度，以及每个 [click] 在页内第几秒。需要先 build_narration。

        Args:
            job: 工作名称。
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            每页时间长度报告。
        """
        cmd = ["video", "timing", self._job(job)]
        return await self._runner.guard(
            __event_emitter__,
            lambda: self._runner.run_command(cmd, __event_emitter__, "计算每页时间"),
        )

    async def video_draft_scenes(
        self,
        job: str,
        source: str = "auto",
        __event_emitter__: EventEmitter | None = None,
    ) -> str:
        """起草分镜到 <工作>/review/scenes.toml，并画出区域预览图。

        Args:
            job: 工作名称。
            source: auto、pptx 或 even。
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            起草分镜结果。
        """
        cmd = ["video", "scenes", self._job(job), "--source", source, "--force"]
        return await self._runner.guard(
            __event_emitter__,
            lambda: self._runner.run_command(cmd, __event_emitter__, "起草分镜"),
        )

    async def video_from_poster(
        self,
        job: str,
        __event_emitter__: EventEmitter | None = None,
    ) -> str:
        """海报影片：依 input/scenes.toml，镜头在海报上移动，加上外框、提示栏，合成配音、烧字幕、验收。

        Args:
            job: 工作名称。
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            海报影片合成结果。
        """
        cmd = ["video", "poster", self._job(job)]
        return await self._runner.guard(
            __event_emitter__,
            lambda: self._runner.run_command(cmd, __event_emitter__, "海报影片"),
        )

    async def video_from_pptx(
        self,
        job: str,
        __event_emitter__: EventEmitter | None = None,
    ) -> str:
        """PowerPoint 汇出影片（保留动画与转场）：移除旧录音，依配音设定换页与动画时间。

        Args:
            job: 工作名称。
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            PowerPoint 影片汇出结果。
        """
        cmd = ["video", "pptx", self._job(job)]
        return await self._runner.guard(
            __event_emitter__,
            lambda: self._runner.run_command(cmd, __event_emitter__, "PowerPoint 影片"),
        )

    async def video_mux(
        self,
        job: str,
        video_path: str,
        __event_emitter__: EventEmitter | None = None,
    ) -> str:
        """把一支现成的画面影片跟配音合成，烧字幕并验收。

        Args:
            job: 工作名称。
            video_path: 画面影片（完整路径，或 input/ 里的档名）。
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            合成影片结果。
        """
        cmd = ["video", "mux", self._job(job), "--video", video_path]
        return await self._runner.guard(
            __event_emitter__,
            lambda: self._runner.run_command(cmd, __event_emitter__, "合成影片"),
        )
