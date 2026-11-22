"""MCP server entrypoint for video-studio (Stdio and Streamable HTTP).

Exposes read-only and confirm-gated mutating tools backed by the shared
`services` layer. Never prints to stdout so stdio JSON-RPC stays clean.
"""

from __future__ import annotations

import json
import logging

from mcp.server.mcpserver import MCPServer

from video_studio.config.logging_setup import setup_logging
from video_studio.config.settings import AppConfig, load_config
from video_studio.services import planner, review_history, script_drafter
from video_studio.services.common import job as J
from video_studio.services.extract_audio import extract as extract_mod
from video_studio.services.narrate import narrate as narrate_mod
from video_studio.services.narrate.core import bilingual, vocab
from video_studio.services.sv import approve_file, check_job_status, init_job, list_jobs
from video_studio.services.video import avatar_overlay
from video_studio.services.video import release as release_mod
from video_studio.services.video import video as video_mod

logger = logging.getLogger(__name__)


def _require_confirm(confirm: bool, action_desc: str) -> str | None:
    """Return a refusal message when a mutating MCP tool lacks confirmation.

    Args:
        confirm: Explicit user confirmation flag.
        action_desc: Human-readable summary of the pending mutation.

    Returns:
        Refusal message if not confirmed, otherwise None.
    """
    if confirm:
        return None
    return f"需要確認：此操作將{action_desc}。請先向使用者確認後，以 confirm=True 重新呼叫。"


def _register_job_read_tools(mcp: MCPServer) -> None:
    """Register read-only job MCP tools.

    Args:
        mcp: Target MCPServer instance.
    """

    @mcp.tool()
    def mcp_list_jobs() -> str:
        """List all jobs in the workspace."""
        return list_jobs()

    @mcp.tool()
    def mcp_check_job(job_name: str) -> str:
        """Validate a job's configuration and input files.

        Args:
            job_name: Job name or type/name identifier.

        Returns:
            Validation report text.
        """
        _, report = check_job_status(job_name)
        return report


def _register_job_write_tools(mcp: MCPServer) -> None:
    """Register mutating job MCP tools gated by confirm=True.

    Args:
        mcp: Target MCPServer instance.
    """

    @mcp.tool()
    def mcp_init_job(job_type: str, name: str, title: str = "", confirm: bool = False) -> str:
        """Create a new job workspace directory (mutating; requires confirm=True).

        Args:
            job_type: extract, dub, or generate.
            name: Lowercase slug name.
            title: Optional display title.
            confirm: Must be True to create files.

        Returns:
            Creation summary or confirmation prompt.
        """
        denied = _require_confirm(confirm, f"建立工作 {job_type}/{name}")
        return denied or init_job(job_type, name, title)

    @mcp.tool()
    def mcp_approve_file(job_name: str, filename: str, confirm: bool = False) -> str:
        """Move an approved draft from review/ to input/ (mutating; requires confirm=True).

        Args:
            job_name: Job name.
            filename: File inside review/ to approve.
            confirm: Must be True to move files.

        Returns:
            Approval result or confirmation prompt.
        """
        denied = _require_confirm(confirm, f"將 {job_name}/review/{filename} 核可移入 input/")
        return denied or approve_file(job_name, filename)


def _register_narrate_read_tools(mcp: MCPServer) -> None:
    """Register read-only narration and vocabulary MCP tools.

    Args:
        mcp: Target MCPServer instance.
    """

    @mcp.tool()
    def mcp_list_vocab() -> str:
        """List all pronunciation entries in shared vocabulary.tsv."""
        voc = vocab.load(J.vocabulary_path())
        return "\n".join(f"{{{{{k}}}}}\t{v.get('subtitle', '')}\t{v.get('tts', '')}" for k, v in voc.items())

    @mcp.tool()
    def mcp_list_lines(job_name: str) -> str:
        """List parsed script lines for a job.

        Args:
            job_name: Job name.

        Returns:
            Formatted script line listing.
        """
        return narrate_mod.list_lines(J.find(job_name))


