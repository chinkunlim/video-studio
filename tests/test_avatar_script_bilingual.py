"""Tests for AI script drafting, bilingual subtitles, and dual-engine Avatar presenter."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from video_studio.config.settings import AppConfig
from video_studio.entrypoints.api import create_app
from video_studio.services.common import job as J
from video_studio.services.narrate.core import bilingual, prosody, subtitles
from video_studio.services.video.engine.avatar_engine import (
    avatar_environment_status,
    overlay_avatar_pip,
    render_lightweight_avatar,
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
            mock_plan.assert_called_once_with("einstein-demo", "test", "html", "gemini-4-argon-high", True)

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
