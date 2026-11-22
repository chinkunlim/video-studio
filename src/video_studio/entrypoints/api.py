"""FastAPI HTTP API, Streamable HTTP MCP, and lightweight Web UI entrypoint."""

from __future__ import annotations

import logging
import re
import socket
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from video_studio.config.logging_setup import setup_logging
from video_studio.config.settings import AppConfig, load_config
from video_studio.entrypoints import studio_routes
from video_studio.entrypoints.mcp_server import build_mcp_server
from video_studio.entrypoints.schemas import (
    ApproveFileRequest,
    DraftScenesRequest,
    ExtractAudioRequest,
    HealthResponse,
    InitJobRequest,
    MuxVideoRequest,
    TextOutputResponse,
    VersionRequest,
    VocabSetRequest,
)
from video_studio.services.common import job as J
from video_studio.services.extract_audio import extract as extract_mod
from video_studio.services.narrate import narrate as narrate_mod
from video_studio.services.narrate.core import vocab
from video_studio.services.sv import approve_file, check_job_status, init_job, list_jobs
from video_studio.services.video import release as release_mod
from video_studio.services.video import video as video_mod

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"


_RENDER_GUARD_LOCK = threading.Lock()
_RENDER_LOCKS: dict[str, threading.Lock] = {}


def _run_with_render_lock(job_name: str, fn: Callable[[], str]) -> TextOutputResponse:
    """Execute a video render callable under a non-blocking per-job lock.

    Args:
        job_name: Target job name.
        fn: Zero-argument render callable returning summary output.

    Returns:
        TextOutputResponse from the render callable.

    Raises:
        HTTPException: 409 Conflict if the same job is already rendering.
    """
    with _RENDER_GUARD_LOCK:
        lock = _RENDER_LOCKS.setdefault(job_name, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=f"工作 {job_name} 正在渲染影片中，請勿重複觸發")
    try:
        return TextOutputResponse(output=fn())
    finally:
        lock.release()


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles subclass that disables browser 304 caching."""

    async def get_response(self, path: str, scope: Any) -> Response:
        """Serve static response with no-store cache headers.

        Args:
            path: Requested relative file path.
            scope: ASGI request scope.

        Returns:
            HTTP response with Cache-Control: no-store.
        """
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-store"
        return resp


def port_is_free(host: str, port: int) -> bool:
    """Check whether a local TCP host/port pair is available for binding.

    Args:
        host: Local bind address (e.g. 127.0.0.1).
        port: TCP port number.

    Returns:
        True if the port is free, False if already in use.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((host, port)) != 0


def _is_allowed_host(host: str, allowed_hosts: set[str], suffixes: tuple[str, ...]) -> bool:
    """Return whether an incoming HTTP Host header is permitted.

    Args:
        host: Normalized lowercase hostname without port.
        allowed_hosts: Exact permitted hostnames.
        suffixes: Permitted domain suffixes (e.g. `.ts.net`).

    Returns:
        True when empty, exact-matched, or suffix-matched.
    """
    if not host or host in allowed_hosts:
        return True
    return any(host.endswith(suffix) for suffix in suffixes)


def _is_allowed_origin(origin: str, allowed_origins: set[str], suffixes: tuple[str, ...]) -> bool:
    """Return whether an HTTP Origin header is permitted for mutating requests.

    Args:
        origin: Raw Origin header string.
        allowed_origins: Exact permitted origins.
        suffixes: Permitted host suffixes (e.g. `.ts.net`).

    Returns:
        True when empty, exact-matched, or matching an allowed host suffix.
    """
    if not origin:
        return True
    norm = origin.rstrip("/")
    if norm in allowed_origins:
        return True
    origin_host = norm.split("://", 1)[-1].split("/", 1)[0].split(":")[0].lower()
    return any(origin_host.endswith(suffix) for suffix in suffixes)


def _build_cors_origin_regex(suffixes: tuple[str, ...]) -> str | None:
    """Build a CORS origin regex matching HTTP(S) origins under allowed host suffixes.

    Args:
        suffixes: Normalized domain suffixes starting with `.`.

    Returns:
        Compiled regex pattern string for CORSMiddleware, or None when disabled.
    """
    if not suffixes:
        return None
    joined = "|".join(re.escape(suffix) for suffix in suffixes)
    return rf"^https?://[^/]+(?:{joined})(?::\d+)?$"


