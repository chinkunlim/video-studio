---
name: adr-issue-tracker
description: >-
  Creates and maintains Architecture Decision Records (docs/adr/NNN-*.md & DECISIONS.md)
  and Known Issues (docs/known-issues/NNN-*.md & KNOWN_ISSUES.md) with four-way traceability.
  Activate whenever making an architectural trade-off, replacing a pattern, or discovering a bug/quirk.
---

# ADR & Known-Issues Tracker — 四向溯源知識庫管理員

> **可執行工具**：[`scripts/tracker_cli.py`](scripts/tracker_cli.py)

本技能透過 `tracker_cli.py` 自動分配下一個 `ADR-NNN` 或 `ISSUE-NNN` 編號，建立獨立說明檔並同步更新 `docs/adr/DECISIONS.md` 與 `docs/known-issues/KNOWN_ISSUES.md` 總表。

---

## 1. 自動調用 Python 工具 (`tracker_cli.py`)

1. 自動新增一筆架構決策 (ADR-NNN) 並寫入 DECISIONS.md 總表

```bash
python3 .agents/skills/adr-issue-tracker/scripts/tracker_cli.py \
  --add-adr "sqlite-wal-lock" \
  --title "採用 SQLite WAL 模式處理本機並發鎖" \
  --summary "避免檔案鎖在高並發下產生競爭" \
  --agent claude-code --task TASK-004

```

2. 自動新增一筆已知問題 (ISSUE-NNN) 並寫入 KNOWN_ISSUES.md 總表 (狀態: open | mitigated | resolved)

```bash
python3 .agents/skills/adr-issue-tracker/scripts/tracker_cli.py \
  --add-issue "webhook-302-redirect" \
  --title "Webhook 302 轉址導致重試風暴" \
  --status resolved \
  --summary "改用直接回傳 200 HTML 避免第三方不跟隨 302 轉址"

```

3. 列出目前所有 ADR 與 Known Issues 總表

```bash
python3 .agents/skills/adr-issue-tracker/scripts/tracker_cli.py
```

新紀錄依照資料夾裡的 `_TEMPLATE.md` 產生（可自行修改範本）；產生的檔案會留下 `TODO` 欄位（方案比較、根因、防回歸測試），**Agent 必須補完**；並在相關程式碼加註 `Refs: ADR-NNN` / `Refs: ISSUE-NNN`。
