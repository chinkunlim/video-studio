---
name: session-closeout
description: >-
  End-of-session protocol: first bring every Markdown document up to date with what this
  session changed, then run tests and code-review-guard, write the local conversation record
  (full transcript + summary of goal, decisions, errors and root causes, next steps) to
  .agents/conversations/ (not in git), update the handoff board, commit, and push to GitHub.
  Use when the user says "結束對話", "收工", "今天先這樣", "wrap up", or when 5+ unpushed
  commits have accumulated.
---

# Session Closeout — 結束對話收尾

> **可執行工具**：[`scripts/closeout_runner.py`](scripts/closeout_runner.py)（也可用 `python3 scripts/agentctl.py closeout`）
>
> **使用者的決定**：說「收工 / 結束對話」就代表同意**更新所有文件並推送到 GitHub**，收尾時不必再問一次要不要推送。
> 使用者明確說「先不要推送」時才加 `--no-push`。

## 1. 先全面更新所有 Markdown 文件（Agent 做，在執行收尾指令之前）

收尾指令會 commit 並推送，所以文件要在那之前改好。逐一檢查專案自己的 `.md`，依**這次對話實際做了什麼**更新，不要只改日期：

| 文件 | 檢查什麼 |
|---|---|
| `README.md`（以及 `web/WEB.md`、`gas/GAS.md`、`mobile/MOBILE.md`、`API.md` 等說明檔） | 安裝步驟、指令、功能清單、資料夾說明、範例是否和現在的程式一致 |
| `CHANGELOG.md` | `## [Unreleased]` 是否涵蓋這次所有使用者看得到的修改（`agentctl commit` 只會加一行標題） |
| `docs/architecture/ARCHITECTURE.md` | 元件、資料流、分層、外部服務有沒有變 |
| `docs/specs/` | 需求或 API 規格有沒有改；新功能要有規格 |
| `docs/adr/`、`docs/known-issues/` | 這次的架構取捨、錯誤根因是否都已記錄（用 `adr-issue-tracker`），總表是否更新 |
| `docs/standards/PROJECT_RULES.md` | 使用者這次說的「本專案以後都要這樣」的規則 |
| `docs/TEMPLATE_FEEDBACK.md` | 使用者這次說的「每個專案都要這樣」的規則 |
| `AGENTS.md` 中由專案維護的段落（Agent 分工等） | 是否仍然正確（規則段落、SKILLS、目錄樹由工具產生） |
| 其他 `docs/**/*.md`（`INTEGRATIONS.md`、`migration/MIGRATION.md` …） | 是否仍然正確 |

不需要手動改的（由工具產生或由母版更新）：`CLAUDE.md`、`GEMINI.md`、`.github/copilot-instructions.md`、`.cursor/`、`.windsurf/`、`docs/architecture/PROJECT_TREE.md`、`.agents/handoff/LATEST.md`、`docs/standards/` 的通用規範、`.agents/skills/`。

## 2. 執行收尾

```bash
python3 scripts/agentctl.py closeout --agent <你的名字> --model <模型> \
  --goal "本次目標" \
  --decisions "做了什麼、關鍵決策與理由（重大者另寫 ADR）" \
  --issues "遇到的錯誤 → 根本原因 → 修正方式" \
  --next "下一位 Agent 從哪裡開始" \
  --note "一句話交接"
```

步驟：
1. 執行 `[commands] test` 與 `code-review-guard`，失敗就停止（先修好再收尾）。
2. 更新入口檔與目錄樹。
3. **文件檢查**：列出這次（未 commit 的修改＋還沒推送的 commit）已更新的文件，以及**沒有修改**的文件。同時自動檢驗：
   - 若填寫了 `--issues`，檢查 `docs/known-issues/` 是否有新增/更新記錄；
   - 若填寫了架構決策 `--decisions` 或異動架構檔，檢查 `docs/adr/` 是否有新增/更新 ADR；
   - 若修改了程式碼，檢查 `CHANGELOG.md` 是否有記錄於 `## [Unreleased]`。
   - 使用 `--strict-docs` 可強制阻斷缺漏。若發現漏改的文件，收尾完成後立刻補上，再 `agentctl commit --push`。
4. 在 `.agents/conversations/` 寫入兩個檔案（去除個資、只存本機、不進 git，專案結束可刪）：
   - `YYYY-MM-DD-HHMM-<agent>-transcript.md`：完整逐字稿（Claude Code 自動讀取；其他工具用 `--transcript <匯出檔>`）。
   - `YYYY-MM-DD-HHMM-<agent>-summary.md`：摘要。
   交接看板 `LATEST.md`（在 git）會記下目標、錯誤根因、下一步各一行，換電腦也看得到。
5. 更新 `.agents/handoff/LATEST.md`。
6. 本機 commit（若你只有一個進行中任務，只提交該任務範圍）。
7. **推送到 GitHub**（目前分支的 upstream，自動帶 `ALLOW_PUSH=1` 通過 pre-push hook）。
   - 沒有 upstream：不推送並說明；問使用者要推到哪個 repo，同意後 `ALLOW_PUSH=1 git push -u origin <分支>`。
   - 推送失敗（例如遠端有新的 commit）：commit 留在本機，把錯誤告訴使用者，**不要 force push**。

## 3. 收尾後 Agent 必須做的事

1. 打開剛產生的摘要，**補完所有 `TODO(...)` 欄位**（摘要不進 git，不需要再 commit）。
2. 若任務還沒完成，先執行 `agentctl task handoff TASK-NNN --done-items ... --todo-items ... --blockers ...`（這會產生新的修改：再 `agentctl commit --push`）。
3. 回報使用者：更新了哪些文件、commit、推送到哪個 repo（或為什麼沒推送）。
