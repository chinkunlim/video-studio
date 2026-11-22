"""Studio MCP tool registrations for AI drafting, bilingual subtitles, planning, and avatars."""

from __future__ import annotations

import json
from collections.abc import Callable

from mcp.server.mcpserver import MCPServer

from video_studio.services import planner, review_history, script_drafter
from video_studio.services.narrate.core import bilingual
from video_studio.services.video import avatar_overlay
from video_studio.services.video import video as video_mod

ConfirmGuard = Callable[[bool, str], str | None]


def register_studio_read_tools(mcp: MCPServer) -> None:
    """Register read-only Studio inspection MCP tools.

    Args:
        mcp: Target MCPServer instance.
    """

    @mcp.tool()
    def mcp_avatar_status() -> str:
        """Return availability status of Route B (lightweight) and Route A (SadTalker)."""
        return json.dumps(avatar_overlay.get_avatar_status(), ensure_ascii=False)

    @mcp.tool()
    def mcp_list_review_snapshots(job_name: str) -> str:
        """List saved needs_review/<job>/ snapshots ordered newest first.

        Args:
            job_name: Job name.

        Returns:
            JSON string of snapshot metadata entries.
        """
        return json.dumps(review_history.list_snapshots(job_name), ensure_ascii=False)

    @mcp.tool()
    def mcp_get_plan_status(run_id: str) -> str:
        """Get status and output of a background agy CLI planning run.

        Args:
            run_id: Planning run identifier.

        Returns:
            JSON string with status, output text, and error if any.
        """
        return json.dumps(planner.get_plan_status(run_id), ensure_ascii=False)


def _register_draft_script_tool(mcp: MCPServer, require_confirm: ConfirmGuard) -> None:
    """Register mcp_draft_script tool on MCPServer.

    Args:
        mcp: Target MCPServer instance.
        require_confirm: Confirmation guard callback.
    """

    @mcp.tool()
    def mcp_draft_script(
        job_name: str, instruction: str = "", language: str = "zh", confirm: bool = False
    ) -> str:
        """Draft script.md into needs_review/<job>/script.md (requires confirm=True).

        Args:
            job_name: Job name.
            instruction: Prompt or topic guidance.
            language: Spoken language code (zh, en, ja, ko).
            confirm: Must be True to generate and write script draft.

        Returns:
            Draft summary or confirmation prompt.
        """
        denied = require_confirm(confirm, f"為 {job_name} 起草講稿至 needs_review/")
        if denied:
            return denied
        path, _ = script_drafter.draft_script_to_review(
            job_name=job_name, instruction=instruction, language=language
        )
        return f"已生成講稿草稿：{path}"


def _register_bilingual_tool(mcp: MCPServer, require_confirm: ConfirmGuard) -> None:
    """Register mcp_generate_bilingual_subtitles tool on MCPServer.

    Args:
        mcp: Target MCPServer instance.
        require_confirm: Confirmation guard callback.
    """

    @mcp.tool()
    def mcp_generate_bilingual_subtitles(
        job_name: str, target_lang: str = "zh-TW", model: str = "", confirm: bool = False
    ) -> str:
        """Translate input/script.md into work/<job>/script_bilingual.tsv (requires confirm=True).

        Args:
            job_name: Job name.
            target_lang: Target secondary subtitle language.
            model: Optional agy CLI model ID.
            confirm: Must be True to write bilingual subtitle TSV.

        Returns:
            Translation summary or confirmation prompt.
        """
        denied = require_confirm(confirm, f"為 {job_name} 翻譯雙語字幕 ({target_lang})")
        if denied:
            return denied
        tsv_path, count = bilingual.translate_job_script_bilingual(job_name, target_lang, model)
        return f"已完成 {count} 句雙語字幕翻譯：{tsv_path}"


def register_studio_script_tools(mcp: MCPServer, require_confirm: ConfirmGuard) -> None:
    """Register mutating AI script drafting and bilingual subtitle MCP tools.

    Args:
        mcp: Target MCPServer instance.
        require_confirm: Confirmation guard callback.
    """
    _register_draft_script_tool(mcp, require_confirm)
    _register_bilingual_tool(mcp, require_confirm)


