# ISSUE-005：Narrate and render status logs reset to default text after page refresh

- **狀態**：🟢 已根治 (Resolved)
- **發現日期**：2026-11-16
- **Agent**：`Antigravity`
- **任務**：`-`

## 1. 現象

After refreshing the Web UI, #narrateLog and #renderLog showed 尚未執行/尚未渲染 even when output/vN already contained narration.wav and video.mp4.

- **錯誤訊息**：無例外錯誤；UI 狀態顯示 `#narrateLog` =「尚未執行」、`#renderLog` =「尚未渲染」。
- **重現步驟**：完成配音與渲染並產出 `output/<job>/vN/narration.wav` 與 `video.mp4` 後，重新整理 Web Studio 頁面並選取同一工作。
- **影響範圍**：`src/video_studio/entrypoints/static/studio.js`（`loadJobDetail`）所有工作的進度顯示面板。

## 2. 根本原因

studio.js only populated #narrateLog and #renderLog on button click without hydrating persisted output_files state in loadJobDetail().

## 3. 修正或規避方式

Hydrate #narrateLog and #renderLog in loadJobDetail() from latest_version and latest_files on page load.（相關程式碼註解加 `Refs: ISSUE-005`）

## 4. 防回歸

`tests/test_api_and_mcp.py::TestAPIAndMCP.test_mcp_tools_and_confirm_gate` 與 `tests/test_studio_ui_and_planner.py::TestStudioUIAndPlanner.test_studio_static_assets` 驗證 `/api/jobs/{job_name}/detail` 正確回傳 `latest_version` 與 `latest_files` 供前端載入還原。
