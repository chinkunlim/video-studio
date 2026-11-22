# ISSUE-004：agy -p non-interactive mode denied file reads and fell back to Ollama hallucination

- **狀態**：🟢 已根治 (Resolved)
- **發現日期**：2026-11-16
- **Agent**：`Antigravity`
- **任務**：`-`

## 1. 現象

run_agy_prompt lacked --add-dir and --dangerously-skip-permissions, and script_drafter did not extract PDF/PPTX text.

- **錯誤訊息**：`agy -p` 過程出現讀取工作區目錄權限拒絕並以非預期 exit code 結束，進而退回 Ollama 幻覺內容。
- **重現步驟**：於 Web Studio 呼叫 AI 起草講稿或規劃簡報，目標素材位於專案根目錄以外的 `DATA_DIR`。
- **影響範圍**：`services/planner.py`（`run_agy_prompt`）與 `services/script_drafter.py`（`draft_script_to_review`）。

## 2. 根本原因

agy -p auto-denied read_file outside project root, causing fallback to Ollama qwen2.5 without document text.

## 3. 修正或規避方式

Pass --add-dir job.dir and --dangerously-skip-permissions to agy -p, and extract PDF/PPTX text directly into the prompt.（相關程式碼註解加 `Refs: ISSUE-004`）

## 4. 防回歸

`tests/test_avatar_script_bilingual.py::TestAvatarScriptBilingual.test_script_draft_to_review_and_load` 及 `tests/test_studio_ui_and_planner.py::TestStudioUIAndPlanner.test_agy_planner_streams_response` 驗證非互動式 prompt 參數與 PDF/PPTX 摘錄管線。
