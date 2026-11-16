"""Open WebUI 影片合成與分鏡工具混入類別。"""

from __future__ import annotations

from video_studio.adapters.openwebui_runner import EventEmitter, OpenWebUIRunner


class OpenWebUIVideoMixin:
    """提供影片時間軸、分鏡起草與合成匯出的 Open WebUI 工具方法。"""

    _runner: OpenWebUIRunner

    def _job(self, job: str) -> str:
        """驗證工作存在並回傳工作名稱。

        Args:
            job: 工作名稱。

        Returns:
            驗證後的工作名稱。
        """
        raise NotImplementedError

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

    async def video_from_html(
        self,
        job: str,
        __event_emitter__: EventEmitter | None = None,
    ) -> str:
        """HTML/GSAP 影片：使用專案內 HyperFrames 將 input/index.html 渲染成影片、合成配音、燒字幕、驗收。

        Args:
            job: 工作名称。
            __event_emitter__: Open WebUI 状态回报函式。

        Returns:
            HTML 影片合成結果。
        """
        cmd = ["video", "html", self._job(job)]
        return await self._runner.guard(
            __event_emitter__,
            lambda: self._runner.run_command(cmd, __event_emitter__, "HyperFrames HTML 影片"),
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