def _register_start_plan_tool(mcp: MCPServer, require_confirm: ConfirmGuard) -> None:
    """Register mcp_start_plan tool on MCPServer.

    Args:
        mcp: Target MCPServer instance.
        require_confirm: Confirmation guard callback.
    """

    @mcp.tool()
    def mcp_start_plan(
        job_name: str, instruction: str = "", mode: str = "html", confirm: bool = False
    ) -> str:
        """Start a background agy CLI planning run for a job (requires confirm=True).

        Args:
            job_name: Job name.
            instruction: Planning instruction.
            mode: Target visual mode ('html' or 'poster').
            confirm: Must be True to launch agy CLI planning.

        Returns:
            JSON string of run handle or confirmation prompt.
        """
        denied = require_confirm(confirm, f"啟動 {job_name} 的 agy {mode} 規劃任務")
        if denied:
            return denied
        return json.dumps(planner.start_agy_plan(job_name, instruction, mode), ensure_ascii=False)


def _register_restore_snapshot_tool(mcp: MCPServer, require_confirm: ConfirmGuard) -> None:
    """Register mcp_restore_review_snapshot tool on MCPServer.

    Args:
        mcp: Target MCPServer instance.
        require_confirm: Confirmation guard callback.
    """

    @mcp.tool()
    def mcp_restore_review_snapshot(job_name: str, snap_id: str, confirm: bool = False) -> str:
        """Restore a saved needs_review snapshot (requires confirm=True).

        Args:
            job_name: Job name.
            snap_id: Snapshot identifier to restore.
            confirm: Must be True to overwrite current review drafts.

        Returns:
            JSON string of restore metadata or confirmation prompt.
        """
        denied = require_confirm(confirm, f"將 {job_name} 草稿退回至快照 {snap_id}")
        if denied:
            return denied
        return json.dumps(review_history.restore_snapshot(job_name, snap_id), ensure_ascii=False)


def register_studio_plan_tools(mcp: MCPServer, require_confirm: ConfirmGuard) -> None:
    """Register mutating agy CLI planning and review snapshot restore MCP tools.

    Args:
        mcp: Target MCPServer instance.
        require_confirm: Confirmation guard callback.
    """
    _register_start_plan_tool(mcp, require_confirm)
    _register_restore_snapshot_tool(mcp, require_confirm)


def _register_avatar_tool(mcp: MCPServer, require_confirm: ConfirmGuard) -> None:
    """Register mcp_render_avatar_video tool on MCPServer.

    Args:
        mcp: Target MCPServer instance.
        require_confirm: Confirmation guard callback.
    """

    @mcp.tool()
    def mcp_render_avatar_video(
        job_name: str, engine: str = "lightweight", position: str = "bottom-right", confirm: bool = False
    ) -> str:
        """Composite an avatar presenter overlay onto the latest rendered video (requires confirm=True).

        Args:
            job_name: Job name.
            engine: 'lightweight' or 'sadtalker'.
            position: Corner placement ('bottom-right', 'bottom-left', 'top-right', 'top-left').
            confirm: Must be True to render and overwrite output video.

        Returns:
            Result summary or confirmation prompt.
        """
        denied = require_confirm(confirm, f"為 {job_name} 合成 {engine} Avatar 畫面")
        if denied:
            return denied
        res = avatar_overlay.apply_avatar_to_job(job_name=job_name, engine=engine, position=position)
        return f"已完成 {res.engine} Avatar 合成：{res.composited_video}"


def _register_mux_tool(mcp: MCPServer, require_confirm: ConfirmGuard) -> None:
    """Register mcp_mux_external_video tool on MCPServer.

    Args:
        mcp: Target MCPServer instance.
        require_confirm: Confirmation guard callback.
    """

    @mcp.tool()
    def mcp_mux_external_video(
        job_name: str, video_path: str, version: str | None = None, confirm: bool = False
    ) -> str:
        """Mux an external video file with narration audio and subtitles (requires confirm=True).

        Args:
            job_name: Job name.
            video_path: Path to source video or filename inside input/.
            version: Optional output version name.
            confirm: Must be True to write muxed output files.

        Returns:
            Mux summary or confirmation prompt.
        """
        denied = require_confirm(confirm, f"將外部影片 {video_path} 與 {job_name} 配音合成")
        return denied or video_mod.mux_external_video(job_name, video_path, version)


def register_studio_media_tools(mcp: MCPServer, require_confirm: ConfirmGuard) -> None:
    """Register mutating Avatar and external video mux MCP tools.

    Args:
        mcp: Target MCPServer instance.
        require_confirm: Confirmation guard callback.
    """
    _register_avatar_tool(mcp, require_confirm)
    _register_mux_tool(mcp, require_confirm)
