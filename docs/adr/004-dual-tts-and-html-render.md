# ADR-004: 雙 TTS 配音引擎（Voicebox + edge-tts）與三模畫面渲染（Poster / PPTX / HTML+GSAP+HyperFrames）

- **狀態**: Accepted
- **日期**: 2026-11-16
- **決策者**: chinkunlim, antigravity
- **相關程式**: `services/narrate/core/edge_tts_client.py`, `services/narrate/narrate.py`, `services/video/engine/html_render.py`, `services/video/video.py`

## 背景與問題

1. **配音彈性**：原有設計僅支援本機 Voicebox 聲音複製，雖然隱私性最高，但每次生成都必須先手動啟動 Voicebox App 並載入模型；若專案不需要個人聲紋（例如快速草稿或標準台灣腔旁白），缺少免啟動的替代方案。
2. **高畫質與高自由度畫面渲染**：原有設計僅支援「海報鏡頭移動（Pillow + FFmpeg）」與「PowerPoint AppleScript 匯出」。若使用 PowerPoint 設計的海報需要以 HTML + CSS + GSAP 重新建構以保持向量/文字銳利度與精細時間軸動畫，或 PowerPoint 匯出結果不符合影片需求，需要第三種渲染引擎。

## 決策

1. **雙 TTS 引擎**：
   - 保留 `voicebox`（`127.0.0.1:17493`）作為預設本機聲音複製引擎。
   - 透過 `uv add edge-tts` 引入 `edge-tts` 作為可選引擎（`[voice] engine = "edge-tts"`，預設台灣中文聲線 `zh-TW-HsiaoChenNeural`），產出統一轉為 24kHz 單聲道 WAV，沿用既有的 `takes.json` 指紋快取、Whisper 驗收、`concat.build` 與 OpenCC 繁體字幕管線。
2. **三模畫面渲染（納入 `html` 模式）**：
   - 在專案根目錄以 `pnpm`（`package.json` + `pnpm-lock.yaml`）鎖定安裝 `hyperframes` 與 `gsap`，禁止使用 `npm` 或 `npx`。
   - 新增 `services/video/engine/html_render.py`，將 `timing.py` 算出的「先聲後影」各頁秒數注入確定性 HTML/GSAP 時間軸，由 `pnpm exec hyperframes render` 輸出無聲畫面 `picture.mp4`，再接回 `finish_video()` 執行 `-map 0:v:0 -map 1:a:0` 合成、字幕燒錄與 `media.check` 驗收。

## 權衡與影響

- **隱私界線**：`edge-tts` 僅於使用者明確選擇時傳送講稿文字至微軟 TTS 端點，**絕不**上傳任何個人語音樣本；需要聲音克隆或完全離線時仍一律走 `voicebox`。
- **可重現性**：所有 HTML 分鏡禁止使用 `Math.random()`、`Date.now()` 與外部 Google Fonts，確保跨次渲染每一格完全一致。
