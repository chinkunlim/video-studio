"""Tests for AI script drafting, bilingual subtitles, and dual-engine Avatar presenter."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from video_studio.config.settings import AppConfig
from video_studio.entrypoints.api import create_app
from video_studio.services.common import job as J
from video_studio.services.narrate.core import bilingual, prosody, subtitles
from video_studio.services.video.engine.avatar_engine import (
    DEFAULT_PORTRAIT_BG_RGB,
    avatar_environment_status,
    ensure_opaque_portrait,
    overlay_avatar_pip,
    render_lightweight_avatar,
    render_sadtalker_avatar,
)


class TestAvatarScriptBilingual(unittest.TestCase):
    """Verify AI script drafting, bilingual subtitles, and Route A/B Avatar helpers."""

    def setUp(self) -> None:
        """Create isolated workspace and TestClient."""
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name).resolve()
        self.ws = self.data_dir / "workspace"
        self.ws.mkdir(parents=True, exist_ok=True)
        self.env_patch = patch.dict(os.environ, {"SPLIT_VOICE_WORKSPACE": str(self.ws)})
        self.env_patch.start()
        self.cfg = AppConfig(app_env="test", log_to_file=False, data_dir=self.data_dir, workspace_dir=self.ws)
        self.client = TestClient(create_app(self.cfg))
        self.client.post(
            "/api/jobs", json={"job_type": "generate", "name": "einstein-demo", "title": "愛因斯坦相對論"}
        )

    def tearDown(self) -> None:
        """Restore environment and clean up temp directory."""
        self.env_patch.stop()
        self.tmp.cleanup()

    def test_script_draft_to_review_and_load(self) -> None:
        """Verify POST /script/draft writes formatted script to review/script.md without overwriting input."""
        with patch(
            "video_studio.services.script_drafter.run_agy_prompt",
            return_value=(
                "# 講稿：相對論\n\n## 投影片 1\n大家好，我是愛因斯坦。今天我們來聊聊時間為什麼會變慢。"
            ),
        ):
            res = self.client.post(
                "/api/jobs/einstein-demo/script/draft",
                json={"instruction": "用愛因斯坦口吻介紹相對論", "language": "zh", "duration_sec": 60},
            )
        self.assertEqual(res.status_code, 200)
        self.assertIn("大家好，我是愛因斯坦", res.json()["content"])
        rev = self.client.get("/api/jobs/einstein-demo/review-script")
        self.assertTrue(rev.json()["exists"])
        self.assertIn("相對論", rev.json()["content"])

        # Edit input/script.md and verify original draft remains untouched
        self.client.put(
            "/api/jobs/einstein-demo/script",
            json={"content": "# 講稿：相對論\n\n## 投影片 1\n修改後的講稿。", "auto_format": False},
        )
        orig = self.client.get("/api/jobs/einstein-demo/original-script")
        self.assertTrue(orig.json()["exists"])
        self.assertIn("大家好，我是愛因斯坦", orig.json()["content"])
        self.assertNotIn("修改後的講稿", orig.json()["content"])

    def test_agy_models_and_prosody_static_asset(self) -> None:
        """Verify /api/agy/models, plan model forwarding, and studio-prosody.js asset."""
        with patch(
            "video_studio.services.planner.list_agy_models",
            return_value=[{"id": "gemini-4-argon-high", "label": "Gemini 4 Argon (High)"}],
        ):
            res = self.client.get("/api/agy/models")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["models"][0]["id"], "gemini-4-argon-high")

        with patch("video_studio.services.planner.start_agy_plan", return_value={"ok": True}) as mock_plan:
            self.client.post(
                "/api/jobs/einstein-demo/plan",
                json={"instruction": "test", "mode": "html", "model": "gemini-4-argon-high"},
            )
            mock_plan.assert_called_once_with(
                "einstein-demo",
                "test",
                "html",
                "gemini-4-argon-high",
                True,
                thread_mode="continue",
                history=[],
            )

        # Verify build_plan_prompt preserves poster design and adds English translation rule when voice=en
        from video_studio.services.planner import build_plan_prompt

        job = J.find("einstein-demo")
        (job.input / "poster.pptx").write_bytes(b"PK")
        self.client.put(
            "/api/jobs/einstein-demo/config",
            json={"title": "愛因斯坦相對論", "voice_language": "en", "visual_mode": "html"},
        )
        prompt = build_plan_prompt("einstein-demo", "", "html", follow_poster_design=True)
        self.assertIn("沿用海報設計", prompt)
        self.assertIn("跨語系海報翻譯", prompt)

        from video_studio.services.planner import parse_agy_stream_line

        init_ev = parse_agy_stream_line('{"event":"init","init":{"model":"gemini-4-argon-high"}}')
        self.assertEqual(init_ev, {"kind": "init", "model": "gemini-4-argon-high"})
        res_ev = parse_agy_stream_line(
            '{"event":"result","result":{"status":"SUCCESS","response":"Done","duration_seconds":3.5}}'
        )
        self.assertEqual(res_ev["kind"], "result")
        self.assertEqual(res_ev["response"], "Done")

        js = self.client.get("/studio-prosody.js")
        self.assertEqual(js.status_code, 200)
        self.assertIn("wrapScriptProsody", js.text)

    def test_bilingual_translation_and_subtitle_output(self) -> None:
        """Verify bilingual TSV parsing and dual-line SRT/VTT/ASS generation."""
        lines = ["Hello everyone, welcome to relativity.", "Time slows down near gravity."]
        raw = "[1] 大家好，歡迎來到相對論。\n[2] 時間在重力附近會變慢。"
        rows = bilingual.parse_bilingual_output(raw, lines)
        self.assertEqual(rows[0][2], "大家好，歡迎來到相對論。")

        tsv = self.data_dir / "script_bilingual.tsv"
        bilingual.save_bilingual_tsv(tsv, rows)
        mapping = bilingual.load_bilingual_map(tsv)
        cues = subtitles.attach_bilingual([(0.0, 2.0, lines[0]), (2.1, 4.0, lines[1])], mapping)
        out_dir = self.data_dir / "subs"
        subtitles.write_all(cues, out_dir, {"subtitle": {"opencc": "none"}}, "Relativity")
        srt = (out_dir / "subtitles_youtube.srt").read_text(encoding="utf-8")
        ass = (out_dir / "subtitles_vlc.ass").read_text(encoding="utf-8")
        self.assertIn("Hello everyone, welcome to relativity.\n大家好，歡迎來到相對論。", srt)
        self.assertIn(r"Hello everyone, welcome to relativity.\N大家好，歡迎來到相對論。", ass)

    def test_avatar_status_and_route_b_lightweight_pipeline(self) -> None:
        """Verify /api/avatar/status and Route B FFmpeg lightweight avatar + PiP overlay."""
        status = self.client.get("/api/avatar/status")
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.json()["lightweight"]["ready"])

        sad_status = avatar_environment_status(self.data_dir / "missing_sadtalker")
        self.assertFalse(sad_status["sadtalker"]["ready"])

        # Synthesize 1s portrait PNG, 1s silent WAV, and 1s base MP4 via ffmpeg
        job = J.find("einstein-demo")
        portrait = job.input / "einstein.png"
        audio = self.data_dir / "narration.wav"
        base_mp4 = self.data_dir / "base.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=256x256:d=1",
                "-frames:v",
                "1",
                str(portrait),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "1", str(audio)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=640x360:d=1",
                "-i",
                str(audio),
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-shortest",
                str(base_mp4),
            ],
            check=True,
            capture_output=True,
        )

        avatar_clip = self.data_dir / "avatar_lw.mp4"
        render_lightweight_avatar(portrait, audio, avatar_clip, fps=15)
        self.assertTrue(avatar_clip.is_file() and avatar_clip.stat().st_size > 0)

        pip_out = self.data_dir / "pip.mp4"
        overlay_avatar_pip(base_mp4, avatar_clip, pip_out, position="bottom-right")
        self.assertTrue(pip_out.is_file() and pip_out.stat().st_size > 0)

        # Verify 10s Avatar A/B preview endpoint using takes/ audio (mock Route A offline)
        job.takes_dir.mkdir(parents=True, exist_ok=True)
        (job.takes_dir / "sample.wav").write_bytes(audio.read_bytes())
        with patch(
            "video_studio.services.video.avatar_overlay.avatar_environment_status",
            return_value={"lightweight": {"ready": True}, "sadtalker": {"ready": False}},
        ):
            ab_res = self.client.post("/api/jobs/einstein-demo/video/avatar-preview", json={})
        self.assertEqual(ab_res.status_code, 200)
        self.assertEqual(ab_res.json()["route_b_file"], "avatar_preview_b.mp4")
        self.assertTrue((job.review / "avatar_preview_b.mp4").is_file())

    def test_word_level_and_sentence_prosody(self) -> None:
        """Verify inline word-level [loud]/[soft] and sentence [fast] tags + FFmpeg filter."""
        clean, spans = prosody.parse_prosody_tags("今天聊聊 [loud]相對論[/loud] 與 [soft]細節[/soft]。")
        self.assertEqual(clean, "今天聊聊 相對論 與 細節。")
        self.assertEqual([(s.tag, s.phrase) for s in spans], [("loud", "相對論"), ("soft", "細節")])

        words = [("今天聊聊", 0.0, 0.5), ("相對論", 0.5, 1.0), ("與", 1.0, 1.2), ("細節", 1.2, 1.6)]
        timed = prosody.match_word_spans(spans, words)
        self.assertEqual(timed, [("loud", 0.5, 1.0), ("soft", 1.2, 1.6)])

        src_wav = self.data_dir / "src.wav"
        dst_wav = self.data_dir / "dst.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(src_wav)],
            check=True,
            capture_output=True,
        )
        prosody.apply_prosody_to_wav(src_wav, dst_wav, timed, preset="energetic")
        self.assertTrue(dst_wav.is_file() and dst_wav.stat().st_size > 0)

    def test_active_plan_reconnect_endpoint(self) -> None:
        """Verify GET /api/jobs/{name}/plan/active returns active running agy plans for reconnect."""
        from video_studio.services import planner

        idle = self.client.get("/api/jobs/einstein-demo/plan/active")
        self.assertEqual(idle.status_code, 200)
        self.assertFalse(idle.json()["active"])

        run = planner.PlanRun(
            run_id="run-reconnect-1",
            job_name="einstein-demo",
            prompt="test prompt",
            model="gemini-3-flash",
            job_dir=self.data_dir,
            status="running",
            lines=["正在讀取簡報與時間軸…"],
        )
        with planner._LOCK:
            planner._RUNS[run.run_id] = run
        try:
            active = self.client.get("/api/jobs/einstein-demo/plan/active")
            self.assertEqual(active.status_code, 200)
            body = active.json()
            self.assertTrue(body["active"])
            self.assertEqual(body["run_id"], "run-reconnect-1")
            self.assertEqual(body["status"], "running")
            self.assertIn("正在讀取簡報與時間軸", body["output"])
        finally:
            with planner._LOCK:
                planner._RUNS.pop(run.run_id, None)

    def test_video_aspect_resolution_config_and_prompt(self) -> None:
        """Verify output width/height (e.g. 4:3 1440x1080) persists in job.toml and plan prompt."""
        from video_studio.services import planner

        res = self.client.put(
            "/api/jobs/einstein-demo/config",
            json={"title": "4:3 Demo", "width": 1440, "height": 1080, "fps": 30},
        )
        self.assertEqual(res.status_code, 200)
        detail = self.client.get("/api/jobs/einstein-demo/detail")
        self.assertEqual(detail.status_code, 200)
        out_cfg = detail.json()["config"]["output"]
        self.assertEqual(out_cfg["width"], 1440)
        self.assertEqual(out_cfg["height"], 1080)
        prompt = planner.build_plan_prompt("einstein-demo")
        self.assertIn("1440x1080", prompt)

    def test_review_snapshot_and_rollback(self) -> None:
        """Verify review/ snapshot creation, listing, and rollback restore."""
        from video_studio.services.common import job as J

        job = J.find("einstein-demo")
        job.review.mkdir(parents=True, exist_ok=True)
        html_path = job.review / "index.html"
        html_path.write_text("<html><body>v1</body></html>", encoding="utf-8")

        snap_res = self.client.post("/api/jobs/einstein-demo/review/snapshots", json={"note": "v1 initial"})
        self.assertEqual(snap_res.status_code, 200)
        snap_id = snap_res.json()["snapshot"]["id"]

        # Overwrite review/index.html with v2 (simulating a bad agy edit)
        html_path.write_text("<html><body>v2 broken</body></html>", encoding="utf-8")
        restore_res = self.client.post(f"/api/jobs/einstein-demo/review/snapshots/{snap_id}/restore")
        self.assertEqual(restore_res.status_code, 200)
        self.assertEqual(html_path.read_text(encoding="utf-8"), "<html><body>v1</body></html>")

        # Pre-restore backup should also exist in list
        list_res = self.client.get("/api/jobs/einstein-demo/review/snapshots")
        self.assertEqual(list_res.status_code, 200)
        self.assertGreaterEqual(len(list_res.json()["snapshots"]), 2)

    def test_render_lock_prevents_duplicate_concurrent_renders(self) -> None:
        """Verify concurrent POST /video/html for the same job returns 409 Conflict."""
        import threading

        from video_studio.entrypoints import api as api_mod

        lock = api_mod._RENDER_LOCKS.setdefault("einstein-demo", threading.Lock())
        lock.acquire()
        try:
            res = self.client.post("/api/jobs/einstein-demo/video/html", json={})
            self.assertEqual(res.status_code, 409)
        finally:
            lock.release()

    def test_bilingual_overlay_line_break_and_lead_in_pause(self) -> None:
        """Verify bilingual overlay keeps EN/ZH on separate lines and lead_in shifts start."""
        from PIL import Image, ImageDraw

        from video_studio.services.narrate.core import audio, concat
        from video_studio.services.video.engine import media, overlay

        srt_path = self.data_dir / "bilingual.srt"
        srt_path.write_text("1\n00:00:02,000 --> 00:00:04,000\nHello world\n你好世界\n\n", encoding="utf-8")
        parsed = media.read_srt(srt_path)
        self.assertEqual(parsed[0][2], "Hello world\n你好世界")

        img = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        fnt = overlay.font("/System/Library/Fonts/STHeiti Light.ttc", 1, 28)
        lines = overlay._fit_lines(draw, parsed[0][2], fnt, 1720)
        self.assertEqual(lines, ["Hello world", "你好世界"])

        from video_studio.services.narrate.core import subtitles

        bmap = {
            "Here is the catch you never know how much money is inside.": (
                "陷阱在這裡，你永遠不知道裡面有多少錢"
            )
        }
        bilingual_cues = subtitles.attach_bilingual(
            [
                (2.0, 4.0, "Here is the catch"),
                (4.02, 6.5, "you never know how much money is inside."),
            ],
            bmap,
        )
        self.assertEqual(len(bilingual_cues), 2)
        self.assertEqual(bilingual_cues[0][1], 4.02)  # <80ms gap snapped to avoid flicker
        self.assertNotEqual(bilingual_cues[0][2].split("\n")[1], bilingual_cues[1][2].split("\n")[1])

        tone = self.data_dir / "tone.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(tone)],
            check=True,
            capture_output=True,
        )
        out_wav = self.data_dir / "lead_in_out.wav"
        tl = concat.build(
            [{"no": 1, "slide": 1, "clip": tone, "brk": "period"}],
            out_wav,
            concat.ConcatOptions(pause={"period": 0.5}, tmp=self.data_dir / "tmp_concat", lead_in=2.0),
        )
        self.assertGreaterEqual(tl[0]["start"], 1.95)
        self.assertGreaterEqual(audio.duration(out_wav), 2.8)

    def test_voice_samples_endpoint_and_plan_thread_modes(self) -> None:
        """Verify /api/voice/samples and planner thread_mode ('continue' vs 'new')."""
        from video_studio.services import planner

        res = self.client.get("/api/voice/samples?voice=en-US-GuyNeural")
        self.assertEqual(res.status_code, 200)
        self.assertIn("ready", res.json())

        hist = [{"role": "user", "text": "keep header clean"}]
        cont_prompt = planner.build_plan_prompt(
            "einstein-demo", "next edit", thread_mode="continue", history=hist
        )
        self.assertIn("前幾輪對話紀錄", cont_prompt)
        self.assertIn("keep header clean", cont_prompt)

        new_prompt = planner.build_plan_prompt("einstein-demo", "fresh edit", thread_mode="new", history=hist)
        self.assertNotIn("keep header clean", new_prompt)
        self.assertIn("已開啟新對話串", new_prompt)

    def test_opaque_portrait_and_sadtalker_env_flags(self) -> None:
        """Verify RGBA portraits get warm cream fill and SadTalker gets --still and PyTorch/MPS env."""
        rgb_img = self.data_dir / "rgb_avatar.png"
        Image.new("RGB", (64, 64), (10, 20, 30)).save(rgb_img)
        self.assertEqual(ensure_opaque_portrait(rgb_img, self.data_dir / "out_rgb"), rgb_img)

        rgba_img = self.data_dir / "rgba_avatar.png"
        im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        for x in range(16, 48):
            for y in range(16, 48):
                im.putpixel((x, y), (90, 60, 40, 255))
        im.save(rgba_img)

        work_dir = self.data_dir / "work_opaque"
        flattened = ensure_opaque_portrait(rgba_img, work_dir)
        self.assertEqual(flattened, work_dir / "rgba_avatar_opaque.png")
        with Image.open(flattened) as out_im:
            self.assertEqual(out_im.mode, "RGB")
            self.assertEqual(out_im.getpixel((0, 0)), DEFAULT_PORTRAIT_BG_RGB)

        sad_dir = self.data_dir / "fake_sadtalker"
        (sad_dir / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
        (sad_dir / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
        (sad_dir / "checkpoints").mkdir(parents=True, exist_ok=True)
        (sad_dir / "checkpoints" / "SadTalker_V0.0.2_512.safetensors").write_bytes(b"ckpt")

        audio = self.data_dir / "dummy.wav"
        audio.write_bytes(b"RIFF")
        out_mp4 = self.data_dir / "sad_out.mp4"
        captured: dict[str, object] = {}

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            captured["cmd"] = cmd
            captured["env"] = kwargs.get("env")
            res_idx = cmd.index("--result_dir") + 1
            res_dir = Path(cmd[res_idx])
            (res_dir / "result.mp4").write_bytes(b"mp4")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("video_studio.services.video.engine.avatar_engine.subprocess.run", side_effect=fake_run):
            res_path = render_sadtalker_avatar(rgba_img, audio, out_mp4, sad_dir)

        self.assertTrue(res_path.is_file())
        cmd_list = captured["cmd"]
        assert isinstance(cmd_list, list)
        self.assertIn("--still", cmd_list)
        src_arg = cmd_list[cmd_list.index("--source_image") + 1]
        self.assertTrue(src_arg.endswith("rgba_avatar_opaque.png"))
        env_dict = captured["env"]
        assert isinstance(env_dict, dict)
        self.assertEqual(env_dict.get("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"), "1")
        self.assertEqual(env_dict.get("PYTORCH_ENABLE_MPS_FALLBACK"), "1")

    def test_bilingual_clause_split_preserves_english_words(self) -> None:
        """Verify English secondary translation never splits mid-word (e.g. 17th-century)."""
        from video_studio.services.narrate.core.subtitles import _split_zh_clauses

        sentence = (
            "Yet both readings are almost the exact opposite of what 17th-century Descartes set out to solve."
        )
        parts = _split_zh_clauses(sentence, 3)
        self.assertEqual(len(parts), 3)
        joined = " ".join(parts)
        self.assertIn("17th-century", joined)
        self.assertNotIn("17th-cen ", joined)