def _register_narrate_write_tools(mcp: MCPServer) -> None:
    """Register mutating narration and vocabulary MCP tools.

    Args:
        mcp: Target MCPServer instance.
    """

    @mcp.tool()
    def mcp_set_vocab(key: str, subtitle: str = "", tts: str = "", confirm: bool = False) -> str:
        """Add or update a vocabulary entry (mutating; requires confirm=True).

        Args:
            key: Vocabulary key.
            subtitle: Subtitle display text.
            tts: Voicebox spoken text.
            confirm: Must be True to write vocabulary.tsv.

        Returns:
            Update confirmation or refusal prompt.
        """
        denied = _require_confirm(confirm, f"更新詞彙表 {{{{{key}}}}}")
        if denied:
            return denied
        voc_path = J.vocabulary_path()
        voc = vocab.load(voc_path)
        row = voc.get(key) or {k: "" for k in vocab.FIELDS}
        row["key"] = key
        row["subtitle"] = subtitle or row.get("subtitle", "")
        row["tts"] = tts or row.get("tts") or row["subtitle"] or key
        row["tts_lang"] = row.get("tts_lang") or "zh"
        voc[key] = row
        vocab.save(voc_path, voc)
        return f"已更新詞彙表：{{{{{key}}}}} -> {row['subtitle']} ({row['tts']})"

    @mcp.tool()
    def mcp_build_narration(job_name: str, confirm: bool = False) -> str:
        """Synthesize missing takes, concatenate audio, and write subtitles (requires confirm=True).

        Args:
            job_name: Job name.
            confirm: Must be True to generate audio and output version.

        Returns:
            Build summary or confirmation prompt.
        """
        denied = _require_confirm(confirm, f"為 {job_name} 生成配音與字幕並輸出新版本")
        return denied or narrate_mod.build_narration(J.find(job_name))


def _register_video_read_tools(mcp: MCPServer) -> None:
    """Register read-only video timing and check MCP tools.

    Args:
        mcp: Target MCPServer instance.
    """

    @mcp.tool()
    def mcp_video_timing(job_name: str, version: str | None = None) -> str:
        """Calculate per-slide timing from narration output.

        Args:
            job_name: Job name.
            version: Optional version name.

        Returns:
            Timing table summary.
        """
        return video_mod.calc_timing(job_name, version)

    @mcp.tool()
    def mcp_video_check(job_name: str, version: str | None = None) -> str:
        """Verify latest rendered video streams, duration, audio, and contact sheet.

        Args:
            job_name: Job name.
            version: Optional version name.

        Returns:
            Verification report text.
        """
        return video_mod.check_video(job_name, version)


def _register_video_release_tools(mcp: MCPServer) -> None:
    """Register video release publishing MCP tools.

    Args:
        mcp: Target MCPServer instance.
    """

    @mcp.tool()
    def mcp_publish_release(job_name: str, version: str | None = None, confirm: bool = False) -> str:
        """Publish a rendered version into output/<job>/releases/<vN>/ (requires confirm=True).

        Args:
            job_name: Job name.
            version: Optional version name (defaults to latest).
            confirm: Must be True to update releases/.

        Returns:
            Release summary message.
        """
        denied = _require_confirm(confirm, f"publish release for '{job_name}'")
        return denied or str(release_mod.publish_release(job_name, version)["message"])


def _register_video_write_tools(mcp: MCPServer) -> None:
    """Register mutating video rendering and audio extraction MCP tools.

    Args:
        mcp: Target MCPServer instance.
    """
    _register_video_release_tools(mcp)

    @mcp.tool()
    def mcp_draft_scenes(job_name: str, source: str = "auto", confirm: bool = False) -> str:
        """Draft scenes.toml and preview image into review/ (requires confirm=True).

        Args:
            job_name: Job name.
            source: auto, pptx, or even.
            confirm: Must be True to write review files.

        Returns:
            Draft summary or confirmation prompt.
        """
        denied = _require_confirm(confirm, f"起草 {job_name}/review/scenes.toml")
        return denied or video_mod.draft_scenes(job_name, source=source, force=True)

    @mcp.tool()
    def mcp_render_poster_video(job_name: str, version: str | None = None, confirm: bool = False) -> str:
        """Render poster camera video, mux narration, and burn subtitles (requires confirm=True).

        Args:
            job_name: Job name.
            version: Optional version name.
            confirm: Must be True to render video files.

        Returns:
            Render summary or confirmation prompt.
        """
        denied = _require_confirm(confirm, f"渲染 {job_name} 海報影片")
        return denied or video_mod.render_poster_video(job_name, version)

    @mcp.tool()
    def mcp_render_html_video(job_name: str, version: str | None = None, confirm: bool = False) -> str:
        """Render HTML/GSAP/HyperFrames video, mux narration, and burn subtitles (requires confirm=True).

        Args:
            job_name: Job name.
            version: Optional version name.
            confirm: Must be True to render HTML video files.

        Returns:
            Render summary or confirmation prompt.
        """
        denied = _require_confirm(confirm, f"使用 HyperFrames 渲染 {job_name} HTML 影片")
        return denied or video_mod.render_html_video(job_name, version)

    @mcp.tool()
    def mcp_extract_audio(video: str, out: str | None = None, confirm: bool = False) -> str:
        """Extract 48kHz mono WAV from a video file (requires confirm=True).

        Args:
            video: Source video path.
            out: Optional output WAV path.
            confirm: Must be True to write audio file.

        Returns:
            Output path message or confirmation prompt.
        """
        denied = _require_confirm(confirm, f"從 {video} 提取音訊")
        if denied:
            return denied
        return f"完成：{extract_mod.extract_audio(video=video, out=out)}"


