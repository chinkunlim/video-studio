# ISSUE-001：影片驗收驗證時缺少 video_contact_sheet.jpg 產出邏輯

- **狀態**：🟢 已根治 (Resolved)
- **發現日期**：2026-10-22
- **Agent**：`antigravity`
- **任務**：`TASK-005`

## 1. 現象

在執行端到端影片渲染測試 `tests/test_workflow_video.py` 時，呼叫 `finish_video` 進入驗收階段，`media.check` 檢查影片輸出目錄時拋出錯誤，指缺少聯絡單影格圖檔 `video_contact_sheet.jpg`。

- **錯誤訊息**：`FileNotFoundError: 缺少 video_contact_sheet.jpg`
- **重現步驟**：呼叫 `video_studio.services.video.video.finish_video` 產出影片後執行驗收檢查。
- **影響範圍**：所有 generate 與 dub 工作類型的成品驗收與縮圖生成流程。

## 2. 根本原因

在自 legacy 搬遷 `video/engine/media.py` 時，`check` 函式中保留了對 `video_contact_sheet.jpg` 產物的檢查，但原本舊專案負責以 ffmpeg 抽格並組裝 4x3 網格縮圖的 `_generate_contact_sheet` 輔助邏輯在整理重構時未完整搬入，導致驗收時必定檢測失敗。

## 3. 修正或規避方式

在 `src/video_studio/services/video/engine/media.py` 的 `check` 函式中，重新補齊使用 ffmpeg 抽樣 12 個時間點畫面並調用 tile filter 組合成單張 `video_contact_sheet.jpg` 的邏輯。

相關程式碼位置：`src/video_studio/services/video/engine/media.py`。

## 4. 防回歸

已於 `tests/test_workflow_video.py` 中建立 `test_mux_and_check_video_workflow`，完整驗證：
1. 合成影音檔產生。
2. 字幕燒錄。
3. 抽樣 `video_contact_sheet.jpg` 與 `video_thumb.jpg` 的完整生成與尺寸校驗。
