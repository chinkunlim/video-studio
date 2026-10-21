---
name: code-review-guard
description: >-
  Static review before committing: required comments (file header, function description,
  every parameter documented), layer rules (env vars only in config), hard-coded secrets,
  function size/params/nesting, project paired-call rules, and deleted-comment warnings.
  Use after writing or refactoring code and before committing.
---

# Code Review Guard — 註解、分層、秘密與函式大小檢查

> **可執行工具**：[`scripts/review_guard.py`](scripts/review_guard.py)（pre-commit hook 與 `agentctl closeout` 也會自動執行）

## 1. 執行

完整報告

```bash
python3 .agents/skills/code-review-guard/scripts/review_guard.py
```

JSON

```bash
python3 .agents/skills/code-review-guard/scripts/review_guard.py --json
```

審查 + 目錄樹 + 依賴檢查

```bash
python3 scripts/agentctl.py check
```

只掃描 `.agents/project.toml` 的 `[architecture] source_roots`。`CRITICAL` 會讓指令回傳 1（並擋下 commit）。

## 2. 檢查項目

| 類別 | 等級 | 規則（門檻在 `[quality]`） |
|---|---|---|
| 註解 | CRITICAL | 檔案開頭說明；每個函數/類別有說明；每個參數都有寫（Python `Args:`，或 Open WebUI 工具用的 `:param name:`；JS `@param`；Go/Rust 需 `//` / `///`）；HTML 在 `<!DOCTYPE>` 後要有 `<!-- -->`、CSS 開頭要有 `/* */`。測試檔不檢查。`require_docstrings = false` 可關閉 |
| 分層 | CRITICAL | 只有 `env_access_layers`（預設 `config`）可讀環境變數；import 方向由 `agentctl check` 的依賴圖檢查 |
| Log | CRITICAL | Python 在 `[quality] print_allowed_layers`（預設 `entrypoints`）以外不可 `print`，改用 `logging.getLogger(__name__)` |
| 檔案大小 | CRITICAL / 警告 | 超過 `hard_max_file_lines` 為 CRITICAL（拆成子模組）；超過 `max_file_lines` 為警告 |
| 秘密 | CRITICAL | API key、token、私鑰等硬編碼 |
| 函式大小 | CRITICAL / 警告 | 超過 `hard_max_function_lines` 為 CRITICAL；超過 `max_function_lines`、`max_params`、`max_nesting` 為警告 |
| 專案規則 | CRITICAL | `[project_rules] paired_calls`（例如有 `acquire_lock` 就必須有 `release_lock`）；`forbidden_imports`（例如新專案禁止 `flask`，一律用 FastAPI） |
| Diff 衛生 | 警告 | 未提交的修改刪除超過 3 行既有註解（Karpathy「Surgical Changes」） |

## 3. 修正方式

- 缺少註解：依 [`CODING_PRINCIPLES.md`](../../../docs/standards/CODING_PRINCIPLES.md) §0 的範本補上。
- 分層違規：把讀環境變數的程式移到 `config` 層，再把值當參數傳下去。
- 函式過長：抽出子函式（一個函式只做一件事），用 early return 減少巢狀。
- 用了 `print`：改成模組 logger（`logger = logging.getLogger(__name__)`）；CLI 要給使用者看的結果才放在 `entrypoints`。
- 舊專案遷移：從 `legacy/` 原樣 `git mv` 進來的檔案，pre-commit 只放行那一次 commit 的註解、大小、分層與 print 問題；下一個 commit 必須補齊（見 `legacy-migration` skill）。