def _register_studio_read_tools(mcp: MCPServer) -> None:
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


def _register_studio_script_tools(mcp: MCPServer) -> None:
    """Register mutating AI script drafting and bilingual subtitle MCP tools.

    Args:
        mcp: Target MCPServer instance.
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
        denied = _require_confirm(confirm, f"為 {job_name} 起草講稿至 needs_review/")
        if denied:
            return denied
        path, _ = script_drafter.draft_script_to_review(
            job_name=job_name, instruction=instruction, language=language
        )
        return f"已生成講稿草稿：{path}"

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
        denied = _require_confirm(confirm, f"為 {job_name} 翻譯雙語字幕 ({target_lang})")
        if denied:
            return denied
        tsv_path, count = bilingual.translate_job_script_bilingual(job_name, target_lang, model)
        return f"已完成 {count} 句雙語字幕翻譯：{tsv_path}"


def _register_studio_plan_tools(mcp: MCPServer) -> None:
    """Register mutating agy CLI planning and review snapshot restore MCP tools.

    Args:
        mcp: Target MCPServer instance.
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
        denied = _require_confirm(confirm, f"啟動 {job_name} 的 agy {mode} 規劃任務")
        if denied:
            return denied
        return json.dumps(planner.start_agy_plan(job_name, instruction, mode), ensure_ascii=False)

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
        denied = _require_confirm(confirm, f"將 {job_name} 草稿退回至快照 {snap_id}")
        if denied:
            return denied
        return json.dumps(review_history.restore_snapshot(job_name, snap_id), ensure_ascii=False)


def _register_studio_media_tools(mcp: MCPServer) -> None:
    """Register mutating Avatar and external video mux MCP tools.

    Args:
        mcp: Target MCPServer instance.
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
        denied = _require_confirm(confirm, f"為 {job_name} 合成 {engine} Avatar 畫面")
        if denied:
            return denied
        res = avatar_overlay.apply_avatar_to_job(job_name=job_name, engine=engine, position=position)
        return f"已完成 {res.engine} Avatar 合成：{res.composited_video}"

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
        denied = _require_confirm(confirm, f"將外部影片 {video_path} 與 {job_name} 配音合成")
        return denied or video_mod.mux_external_video(job_name, video_path, version)


def build_mcp_server(config: AppConfig | None = None) -> MCPServer:
    """Create and configure the video-studio MCPServer instance.

    Args:
        config: Optional AppConfig override.

    Returns:
        Configured MCPServer with all video-studio tools registered.
    """
    _ = config or load_config()
    mcp = MCPServer("video-studio")
    _register_job_read_tools(mcp)
    _register_job_write_tools(mcp)
    _register_narrate_read_tools(mcp)
    _register_narrate_write_tools(mcp)
    _register_video_read_tools(mcp)
    _register_video_write_tools(mcp)
    _register_studio_read_tools(mcp)
    _register_studio_script_tools(mcp)
    _register_studio_plan_tools(mcp)
    _register_studio_media_tools(mcp)
    return mcp


def main() -> None:
    """Run the video-studio MCP server over stdio."""
    cfg = load_config()
    setup_logging(cfg.log_level, cfg.logs_dir if cfg.log_to_file else None)
    logger.info("Starting video-studio MCP stdio server")
    build_mcp_server(cfg).run(transport="stdio")


if __name__ == "__main__":
    main()
