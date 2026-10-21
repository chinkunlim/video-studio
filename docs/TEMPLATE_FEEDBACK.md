# 給專案模板的改進建議 (TEMPLATE_FEEDBACK)

> 使用者提出「以後每個專案都要這樣」的規則或習慣時，Agent 記在這裡（不直接改模板）。
> 使用者之後決定是否把它更新到專案模板（`01 project_template`），讓所有新專案都有。
>
> - 每條建議一列；**狀態**只用：`待決定`（新建議）、`已採用`（母版已更新）、`不採用`。
> - 使用者在母版執行 `python3 scripts/collect_feedback.py`，會一次列出所有專案中「待決定」的建議。

| 日期 | 建議 | 來源（對話 / 任務） | 狀態 |
|---|---|---|---|
| 2026-10-22 | `.agents/bin/setup_env.py` 的 `check_dependencies` 應支援 `IMPORT_HINTS` 對應之 PyPI 套件名稱（例如 `PIL` 對應 `Pillow`），避免已宣告 `Pillow` 時仍報 `PIL` 未宣告。 | TASK-002 | 待決定 |
| 2026-10-22 | `.agents/bin/auto_commit.py` 的 `stage_scan_commit` 於處理已刪除檔案時，應區分存在與不存在路徑，不存在者以 `git rm -q --cached --ignore-unmatch` 處理，避免 `git add -A -- <deleted_path>` 拋出 fatal pathspec 錯誤。 | TASK-004 | 待決定 |
| 2026-10-22 | `.agents/bin/setup_env.py` 的 `is_stdlib` 於主機 Python 版本低於 3.11（如 macOS 預設 3.9）時，應補齊 Python 3.11+ 新增之標準函式庫清單（如 `tomllib`），避免誤判為未宣告依賴。 | TASK-005 | 待決定 |
