# 程式碼註解、Log 與 Karpathy 原則 (Code Comments, Logging & Karpathy Guardrails)

> **任務載入時機**：撰寫、修改或重構任何程式碼前必讀。

---

## 1. 註解規範（`code-review-guard` 與 pre-commit 會自動檢查）

**核心目標**：任何人（或下一個接手的 Agent）只讀註解，就能完全理解該檔案的用途、每個函數/類別的功能、以及每個參數的語意與限制。

| 項目 | 規範標準 |
|---|---|
| **檔案開頭** | 說明此檔案的核心**用途**；較大模組需補充「主要功能」與「用法範例」。 |
| **函數 / 方法 / 類別** | 一句話清楚說明**做什麼**（說明目的與成果，而非逐行翻譯怎麼做）。 |
| **每個參數** | 名稱 + 語意（必要時標明型別、單位、允許值範圍與預設行為）。格式需包含 `name:` 或 JSDoc `@param`。 |
| **回傳值** | 說明回傳物件的語意與結構；無回傳值可省略。 |
| **例外拋出** | 說明會主動拋出的例外型別與觸發條件（`Raises:` / `@throws`）。 |
| **行內註解** | 只寫「為什麼這樣做」（非直覺的取捨、外部系統限制、相關 ADR/ISSUE 編號），禁止流水帳式翻譯程式碼。 |

### 多語言標準範例

#### Python（Google style docstring）
```python
"""Order pricing service.

Calculates order totals including tax and discounts. Used by the checkout API.
"""


def calculate_total(items: list[Item], tax_rate: float, coupon: str | None = None) -> Decimal:
    """Calculate the payable total of an order.

    Args:
        items: Line items in the cart; must not be empty.
        tax_rate: Tax rate as a fraction, e.g. 0.05 for 5%.
        coupon: Optional coupon code; unknown codes are ignored.

    Returns:
        Total amount rounded to 2 decimals.

    Raises:
        ValueError: When `items` is empty.
    """
```

#### JavaScript / TypeScript（JSDoc）
```javascript
/**
 * @file Order pricing service used by the checkout API.
 */

/**
 * Calculate the payable total of an order.
 * @param {Item[]} items Line items in the cart; must not be empty.
 * @param {number} taxRate Tax rate as a fraction, e.g. 0.05 for 5%.
 * @param {string} [coupon] Optional coupon code.
 * @returns {number} Total amount rounded to 2 decimals.
 * @throws {Error} When items is empty.
 */
export function calculateTotal(items, taxRate, coupon) { ... }
```

#### HTML / CSS
```html
<!DOCTYPE html>
<!--
  Order page: lists cart items and submits the checkout form to /api/orders.
-->
<html lang="zh-Hant">
```

```css
/*
 * Checkout page styles: layout, form controls, error states.
 */
```

#### Go / Rust
- **Go**：檔案開頭 `// Package xxx ...`；每個函數上方 `// FuncName does ...`，參數寫在同一段註解中。
- **Rust**：檔案開頭 `//! ...`；每個函數上方 `/// ...`，參數用 `/// * \`name\` - 說明`。

---

## 2. Log 紀錄規範（系統可觀測性與追蹤）

1. **每個模組建立獨立 Logger**：在有定義函式的程式檔開頭，**必須建立模組 logger**（由 `code-review-guard` 的 `[Logging]` 擋缺漏）。
   - Python: `logger = logging.getLogger(__name__)`
   - Node: `const logger = createLogger("services/x")`
   - 網頁前端: `const logger = createLogger("app")`
   - 只有 `entrypoints` 可以 `print`（終端機面向使用者的輸出），其他各層一律使用 logger。
2. **分級記錄時機**：
   - `INFO`：批次/任務開始與結束、重要外部呼叫（耗時、結果）。
   - `WARNING`：可繼續運行但異常的情境（重試、降級、跳過檔案存入 needs_review）。
   - `ERROR`：未預期錯誤，一律使用 `logger.exception(...)` 附帶 traceback，絕不靜默吞掉。
   - `DEBUG`：內部計算細節、中間狀態值。
3. **禁止記錄**：API Key、Secret Token、密碼與未脫敏個人隱私資料。

---

## 3. Karpathy 四原則（防範 LLM 常見通病）

1. **Think Before Coding（動手前先思考）**：需求模糊或有衝突時，先列出假設與架構取捨詢問使用者，絕不私自盲猜。
2. **Simplicity First（簡單至上）**：只寫解決當前問題所需的最少程式碼；嚴禁為了想像中的「未來擴展」過度抽象。
3. **Surgical Changes（精準微創）**：只修改必須改動之處；嚴禁順手重排、改名或刪除既有註解與不相關程式碼。
4. **Goal-Driven Execution（目標驅動驗收）**：先定義可驗證的成功標準（測試或指令），反覆修正直到客觀實證通過，才回報完成。
