# SPEC-005: 雙 TTS 配音引擎與 HTML/GSAP/HyperFrames 畫面渲染

- **狀態**: Implemented
- **日期**: 2026-11-16
- **相關模組**: `services/narrate/core/edge_tts_client.py`, `services/video/engine/html_render.py`, `entrypoints/cli.py`, `entrypoints/api.py`, `entrypoints/mcp_server.py`, `adapters/openwebui_video_mixin.py`

## 1. 雙 TTS 引擎（Voicebox + edge-tts）

- `job.toml` `[voice]` 區塊支援：
  - `engine = "voicebox"`（預設）或 `"edge-tts"`
  - `edge_voice = "zh-TW-HsiaoChenNeural"`（可改為 `zh-TW-YunJheNeural`、`zh-TW-HsiaoYuNeural` 等）
- `EdgeTTSClient` 實作 `check_ready()` 與 `generate(text, language=None) -> bytes`，將 `edge-tts` 生成音訊透過 `ffmpeg` 轉為 24kHz 單聲道 `pcm_s16le` WAV，與 `Voicebox` 客戶端介面完全相容。

## 2. HTML / GSAP / HyperFrames 渲染模式（`html`）

- 透過 `pnpm add hyperframes gsap` 管理前端依賴，由 Python 透過 `pnpm exec hyperframes` 呼叫。
- `html_render.draft_html(job, slides, out_html)`：依 `script.md` 與 `timing.py` 算出的每頁秒數產生確定性 HTML（內嵌本機系統字型 `PingFang TC` / `Microsoft JhengHei`，載入本地 `node_modules/gsap` 並讀取 `timing.json`，禁用 `Math.random()` 與 `Date.now()`）。
- `video.render_html_video(job_name, version=None)`：
  1. 以 `video_context()` 計算「先聲後影」時間軸並寫出 `slide_timing.tsv` 與 `timing.json`。
  2. 若 `input/index.html` 不存在，提示或使用 `draft_html` 產出之核可頁面（AI 起草一律先放 `review/index.html`，經 `job approve` 移入 `input/index.html`）。
  3. 呼叫 `pnpm exec hyperframes render` 輸出 `work/video/picture.mp4`。
  4. 接回 `finish_video()` 合成配音、燒錄繁體字幕並產出 `video_contact_sheet.jpg` 驗收。
- CLI (`video html`)、FastAPI (`POST /api/jobs/{job_name}/video/html`)、MCP (`mcp_render_html_video`, 含 `confirm=False` 保護) 與 Open WebUI (`video_from_html`) 四個入口同步支援。
