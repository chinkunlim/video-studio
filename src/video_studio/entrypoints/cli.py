"""Command-line entrypoint for video-studio.

Wires all service modules (job management, audio extraction,
narration synthesis, and video assembly) into unified command-line actions.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from video_studio.config.logging_setup import setup_logging
from video_studio.config.settings import load_config
from video_studio.services.common import job as J
from video_studio.services.extract_audio import extract as extract_mod
from video_studio.services.narrate import narrate as narrate_mod
from video_studio.services.narrate.core import script, vocab
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
        options=extract_mod.ExtractOptions(
            rate=args.rate,
            start=args.start,
            end=args.end,
            samples_dir=args.samples,
        ),
    )
    print(f"完成：{out_p}")
    return 0


def _handle_narrate_vocab(args: argparse.Namespace) -> int:
    """Handle narrate vocab list/set subcommands.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code (0 on success, 1 on validation error).
    """
    voc_path = J.vocabulary_path()
    voc = vocab.load(voc_path)
    if args.action == "list":
        for k, v in voc.items():
            tested_str = f"试听 {v.get('tested', '')}" if v.get("tested") else "未试听"
            print(
                f"{{{{{k}}}}}\t{v.get('type', '')}\t字幕「{v.get('subtitle', '')}」\t"
                f"念「{v.get('tts', '')}」\t{tested_str}\t{v.get('note', '')}"
            )
        return 0
    if not args.key:
        print("请提供词汇 key")
        return 1
    row = voc.get(args.key) or {k: "" for k in vocab.FIELDS}
    row["key"] = args.key
    for f in ("type", "subtitle", "tts", "tested", "note"):
        val = getattr(args, f, None)
        if val:
            row[f] = val
    row["tts"] = row.get("tts") or row.get("subtitle") or args.key
    row["tts_lang"] = row.get("tts_lang") or "zh"
    voc[args.key] = row
    vocab.save(voc_path, voc)
    print(f"已更新词汇表：{{{{{args.key}}}}} -> {row.get('subtitle', '')} ({row.get('tts', '')})")
    return 0


def _handle_narrate(args: argparse.Namespace) -> int:
    """Handle narration subcommand.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code (0 on success).
    """
    cmd = args.narrate_cmd
    if cmd == "format":
        content = Path(args.file).read_text(encoding="utf-8")
        print(script.split_sentences(content))
        return 0
    if cmd == "vocab":
        return _handle_narrate_vocab(args)
    if cmd not in ("lines", "scan", "build", "audition", "pick"):
        return 0
    job = J.find(args.job)
    actions = {
        "lines": lambda: narrate_mod.list_lines(job),
        "scan": lambda: narrate_mod.scan_vocab(job),
        "build": lambda: narrate_mod.build_narration(job),
        "audition": lambda: narrate_mod.audition_line(job, args.line, args.takes),
        "pick": lambda: narrate_mod.pick_take(job, args.line, args.take),
    }
    print(actions[cmd]())
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
    if cmd == "mux":
        print(video_mod.mux_external_video(args.job, args.video, args.version, args.reserve_bottom))
        return 0
    if cmd == "check":
        print(video_mod.check_video(args.job, args.version))
        return 0
    return 0


def _add_job_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register job subcommand parser.

    Args:
        sub: Root subparsers action.
    """
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


def _add_extract_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register extract subcommand parser.

    Args:
        sub: Root subparsers action.
    """
    p_ext = sub.add_parser("extract", help="音讯提取")
    p_ext.add_argument("video")
    p_ext.add_argument("--out")
    p_ext.add_argument("--rate", type=int, default=48000)
    p_ext.add_argument("--start")
    p_ext.add_argument("--end")
    p_ext.add_argument("--samples")


def _add_narrate_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register narrate subcommand parser.

    Args:
        sub: Root subparsers action.
    """
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
    sp_fmt = nar_sub.add_parser("format", help="整理讲稿格式")
    sp_fmt.add_argument("file")
    sp_voc = nar_sub.add_parser("vocab", help="词汇表管理")
    sp_voc.add_argument("action", choices=["list", "set"])
    sp_voc.add_argument("key", nargs="?")
    sp_voc.add_argument("--subtitle", default="")
    sp_voc.add_argument("--tts", default="")
    sp_voc.add_argument("--type", dest="type", default="")
    sp_voc.add_argument("--tested", default="")
    sp_voc.add_argument("--note", default="")


def _add_video_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register video subcommand parser.

    Args:
        sub: Root subparsers action.
    """
    p_vid = sub.add_parser("video", help="影片合成")
    vid_sub = p_vid.add_subparsers(dest="video_cmd", required=True)
    for name in ("timing", "poster", "check"):
        sp = vid_sub.add_parser(name)
        sp.add_argument("job")
        sp.add_argument("--version")
    sp_sc = vid_sub.add_parser("scenes")
    sp_sc.add_argument("job")
    sp_sc.add_argument("--source", default="auto")
    sp_sc.add_argument("--force", action="store_true")
    sp_mux = vid_sub.add_parser("mux")
    sp_mux.add_argument("job")
    sp_mux.add_argument("--video", required=True)
    sp_mux.add_argument("--reserve-bottom", type=int, default=0)
    sp_mux.add_argument("--version")


def build_parser() -> argparse.ArgumentParser:
    """Construct command-line argument parser with subcommands.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(description="video-studio command-line interface")
    sub = parser.add_subparsers(dest="subcommand")
    _add_job_parser(sub)
    _add_extract_parser(sub)
    _add_narrate_parser(sub)
    _add_video_parser(sub)
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
