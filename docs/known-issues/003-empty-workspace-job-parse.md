# ISSUE-003：Empty workspace job list parsed sv.py as job name causing 500 error

- **狀態**：🟢 已根治 (Resolved)
- **發現日期**：2026-11-16
- **Agent**：`Antigravity`
- **任務**：`-`

## 1. 現象

When workspace has no jobs, studio.js split the help text and sent sv.py to /api/jobs/*/detail.

- **錯誤訊息**：`HTTP 500 Internal Server Error`（對 `/api/jobs/sv.py/detail` 發送請求時未攔截 `JobError`）
- **重現步驟**：在空工作區（尚無任何 job）下開啟 Web Studio 首頁，前端解析 `/api/jobs` 回傳的幫助提示文字行並選取誤判的 `sv.py` 觸發載入。
- **影響範圍**：全新或空工作區首次開啟 Web Studio UI 的所有使用者。

## 2. 根本原因

studio.js split every line of /api/jobs output instead of matching job rows, and routes did not catch J.JobError.

## 3. 修正或規避方式

Match only ^(generate|dub|extract) job lines in studio.js and return HTTP 404 on J.JobError.（相關程式碼註解加 `Refs: ISSUE-003`）

## 4. 防回歸

`tests/test_studio_ui_and_planner.py::TestStudioUIAndPlanner.test_studio_static_assets` 驗證 `studio.js` 包含 `^(generate|dub|extract)` 過濾正則，且呼叫不存在的 `/api/jobs/nonexistent-job/detail` 回傳 HTTP `404`。
