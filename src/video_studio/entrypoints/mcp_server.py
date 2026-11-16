"""MCP server entrypoint for video-studio (Stdio and Streamable HTTP).

Exposes read-only and confirm-gated mutating tools backed by the shared
`services` layer. Never prints to stdout so stdio JSON-RPC stays clean.
"""

from __future__ import annotations

import logging

from mcp.server.mcpserver import MCPServer

from video_studio.config.logging_setup import setup_logging
from video_studio.config.settings import AppConfig, load_config
from video_studio.services.common import job as J
from video_studio.services.extract_audio import extract as extract_mod
from video_studio.services.narrate import narrate as narrate_mod
from video_studio.services.narrate.core import vocab
from video_studio.services.sv import approve_file, check_job_status, init_job, list_jobs
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


def _register_video_write_tools(mcp: MCPServer) -> None:
    """Register mutating video rendering and audio extraction MCP tools.

    Args:
        mcp: Target MCPServer instance.
    """

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
    return mcp


def main() -> None:
    """Run the video-studio MCP server over stdio."""
    cfg = load_config()
    setup_logging(cfg.log_level, cfg.logs_dir if cfg.log_to_file else None)
    logger.info("Starting video-studio MCP stdio server")
    build_mcp_server(cfg).run(transport="stdio")


if __name__ == "__main__":
    main()
