# ADR-003：影片合成渲染引擎之雙模式設計（PowerPoint 動畫與海報鏡頭動畫）

- **狀態**：Accepted
- **日期**：2026-10-22
- **Agent**：`antigravity`
- **任務**：`TASK-003`
- **相關規格**：[`SPEC-002`](../specs/002-video-engine.md)

## 1. 背景與問題

教學影片與學術報告常包含兩種迥異的呈現情境：
1. **投影片演講**：講者已有精心製作的 PowerPoint 投影片，包含豐富的內建物件動畫與段落點擊（`[click]`）。
2. **學術海報介紹**：講者僅有一張超高解析度（4K+）的靜態海報 PDF 或圖片，需要像紀錄片一樣動態平移縮放鏡頭帶到各個圖表、重點區域並疊加解說浮水印。

系統需要以統一的講稿配音介面，同時支援這兩種完全不同的畫面渲染管線。

## 2. 評估過的方案

| 方案 | 優點 | 缺點 |
|---|---|---|
| A. 雙引擎架構：PowerPoint AppleScript 自動化模式 + ffmpeg Poster 視窗運動渲染引擎 | 滿足雙重場景；簡報動畫與海報鏡頭各取所長，輸出品質最高 | 需要支援 macOS 專用 AppleScript（PPTX 模式）及 ffmpeg complex filter |
| B. 純網頁/Canvas/Remotion 重新繪製 | 跨平台能力強 | 無法重現 PowerPoint 複雜的轉場動畫與圖表效果；海報 4K 即時轉檔負擔重 |
| C. 僅支援海報模式 | 架構單純 | 無法服務既有的大量 PPTX 投影片教學需求 |

## 3. 決策與理由

**採用方案 A**：
1. **PowerPoint 模式（`pptx.py`）**：
   - 先透過 TTS 產生單句配音並組裝出完整 `narration.wav`。
   - 依據講稿標記的 `[click]` 計算每頁投影片與每個動畫的停留秒數，寫入 `timing.tsv`。
   - 透過 AppleScript 指令自動調整 PPTX 每頁延遲並呼叫 PowerPoint 原生功能匯出無聲影片，再以 ffmpeg 合成音訊與字幕。
2. **海報鏡頭動畫模式（`poster.py`, `storyboard.py`, `overlay.py`）**：
   - 依據 `scenes.toml` 定義的每幕海報座標區域（`box = [left, top, right, bottom]`）。
   - 計算鏡頭平滑插值，利用 ffmpeg 與 PIL 進行畫面平移、縮放、疊加提示欄（callout）與文字框。
3. **驗收機制（`media.py`）**：
   - 無論哪種模式，最後統一經由 `finish_video` 燒錄繁體中文字幕、檢查影音時長一致性並輸出 `video_contact_sheet.jpg` 縮圖。

## 4. 影響與代價

- **正面影響**：
  - 同一套講稿系統（`script.md`）可靈活切換 PPT 演講影片或海報解說影片。
  - 保證了專業海報與教學簡報的視覺水準。
- **代價**：
  - PPTX 匯出影片依賴本機 macOS 與 Microsoft PowerPoint 應用程式。無此環境時需使用海報模式或預先匯出之畫面。