def _install_security_middleware(app: FastAPI, cfg: AppConfig) -> None:
    """Register Host/Origin validation and CORS middleware for local-only access.

    Args:
        app: FastAPI application instance.
        cfg: Application configuration.
    """
    suffixes = cfg.http_allowed_host_suffixes
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cfg.http_allowed_origins),
        allow_origin_regex=_build_cors_origin_regex(suffixes),
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    allowed_hosts = {cfg.http_host, "127.0.0.1", "localhost", "testserver"}
    allowed_origins = set(cfg.http_allowed_origins)

    @app.middleware("http")
    async def guard_host_and_origin(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Reject non-local Host headers and disallowed cross-origin mutations.

        Args:
            request: Incoming HTTP request.
            call_next: Next ASGI handler.

        Returns:
            HTTP response or 403 error JSON.
        """
        host_header = (request.headers.get("host") or "").split(":")[0].lower()
        if not _is_allowed_host(host_header, allowed_hosts, suffixes):
            return JSONResponse({"detail": "Forbidden host"}, status_code=403)
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("origin") or ""
            if not _is_allowed_origin(origin, allowed_origins, suffixes):
                return JSONResponse({"detail": "Forbidden origin"}, status_code=403)
        return await call_next(request)


def _register_job_routes(app: FastAPI, cfg: AppConfig) -> None:
    """Register health and job workspace HTTP routes.

    Args:
        app: FastAPI application instance.
        cfg: Application configuration.
    """

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        """Check API health and active workspace directory."""
        return HealthResponse(status="ok", app_env=cfg.app_env, workspace=str(J.workspace()))

    @app.get("/api/jobs", response_model=TextOutputResponse, tags=["jobs"])
    def api_list_jobs() -> TextOutputResponse:
        """List all jobs in the workspace."""
        return TextOutputResponse(output=list_jobs())

    @app.post("/api/jobs", response_model=TextOutputResponse, tags=["jobs"])
    def api_init_job(req: InitJobRequest) -> TextOutputResponse:
        """Create a new extract, dub, or generate job workspace.

        Args:
            req: Job creation payload.

        Returns:
            Creation result text.
        """
        try:
            return TextOutputResponse(output=init_job(req.job_type, req.name, req.title))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_name}/check", response_model=TextOutputResponse, tags=["jobs"])
    def api_check_job(job_name: str) -> TextOutputResponse:
        """Validate a job's configuration and input files.

        Args:
            job_name: Target job name.

        Returns:
            Validation status and report text.
        """
        try:
            ok, report = check_job_status(job_name)
            return TextOutputResponse(ok=ok, output=report)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


def _register_job_write_routes(app: FastAPI) -> None:
    """Register job file approval route.

    Args:
        app: FastAPI application instance.
    """

    @app.post("/api/jobs/{job_name}/approve", response_model=TextOutputResponse, tags=["jobs"])
    def api_approve_file(job_name: str, req: ApproveFileRequest) -> TextOutputResponse:
        """Approve and move a draft file from review/ to input/.

        Args:
            job_name: Target job name.
            req: File approval payload.

        Returns:
            Approval result text.
        """
        try:
            return TextOutputResponse(output=approve_file(job_name, req.filename))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def _register_narrate_routes(app: FastAPI) -> None:
    """Register vocabulary and narration HTTP routes.

    Args:
        app: FastAPI application instance.
    """

    @app.get("/api/vocab", response_model=TextOutputResponse, tags=["narrate"])
    def api_list_vocab() -> TextOutputResponse:
        """List all pronunciation entries in shared vocabulary.tsv."""
        voc = vocab.load(J.vocabulary_path())
        lines = [f"{{{{{k}}}}}\t{v.get('subtitle', '')}\t{v.get('tts', '')}" for k, v in voc.items()]
        return TextOutputResponse(output="\n".join(lines))

    @app.post("/api/vocab", response_model=TextOutputResponse, tags=["narrate"])
    def api_set_vocab(req: VocabSetRequest) -> TextOutputResponse:
        """Add or update a vocabulary entry.

        Args:
            req: Vocabulary entry payload.

        Returns:
            Update confirmation text.
        """
        voc_path = J.vocabulary_path()
        voc = vocab.load(voc_path)
        row = voc.get(req.key) or {k: "" for k in vocab.FIELDS}
        row["key"] = req.key
        row["subtitle"] = req.subtitle or row.get("subtitle", "")
        row["tts"] = req.tts or row.get("tts") or row["subtitle"] or req.key
        row["type"] = req.word_type or row.get("type", "")
        row["note"] = req.note or row.get("note", "")
        row["tts_lang"] = row.get("tts_lang") or "zh"
        voc[req.key] = row
        vocab.save(voc_path, voc)
        return TextOutputResponse(
            output=f"已更新詞彙表：{{{{{req.key}}}}} -> {row['subtitle']} ({row['tts']})"
        )

    @app.get("/api/jobs/{job_name}/lines", response_model=TextOutputResponse, tags=["narrate"])
    def api_list_lines(job_name: str) -> TextOutputResponse:
        """List parsed script lines for a job.

        Args:
            job_name: Target job name.

        Returns:
            Formatted script line listing.
        """
        return TextOutputResponse(output=narrate_mod.list_lines(J.find(job_name)))

    @app.post("/api/jobs/{job_name}/narrate/build", response_model=TextOutputResponse, tags=["narrate"])
    def api_build_narration(job_name: str) -> TextOutputResponse:
        """Build narration WAV and subtitles for a job.

        Args:
            job_name: Target job name.

        Returns:
            Build summary text.
        """
        try:
            return TextOutputResponse(output=narrate_mod.build_narration(J.find(job_name)))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def _register_video_read_routes(app: FastAPI) -> None:
    """Register read-only video timing and check HTTP routes.

    Args:
        app: FastAPI application instance.
    """

    @app.get("/api/jobs/{job_name}/video/timing", response_model=TextOutputResponse, tags=["video"])
    def api_video_timing(job_name: str, version: str | None = None) -> TextOutputResponse:
        """Calculate per-slide timing from narration output.

        Args:
            job_name: Target job name.
            version: Optional version name.

        Returns:
            Timing summary text.
        """
        return TextOutputResponse(output=video_mod.calc_timing(job_name, version))

    @app.get("/api/jobs/{job_name}/video/check", response_model=TextOutputResponse, tags=["video"])
    def api_video_check(job_name: str, version: str | None = None) -> TextOutputResponse:
        """Check rendered video streams, loudness, and contact sheet.

        Args:
            job_name: Target job name.
            version: Optional version name.

        Returns:
            Verification report text.
        """
        return TextOutputResponse(output=video_mod.check_video(job_name, version))


def _register_publish_route(app: FastAPI) -> None:
    """Register the video release publish HTTP route.

    Args:
        app: FastAPI application instance.
    """

    @app.post("/api/jobs/{job_name}/video/publish", response_model=TextOutputResponse, tags=["video"])
    def api_publish_release(job_name: str, req: VersionRequest) -> TextOutputResponse:
        """Publish a rendered version into output/<job>/releases/<vN>/ (demotes previous release).

        Args:
            job_name: Target job name.
            req: Optional version request.

        Returns:
            Release summary message.
        """
        try:
            res = release_mod.publish_release(job_name, req.version)
            return TextOutputResponse(output=str(res["message"]))
        except (J.JobError, FileNotFoundError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def _register_video_routes(app: FastAPI) -> None:
    """Register mutating video and audio extraction HTTP routes.

    Args:
        app: FastAPI application instance.
    """
    _register_video_read_routes(app)
    _register_publish_route(app)

    @app.post("/api/jobs/{job_name}/video/scenes", response_model=TextOutputResponse, tags=["video"])
    def api_draft_scenes(job_name: str, req: DraftScenesRequest) -> TextOutputResponse:
        """Draft scenes.toml and preview image into review/.

        Args:
            job_name: Target job name.
            req: Scene drafting options.

        Returns:
            Draft summary text.
        """
        return TextOutputResponse(output=video_mod.draft_scenes(job_name, source=req.source, force=req.force))

    @app.post("/api/jobs/{job_name}/video/poster", response_model=TextOutputResponse, tags=["video"])
    def api_render_poster(job_name: str, req: VersionRequest) -> TextOutputResponse:
        """Render poster camera video, mux narration, and burn subtitles.

        Args:
            job_name: Target job name.
            req: Optional version selector.

        Returns:
            Render summary text.
        """
        return _run_with_render_lock(job_name, lambda: video_mod.render_poster_video(job_name, req.version))

    @app.post("/api/jobs/{job_name}/video/html", response_model=TextOutputResponse, tags=["video"])
    def api_render_html(job_name: str, req: VersionRequest) -> TextOutputResponse:
        """Render HTML/GSAP/HyperFrames video, mux narration, and burn subtitles.

        Args:
            job_name: Target job name.
            req: Optional version selector.

        Returns:
            Render summary text.
        """
        return _run_with_render_lock(job_name, lambda: video_mod.render_html_video(job_name, req.version))

    @app.post("/api/jobs/{job_name}/video/mux", response_model=TextOutputResponse, tags=["video"])
    def api_mux_video(job_name: str, req: MuxVideoRequest) -> TextOutputResponse:
        """Mux an external video with narration and burn subtitles.

        Args:
            job_name: Target job name.
            req: Muxing parameters.

        Returns:
            Muxing summary text.
        """
        return TextOutputResponse(
            output=video_mod.mux_external_video(job_name, req.video_file, req.version, req.reserve_bottom)
        )

    @app.post("/api/extract", response_model=TextOutputResponse, tags=["extract"])
    def api_extract_audio(req: ExtractAudioRequest) -> TextOutputResponse:
        """Extract 48kHz mono WAV audio from a video file.

        Args:
            req: Extraction parameters.

        Returns:
            Output WAV path message.
        """
        opts = extract_mod.ExtractOptions(rate=req.rate, samples_dir=req.samples_dir)
        out_p = extract_mod.extract_audio(video=req.video, out=req.out, options=opts)
        return TextOutputResponse(output=f"完成：{out_p}")


def create_app(config: AppConfig | None = None) -> FastAPI:
    """Construct and configure the FastAPI application (factory pattern).

    Args:
        config: Optional AppConfig override (defaults to load_config()).

    Returns:
        Configured FastAPI instance with HTTP routes, /mcp, and static Web UI.
    """
    cfg = config or load_config()
    mcp_server = build_mcp_server(cfg)
    mcp_app = mcp_server.streamable_http_app(streamable_http_path="/")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Manage MCP Streamable HTTP session lifecycle.

        Args:
            _: FastAPI application instance.

        Yields:
            Control while the MCP session manager is active.
        """
        async with mcp_server.session_manager.run():
            yield

    app = FastAPI(
        title="video-studio API",
        version="0.1.0",
        description="Local AI narration, subtitle, and video synthesis HTTP + MCP server.",
        lifespan=lifespan,
    )
    _install_security_middleware(app, cfg)
    _register_job_routes(app, cfg)
    _register_job_write_routes(app)
    _register_narrate_routes(app)
    _register_video_routes(app)
    app.include_router(studio_routes.router)
    app.mount("/mcp", mcp_app)
    if STATIC_DIR.is_dir():
        app.mount("/", NoCacheStaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    return app


def main() -> None:
    """Start the local FastAPI + MCP server on 127.0.0.1."""
    cfg = load_config()
    setup_logging(cfg.log_level, cfg.logs_dir if cfg.log_to_file else None)
    if not port_is_free(cfg.http_host, cfg.http_port):
        raise SystemExit(f"Port {cfg.http_host}:{cfg.http_port} is already in use.")
    logger.info("Starting video-studio API at http://%s:%d", cfg.http_host, cfg.http_port)
    uvicorn.run(create_app(cfg), host=cfg.http_host, port=cfg.http_port)


if __name__ == "__main__":
    main()
