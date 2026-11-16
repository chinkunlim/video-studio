# ISSUE-003：Empty workspace job list parsed sv.py as job name causing 500 error

- **狀態**：🟢 已根治 (Resolved)
- **發現日期**：2026-11-16
- **Agent**：`Antigravity`
- **任務**：`-`

## 1. 現象

When workspace has no jobs, studio.js split the help text and sent sv.py to /api/jobs/*/detail.

- **錯誤訊息**：TODO（貼上完整訊息或 log 片段）
- **重現步驟**：TODO
- **影響範圍**：TODO

## 2. 根本原因

studio.js split every line of /api/jobs output instead of matching job rows, and routes did not catch J.JobError.

## 3. 修正或規避方式

Match only ^(generate|dub|extract) job lines in studio.js and return HTTP 404 on J.JobError.（相關程式碼註解加 `Refs: ISSUE-003`）

## 4. 防回歸

TODO: 對應的測試檔與測試名稱，確保不會再發生。
