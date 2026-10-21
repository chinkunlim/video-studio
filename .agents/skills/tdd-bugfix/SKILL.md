---
name: tdd-bugfix
description: >-
  Enforces the Iron Law of TDD ("No production code without a failing test first",
  based on obra/superpowers test-driven-development) and offline fixture-driven bug fixing.
  Activate whenever implementing a new feature or fixing a bug.
---

# TDD & Fixture-Driven Bugfix — 測試驅動開發與防回歸修復

> **GitHub 來源基準**：整合自 [`obra/superpowers/test-driven-development`](https://github.com/obra/superpowers)。
> **可執行工具**：[`scripts/tdd_runner.py`](scripts/tdd_runner.py)

---

## 1. TDD 鐵律 (The Iron Law)

```text
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
(沒有先看到失敗的測試，就不准寫正式產品程式碼)
```

---

## 2. 自動調用 Python 工具 (`tdd_runner.py`)

Step 1 (RED)：建立預設會失敗的測試與 fixture（Python: tests/；Node: test/*.test.cjs）

```bash
python3 .agents/skills/tdd-bugfix/scripts/tdd_runner.py --new-test search_parser --fixture-ext html

```

Step 2 (Watch it Fail / Verify Green)：執行專案完整離線測試套件

```bash
python3 .agents/skills/tdd-bugfix/scripts/tdd_runner.py --verify
```

---

## 3. Red ➔ Green ➔ Refactor 標準循環

1. **RED**：執行 `tdd_runner.py --new-test <name>` 建立測試與 fixtures 靜態樣本，填入預期斷言並執行 `--verify` **親眼確認它失敗**。
2. **GREEN**：在 `src/` 撰寫通過測試所需的**最小原子化實作**，再次執行 `--verify` 確認全套測試 100% 綠燈。
3. **REFACTOR**：在保持全綠的前提下，使用 `code-review-guard` 檢查並消除重複程式碼（DRY）與過長函式（Atomic）。
