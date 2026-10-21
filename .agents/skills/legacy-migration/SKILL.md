---
name: legacy-migration
description: >-
  Migrate an old project that was moved into legacy/ by the template's scripts/migrate_project.py, one batch at a
  time, until the whole program meets every rule of the new project (structure, comments,
  types, layers, tests, docs, uv/pnpm). Use when docs/migration/MIGRATION.md exists, or when
  the user asks to continue or finish the migration.
---

# Legacy Migration — 舊專案逐批搬到新結構

> **可執行工具**：[`scripts/migration_status.py`](scripts/migration_status.py)（也可用 `python3 scripts/agentctl.py migration`）
>
> **目標**：不只是把檔案搬過來，而是**整個程式符合新專案的所有要求**——standards、文件結構、程式註解、型別、測試、依賴管理。`agentctl migration --verify` 全部通過才算完成。

## 0. 模式（Flask 專案）

| 模式 | 什麼時候 | 規則 |
|---|---|---|
| `maintain`（預設） | 舊專案已完工，只需要維護 | 保留 Flask；結構、註解、型別、測試、依賴仍須符合新規範 |
| `develop` | 舊專案要繼續開發 | Flask 全部改寫成 FastAPI（對照表：[`FLASK_TO_FASTAPI.md`](FLASK_TO_FASTAPI.md)）；`import flask` 會被擋下 |

維護模式的專案之後要繼續開發時，先切換再接手改寫任務：

```bash
python3 scripts/agentctl.py migration --develop
```

資料庫：舊的 SQLAlchemy 模型搬到 `src/<pkg>/adapters/db/`；舊的 Alembic / Flask-Migrate revision 搬到 `alembic/versions/`（保留 revision ID，刪除範例的 `greetings` revision 與模型）；`.db` 資料檔複製到 `DATA_DIR/db/`（專案資料夾之外，不進 git；見 MIGRATION.md §4.5）。完成後 `uv run alembic upgrade head && uv run alembic check` 必須通過。

## 1. 開始前

1. 閱讀 `docs/migration/MIGRATION.md`（批次、檔案清單、依賴轉換、風險、完成標準）。
2. 先處理「風險」：被 git 追蹤的機密檔要先移除並請使用者更換金鑰。
3. 查看進度並接手下一批：

```bash
python3 scripts/agentctl.py migration
```

```bash
python3 scripts/agentctl.py task claim TASK-NNN --agent <你的名字>
```

## 2. 每一批的步驟

1. **先搬移，單獨一個 commit，內容不改**：git 一定會記成改名，`git log --follow` 與 blame 追得到舊歷史。pre-commit 只對「從 legacy/ 原樣搬入」的檔案暫時放行註解、大小、分層與 print 問題（秘密與禁用套件仍會擋）。一批只搬少量檔案，因為下一個 commit 必須全部整理好：

```bash
git mv legacy/舊路徑/檔案.py src/<pkg>/<layer>/新檔名.py
```

```bash
python3 scripts/agentctl.py commit --bump none -m "refactor(migration): move 檔案.py from legacy"
```

2. **依新規範修改**（一次一個檔案，改完就測）：
   - 檔案開頭用途說明；每個函數/類別說明；每個參數 `Args:`（JS `@param`）；回傳值。
   - Python 型別完整，`uv run mypy` 通過。
   - 放在正確的層；環境變數只在 `config` 讀，其他層改收參數；函式過長就拆。
   - `print` 改模組 logger（只有 entrypoints 可 print），關鍵步驟、外部呼叫與例外補上 log（`CODING_PRINCIPLES.md` §0.4）；金鑰移到 `.env`。
   - 依賴用 `uv add` / `pnpm add`，不用 pip / npm；本機服務綁 `127.0.0.1`。
   - 沿用或補寫測試（舊測試搬到 `tests/` 並改成新的 import 路徑）。
3. **驗證**：

```bash
python3 scripts/agentctl.py check
```

```bash
uv run python -m unittest discover -s tests -v
```

4. **紀錄**：`MIGRATION.md` 檔案清單把這批的 `☐` 改成 `☑`；重要決策寫 ADR、發現的舊 bug 寫 known-issue（`adr-issue-tracker`）。
5. **提交並完成任務**：

```bash
python3 scripts/agentctl.py commit --agent <你的名字> --task TASK-NNN
```

```bash
python3 scripts/agentctl.py task done TASK-NNN --summary "搬移並整理 <內容>"
```

一批做不完就 `agentctl task handoff`，寫清楚已完成與待辦。

## 3. 依賴批次（通常是第一批）

- 依 `MIGRATION.md` §4 的指令把依賴加進 `pyproject.toml` / `package.json`，確認版本後刪除 `legacy/` 裡的 `requirements.txt`、`package-lock.json` 等。
- 舊 `.env.example` 的變數名稱加到新的 `.env.example`；舊 `Brewfile` 合併到根目錄 `Brewfile`。

## 4. 最後收尾

1. 確認 `legacy/` 只剩不需要的檔案，刪除：

```bash
git rm -r legacy
```

2. 刪除模板的範例程式（greeting），改寫 `README.md`、`docs/architecture/ARCHITECTURE.md`，主要功能補 `docs/specs/`。
3. 驗收（全部 ✅ 才算完成）：

```bash
python3 scripts/agentctl.py migration --verify
```

4. `agentctl closeout`，在對話摘要與交接看板寫下遷移完成。
