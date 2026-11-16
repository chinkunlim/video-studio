# ISSUE-004：agy -p non-interactive mode denied file reads and fell back to Ollama hallucination

- **狀態**：🟢 已根治 (Resolved)
- **發現日期**：2026-11-16
- **Agent**：`Antigravity`
- **任務**：`-`

## 1. 現象

run_agy_prompt lacked --add-dir and --dangerously-skip-permissions, and script_drafter did not extract PDF/PPTX text.

- **錯誤訊息**：TODO（貼上完整訊息或 log 片段）
- **重現步驟**：TODO
- **影響範圍**：TODO

## 2. 根本原因

agy -p auto-denied read_file outside project root, causing fallback to Ollama qwen2.5 without document text.

## 3. 修正或規避方式

Pass --add-dir job.dir and --dangerously-skip-permissions to agy -p, and extract PDF/PPTX text directly into the prompt.（相關程式碼註解加 `Refs: ISSUE-004`）

## 4. 防回歸

TODO: 對應的測試檔與測試名稱，確保不會再發生。
