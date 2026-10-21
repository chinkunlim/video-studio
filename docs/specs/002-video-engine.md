# SPEC-002：影片合成與渲染引擎

- **狀態**：Implemented
- **日期**：2026-10-22
- **相關任務 / ADR**：TASK-002 / [`ADR-003`](../adr/003-dual-video-rendering-engines.md)

## 1. 目標

將生成的配音（`narration.wav`）與畫面素材（PowerPoint 投影片或高解析度海報）合成，自動對齊時間軸、燒錄字幕並產出完整影片。

## 2. 使用情境

配音生成完畢後，使用者希望產生完整簡報影片：
1. **PowerPoint 方式**：保留簡報動畫與點擊（`[click]`），自動依配音時間調整換頁與動畫延遲，由 PowerPoint 匯出影片後合成音訊。
2. **海報鏡頭動畫方式**：依據分鏡設定（`scenes.toml`），以原始高解析度海報為畫布，平滑平移縮放鏡頭並疊加提示欄、圖表外框與字幕。

## 3. 需求

- **必須 (Must)**：
  - 先配音量時長，再決定每頁影片長度（先聲後影）。
  - PowerPoint 模式自動校對講稿中的 `[click]` 與 PPTX 點擊動畫數量一致。
  - 海報渲染模式支援 1920x1080 30fps，並提供 `scenes_preview.jpg` 縮圖供確認。
  - 燒錄繁體中文字幕至影片，支援多種字幕格式匯出（YouTube SRT, PowerPoint VTT, VLC ASS）。
- **可選 (Nice to have)**：
  - 產出 `video_contact_sheet.jpg` 抽取每頁影格供快速人工驗收。

## 4. 介面 / API

- CLI:
  - `video-studio video timing <job>`
  - `video-studio video scenes <job>`
  - `video-studio video preview <job>`
  - `video-studio video poster <job>`
  - `video-studio video pptx <job>`
  - `video-studio video mux <job> --video <file>`
  - `video-studio video check <job>`

## 5. 驗收標準

- [x] 單元測試涵蓋時間解析、講稿解析與字幕生成
- [x] 通過 mypy strict 與 code-review-guard
