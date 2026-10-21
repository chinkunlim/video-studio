"""Command-line entrypoint for video-studio.

Wires all service modules (job management, audio extraction,
narration synthesis, and video assembly) into unified command-line actions.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence

from video_studio.config.logging_setup import setup_logging
from video_studio.config.settings import load_config
from video_studio.services.common import job as J
from video_studio.services.extract_audio import extract as extract_mod
from video_studio.services.narrate import narrate as narrate_mod
from video_studio.services.sv import approve_file, check_job_status, init_job, list_jobs
from video_studio.services.video import video as video_mod

logger = logging.getLogger(__name__)


def _handle_job(args: argparse.Namespace) -> int:
    """Handle job subcommand.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code (0 on success).
    """
    cmd = args.job_cmd
    if cmd == "list":
        print(list_jobs())
        return 0
    if cmd == "init":
        print(init_job(args.type, args.name, args.title))
        return 0
    if cmd == "check":
        ok, report = check_job_status(args.job)
        print(report)
        return 0 if ok else 1
    if cmd == "approve":
        print(approve_file(args.job, args.file))
        return 0
    return 1


def _handle_extract(args: argparse.Namespace) -> int:
    """Handle audio extraction subcommand.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code (0 on success).
    """
    out_p = extract_mod.extract_audio(
        video=args.video,
        out=args.out,
        rate=args.rate,
        start=args.start,
        end=args.end,
        samples_dir=args.samples,
    )
    print(f"完成：{out_p}")
    return 0


def _handle_narrate(args: argparse.Namespace) -> int:
    """Handle narration subcommand.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code (0 on success).
    """
    cmd = args.narrate_cmd
    if cmd in ("lines", "scan", "build", "audition", "pick"):
        job = J.find(args.job)
        if cmd == "lines":
            print(narrate_mod.list_lines(job))
            return 0
        if cmd == "scan":
            print(narrate_mod.scan_vocab(job))
            return 0
        if cmd == "build":
            print(narrate_mod.build_narration(job))
            return 0
        if cmd == "audition":
            print(narrate_mod.audition_line(job, args.line, args.takes))
            return 0
        if cmd == "pick":
            print(narrate_mod.pick_take(job, args.line, args.take))
            return 0
    return 0


def _handle_video(args: argparse.Namespace) -> int:
    """Handle video subcommand.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code (0 on success).
    """
    cmd = args.video_cmd
    if cmd == "timing":
        print(video_mod.calc_timing(args.job, args.version))
        return 0
    if cmd == "scenes":
        print(video_mod.draft_scenes(args.job, source=args.source, force=args.force))
        return 0
    if cmd == "poster":
        print(video_mod.render_poster_video(args.job, args.version))
        return 0
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct command-line argument parser with subcommands.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(description="video-studio command-line interface")
    sub = parser.add_subparsers(dest="subcommand")

    # job
    p_job = sub.add_parser("job", help="工作管理")
    job_sub = p_job.add_subparsers(dest="job_cmd", required=True)
    job_sub.add_parser("list")
    sp_init = job_sub.add_parser("init")
    sp_init.add_argument("type", choices=J.TYPES)
    sp_init.add_argument("name")
    sp_init.add_argument("--title", default="")
    sp_check = job_sub.add_parser("check")
    sp_check.add_argument("job")
    sp_app = job_sub.add_parser("approve")
    sp_app.add_argument("job")
    sp_app.add_argument("file")

    # extract
    p_ext = sub.add_parser("extract", help="音讯提取")
    p_ext.add_argument("video")
    p_ext.add_argument("--out")
    p_ext.add_argument("--rate", type=int, default=48000)
    p_ext.add_argument("--start")
    p_ext.add_argument("--end")
    p_ext.add_argument("--samples")

    # narrate
    p_nar = sub.add_parser("narrate", help="讲稿配音与字幕")
    nar_sub = p_nar.add_subparsers(dest="narrate_cmd", required=True)
    for name in ("lines", "scan", "build"):
        sp = nar_sub.add_parser(name)
        sp.add_argument("job")
    sp_aud = nar_sub.add_parser("audition")
    sp_aud.add_argument("job")
    sp_aud.add_argument("line", type=int)
    sp_aud.add_argument("--takes", type=int, default=4)
    sp_pick = nar_sub.add_parser("pick")
    sp_pick.add_argument("job")
    sp_pick.add_argument("line", type=int)
    sp_pick.add_argument("take", type=int)

    # video
    p_vid = sub.add_parser("video", help="影片合成")
    vid_sub = p_vid.add_subparsers(dest="video_cmd", required=True)
    sp_tim = vid_sub.add_parser("timing")
    sp_tim.add_argument("job")
    sp_tim.add_argument("--version")
    sp_sc = vid_sub.add_parser("scenes")
    sp_sc.add_argument("job")
    sp_sc.add_argument("--source", default="auto")
    sp_sc.add_argument("--force", action="store_true")
    sp_pos = vid_sub.add_parser("poster")
    sp_pos.add_argument("job")
    sp_pos.add_argument("--version")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, run services, and output result.

    Args:
        argv: Command-line arguments.

    Returns:
        Exit code (0 on success).
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config()
    setup_logging(config.log_level, config.logs_dir if config.log_to_file else None)
    if args.subcommand == "job":
        return _handle_job(args)
    if args.subcommand == "extract":
        return _handle_extract(args)
    if args.subcommand == "narrate":
        return _handle_narrate(args)
    if args.subcommand == "video":
        return _handle_video(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
