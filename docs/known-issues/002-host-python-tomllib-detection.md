# ISSUE-002：舊版主機 Python 環境下執行 check 誤報 tomllib 未宣告依賴

- **狀態**：🟢 已根治 (Resolved)
- **發現日期**：2026-10-22
- **Agent**：`antigravity`
- **任務**：`TASK-005`

## 1. 現象

在 macOS 預設環境（系統 `/usr/bin/python3` 為 Python 3.9）下執行 `python3 scripts/agentctl.py check`，雖然虛擬環境 `uv` 為 Python 3.11，但在依賴檢查階段（`setup_env.py` 的 `check_dependencies`）仍拋出警告並回傳非 0 錯誤碼：

- **錯誤訊息**：
  ```text
  ⚠️ 以下 import 尚未宣告為依賴（確認套件名稱後執行 `uv add <套件>`，不要用 pip）：
     - tomllib          (於 src/video_studio/services/common/check.py)  建議套件：tomllib
  ```
- **重現步驟**：在系統 Python < 3.11 的主機上執行 `python3 scripts/agentctl.py check`。
- **影響範圍**：所有使用了 Python 3.11 內建 `tomllib` 的程式碼模組檢驗。

## 2. 根本原因

`.agents/bin/setup_env.py` 的 `is_stdlib` 函式是藉由當前執行腳本之 Python 解譯器的 `sys.stdlib_module_names` 來判斷模組是否為標準函式庫。因為專案外層的 `agentctl.py` 預設以主機系統 `python3`（3.9.6）執行，在 Python 3.9 的 `sys.stdlib_module_names` 中尚未包含 Python 3.11 才加入的 `tomllib`，導致其被誤判為第三方套件。

## 3. 修正或規避方式

在 `.agents/bin/setup_env.py` 的 `is_stdlib` 檢查中，加入對 Python 3.11+ 新增標準函式庫模組（如 `tomllib`）的白名單判定：
```python
if (
    name in getattr(sys, "stdlib_module_names", ())
    or name in sys.builtin_module_names
    or name == "__future__"
    or name in {"tomllib"}
):
    return True
```
同時於 `docs/TEMPLATE_FEEDBACK.md` 提出母版框架改進建議。

## 4. 防回歸

已透過 `python3 scripts/agentctl.py check` 與 `python3 scripts/agentctl.py migration --verify` 驗證其不再回報 `tomllib` 為未宣告依賴，全部通過。
