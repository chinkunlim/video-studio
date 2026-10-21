---
name: session-closeout
description: >-
  End-of-session protocol: run tests and code-review-guard, write the local conversation
  record (full transcript + summary of goal, decisions, errors and root causes, next steps)
  to .agents/conversations/ (not in git), update the handoff board, commit locally, and ask
  whether to push. Use when the user says
  "結束對話", "收工", "今天先這樣", "wrap up", or when 5+ unpushed commits have accumulated.
---

# Session Closeout — 結束對話收尾

> **可執行工具**：[`scripts/closeout_runner.py`](scripts/closeout_runner.py)（也可用 `python3 scripts/agentctl.py closeout`）

## 1. 執行

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
3. 在 `.agents/conversations/` 寫入兩個檔案（去除個資、只存本機、不進 git，專案結束可刪）：
   - `YYYY-MM-DD-HHMM-<agent>-transcript.md`：完整逐字稿（Claude Code 自動讀取；其他工具用 `--transcript <匯出檔>`）。
   - `YYYY-MM-DD-HHMM-<agent>-summary.md`：摘要。
   交接看板 `LATEST.md`（在 git）會記下目標、錯誤根因、下一步各一行，換電腦也看得到。
4. 更新 `.agents/handoff/LATEST.md`。
5. 本機 commit（若你只有一個進行中任務，只提交該任務範圍），列出未推送的 commit。

## 2. 收尾後 Agent 必須做的事

1. 打開剛產生的摘要，**補完所有 `TODO(...)` 欄位**（摘要不進 git，不需要再 commit）。重大決策另寫 ADR、會重複發生的錯誤另寫 known-issue，這兩者會進 git。
2. 若任務還沒完成，先執行 `agentctl task handoff TASK-NNN --done-items ... --todo-items ... --blockers ...`。
3. 依輸出詢問使用者：「目前累積 N 個未推送 commit，要推送到 GitHub 嗎？」——**得到同意才可加 `--push`**。
