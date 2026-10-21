# Git、版本與收尾規範 (Git, Versioning & Closeout)

> **AI Agent 載入時機**：準備 commit、發版，或使用者說「結束對話 / 收工 / 今天先這樣 / wrap up」時。

---

## 1. Commit 鐵律

1. **每完成一個可獨立通過測試的修改就 commit 一次**（本機）：
   ```bash
   python3 scripts/agentctl.py commit --agent <agent-name> --model <model> [--task TASK-NNN] [-m "feat(services): ..."]
   ```
   `auto_commit.py` 會自動：
   - 產生 Conventional Commit 標題（或使用 `-m`），加上 `[agent:<name>]`。
   - 寫入 Git trailers：`Agent:`、`Model:`、`Task:`、`Version:`、`Co-Authored-By:` → 之後可用 `git log --grep="Agent: claude-code"` 或 `agentctl audit` 追蹤。
   - 在 `CHANGELOG.md` 的 `## [Unreleased]` 加一行（依類型分到 Added / Fixed / Documentation…；只改測試、只改交接看板/任務卡、或 `--bump none` 時不寫）。**不升版**。
   - 只暫存它列出的檔案，掃描**已暫存內容**中的秘密（含新檔案），失敗時還原它改過的檔案。
2. **commit 訊息一律英文**（Conventional Commits，例如 `feat(services): add pricing module`），不要在標題加日期（git 本身有日期）。文件內容可以用中文。
3. **未經使用者明確同意，不得 `git push`。** `.agents/hooks/pre-push` 會擋下一般的 push；使用者同意後，`agentctl commit --push` 會自動帶 `ALLOW_PUSH=1`，手動推送則用 `ALLOW_PUSH=1 git push`。
4. **中途離開**（去上課、開會）：`python3 scripts/agentctl.py pause "<English reason>"`，在交接看板留紀錄並做一次 `wip(handoff)` commit（不寫 CHANGELOG）。程式還沒寫完、過不了檢查時不會 commit，改動和紀錄都留在工作區，回來補齊再 commit。
5. **不要繞過 pre-commit hook**（`--no-verify`）。Hook 由 `git config core.hooksPath .agents/hooks` 啟用，會檢查秘密、憑證檔與 `code-review-guard`；新電腦請先執行 `python3 scripts/agentctl.py doctor --fix`。

## 2. 版本：平常累積，發布時才升版

- **平常**：每次 commit 只把一行說明加到 `CHANGELOG.md` 的 `## [Unreleased]`，版本號不變，避免版本號因頻繁 commit 而膨脹。
- **發布**（交付、里程碑，或使用者說要出版本）。升版幅度預設 auto：有 Added 就 minor，否則 patch；要大改版時加 `--bump major`。
  ```bash
  python3 scripts/agentctl.py finish --tag
  ```
  完成驗收全部通過後才會：把 Unreleased 改成 `## [X.Y.Z] - 日期`、更新版本檔（`pyproject.toml` / `package.json` / `VERSION`）、做一個 `chore(release)` commit、建立本機 tag `vX.Y.Z`（不推送）。

## 3. 主動提醒推送

符合任一條件時，Agent 必須**詢問**使用者是否 `git push`：
- 未推送 commit 數 ≥ `push_reminder_threshold`（預設 5）。
- 剛發布新版本（`finish --tag`）。
- 完成里程碑、或使用者要結束對話。

## 4. 結束對話收尾 (Session Closeout)

使用者說「結束對話 / 收工 / 今天先這樣 / wrap up」時執行：

```bash
python3 scripts/agentctl.py closeout --agent <name> --model <model> \
  --goal "本次目標" --decisions "做了什麼、為什麼" --issues "錯誤與根因" --next "下一步" --note "一句話交接"
```

1. 跑測試與 `code-review-guard`，失敗就停止並修復。
2. 更新入口檔與目錄樹。
3. 在 `.agents/conversations/` 寫入這次對話的**逐字稿＋摘要**兩個檔案（去除個資、只存本機、不進 git）；摘要沒提供的欄位會留 TODO，**Agent 必須補完**。
4. 更新 `.agents/handoff/LATEST.md`。
5. 本機 commit，列出未推送的 commit 並詢問是否推送。

任務沒做完就要結束時，先執行 `agentctl task handoff TASK-NNN --done-items ... --todo-items ... --blockers ...`。

## 5. 溯源查詢

產生完整報告 `docs/architecture/AGENT_AUDIT_REPORT.md`（需要時才產生、不進 git；真正的紀錄是 git trailers 與任務卡）

```bash
python3 scripts/agentctl.py audit
```

某個 Agent 做過的事

```bash
python3 scripts/agentctl.py audit --agent claude-code
```

某個檔案被誰改過

```bash
python3 scripts/agentctl.py audit --file src/app/x.py
```

某個任務的所有 commit

```bash
git log --grep="Task: TASK-003"
```

找過去遇過的錯誤與根因

```bash
grep -rn "timeout" docs/known-issues .agents/conversations
```
