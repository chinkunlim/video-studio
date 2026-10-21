# 核心程式設計準則 (Coding Principles: 註解規範、Karpathy 原則、SOLID、DRY、Atomic)

> **AI Agent 載入時機**：當準備在專案原始碼目錄 (`src/` 等) 或 `test/` 撰寫、修改或重構任何程式碼時，**必須閱讀並遵守本文件**。具體量化門檻與分層定義於 [`.agents/project.toml`](../../.agents/project.toml)。

---

## 0. 註解規範（必須遵守，`code-review-guard` 與 pre-commit 會自動檢查）

**目的**：任何人（或下一個 Agent）只讀註解，就知道這個檔案做什麼、每個函數做什麼、每個參數代表什麼。

| 項目 | 規則 |
|---|---|
| 檔案開頭 | 說明此檔案的**用途**；較大的模組再加「主要功能」與「用法」 |
| 每個函數 / 方法 / 類別 | 一句話說明**做什麼**（不是怎麼做） |
| 每個參數 | 名稱 + 意義（必要時含型別、單位、允許值、預設行為） |
| 回傳值 | 回傳什麼；沒有回傳值可省略 |
| 例外 | 會主動拋出的例外與條件 |
| 行內註解 | 只寫「為什麼」（非直覺的取捨、外部限制、相關 ADR/ISSUE 編號），不要逐行翻譯程式碼 |

### Python（Google style docstring）

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

### JavaScript / TypeScript / Google Apps Script（JSDoc）

```js
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

### HTML / CSS

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

### Go / Rust

- Go：檔案開頭 `// Package xxx ...`；每個函數上方 `// FuncName does ...`，參數寫在同一段註解中。
- Rust：檔案開頭 `//! ...`；每個函數上方 `/// ...`，參數用 `/// * \`name\` - 說明`。

### 自動檢查內容
- Python：模組 docstring、每個函數/類別 docstring、每個參數在 docstring 中以 `name:` 出現。
- JS/TS：檔案開頭註解、每個函數上方 `/** */`，且 `@param` 數量不少於參數數量。
- Go/Rust：檔案開頭註解、每個函數上方 `//` / `///` 註解。
- HTML：`<!DOCTYPE>` 之後第一個內容是 `<!-- 用途 -->`；CSS/SCSS：開頭是 `/* 用途 */`。
- Python 型別：每個函數參數與回傳值都要有型別註記；`agentctl check` 會以 `mypy --strict`（`[commands] typecheck`）檢查 `src/`。
- 測試檔（`test_*.py`、`*.test.js`、`*_test.go`、`tests/` 內）不強制，但建議每個測試寫一句「驗證什麼」。
- 可在 `.agents/project.toml` 以 `[quality] require_docstrings = false` 暫時關閉（不建議）。

---

## 0.4 Log 紀錄規範（方便追蹤與除錯）

程式出問題時，第一個看的是 log。Python 專案的 `config/logging_setup.py` 已經設定好格式與檔案，**寫程式時只要照下面做**：

1. **每個模組一個 logger**：`logger = logging.getLogger(__name__)`。只有 `entrypoints` 可以 `print`（CLI 給使用者看的結果），其他層一律用 logger（`code-review-guard` 會擋 `[Logging]`，可用 `[quality] print_allowed_layers` 調整）。
2. **要記什麼**：
   | 時機 | 等級 | 例子 |
   |---|---|---|
   | 一次執行 / 一個請求 / 一批工作的開始與結束（含筆數、耗時） | INFO | `logger.info("batch done files=%d ok=%d failed=%d (%.1fs)", ...)` |
   | 每次外部呼叫（API、資料庫、檔案、模型）：對象、結果、耗時、重試 | INFO / DEBUG | `logger.info("ollama model=%s status=%s (%.0f ms)", ...)` |
   | 可以繼續、但不正常的狀況（重試、跳過、放進 needs_review） | WARNING | `logger.warning("skip %s: %s", path.name, reason)` |
   | 失敗：在處理例外的地方用 `logger.exception(...)`（會附 traceback），不要吞掉例外 | ERROR | `logger.exception("convert failed file=%s", path.name)` |
   | 除錯細節（中間值、分支） | DEBUG | `.env` 設 `LOG_LEVEL=DEBUG` 才會出現 |
3. **寫法**：用 `%s` 參數（`logger.info("user=%s", uid)`），不要先組字串；訊息寫「發生什麼 + 關鍵 id」，讓一行就看得懂。
4. **不能記**：API key、token、密碼、完整個資；檔案內容只記檔名與大小。
5. **去哪裡看**：
   - 主控台（stderr）：每行有時間、等級、`[run id]`、`模組:函式:行號`。
   - `DATA_DIR/logs/app.log`（全部）與 `errors.log`（WARNING 以上），自動輪替；`.env` 的 `LOG_TO_FILE=false` 可關閉。
   - 追蹤某一次執行或某個 API 請求：`grep <run id> app.log`；API 回應的 `X-Request-ID` 就是那個 id。
   - 沒被接住的例外也會連同 traceback 寫進 log。
6. **JS / GAS**：用 `console.info / warn / error`，訊息格式同上（事件 + 關鍵 id + 結果）；GAS 的紀錄在 Apps Script「執行作業」頁查看，不要用 `Logger.log` 混用。

---

## 0.5 Karpathy 四原則（避免 LLM 常見通病）

1. **Think Before Coding**：需求模糊時先列出假設與取捨並詢問，不要默默猜。
2. **Simplicity First**：只寫解決問題所需的最少程式碼；不寫「未來可能用到」的抽象與設定。
3. **Surgical Changes**：只改必須改的地方；不順手重排、改名或刪除無關的程式碼與既有註解（`review_guard` 會在 diff 刪除大量註解時警告）。自己這次產生的廢棄程式碼要清乾淨。
4. **Goal-Driven Execution**：先定義可驗證的成功標準（測試或指令），反覆修正直到通過才回報完成。

---

## 1. SOLID 原則實戰規範（跨語言通用）

| 原則 | 在本框架的具體實踐要求 | ❌ 禁止的反模式 (Anti-Patterns) |
|---|---|---|
| **S — 單一職責 (Single Responsibility)** | 每個檔案、類別與函式只有一個修改理由：<br>• `entrypoints`：驗證輸入、組裝依賴、輸出結果<br>• `adapters`：外部 API、資料庫、檔案與硬體 I/O，轉成 domain 物件<br>• `services`：業務流程與規則<br>• `domain`：資料型別與領域錯誤<br>• `config`：設定與 logging | 在外部 API Adapter 內直接拼湊 UI 畫面，或在 `services` 內直接讀取作業系統環境變數（`os.environ` / `process.env` / `os.Getenv`）。 |
| **O — 開放封閉 (Open/Closed)** | **對擴充開放、對修改封閉**。新增指令、策略、資料源或供應商時，透過註冊表（Registry / Map / Trait / Interface）擴充，不修改核心調度迴圈。 | 每次加一個新功能分支，就在主流程寫長串 `if / elif / else` 或 `switch`。 |
| **L — 里氏替換 (Liskov Substitution)** | 同一抽象介面（Port / Interface / Protocol / Trait）的所有實作（如主服務 vs. 備援服務、正式 `Store` vs. 測試 `FakeStore`）必須遵守完全相同的輸入契約、回傳 DTO 結構與標準例外型別。 | 某個實作失敗時回傳 `null`/`None`，另一個卻拋出未包裝的底層例外，導致呼叫端必須針對特定實作寫特例判斷。 |
| **I — 介面隔離 (Interface Segregation)** | 函式只接收完成任務所需的**最小參數集合**。純函式只傳入基本型別或小型結構，不傳入整份 `config`。 | 把整份 `config` 傳進單純的字串排版函式。 |
| **D — 依賴反轉 (Dependency Inversion)** | 高層業務模組不依賴低層外部細節，兩者皆依賴抽象介面（以參數注入的 adapter / repository 與 domain 物件）。這讓同一份業務邏輯可同時用在正式環境與離線單元測試。 | 在核心業務層頂層寫死特定第三方 SDK 或網路連線，導致無法在無網路環境下跑單元測試。 |

---

## 2. DRY (Don't Repeat Yourself) 與 SSOT (單一真相來源)

1. **單一設定來源 (Single Source of Truth)**：
   - 專案架構分層、品質門檻與業務成對規則統一由 `.agents/project.toml` 定義；應用程式執行期設定統一集中於 `config` 層，禁止在業務程式碼中散落 Magic Numbers 或硬編碼字串。
2. **禁止複製貼上邏輯 (Rule of Three)**：
   - 相同的資料清洗、解析、錯誤分類邏輯不可在多個檔案中重複出現；需要重複使用時抽取成共用函式（放在使用它的最低那一層，通常是 `domain` 或 `services`）。
3. **跨 AI Agent 規則不重複維護**：
   - 全專案只手寫維護 `AGENTS.md` 與 `.agents/project.toml`；`CLAUDE.md`、`GEMINI.md`、`.github/copilot-instructions.md`、`.cursor/rules/` 由 `python3 scripts/agentctl.py sync` 自動同步產生。

---

## 3. OOP (物件導向) 與 FP (純函式) 混合設計

1. **何時使用 OOP / Struct + Interface（邊界與狀態封裝）**：
   - **資料傳輸物件 (DTO / Value Objects)**：使用不可變結構（Python `@dataclass(frozen=True)`、TypeScript `readonly interface`、Go/Rust struct）表達跨層傳遞的資料。
   - **外部資源與狀態邊界 (`adapters`)**：封裝需要連線池、API 金鑰、session 或並發鎖的物件。
   - **組合優於繼承 (Composition over Inheritance)**：嚴禁超過 **2 層** 的類別繼承樹；優先透過注入協作者或策略函式組合行為。
2. **何時使用 Pure Functions（核心計算與轉換）**：
   - 資料轉換、關鍵字處理、格式排版、規則校驗一律寫成**零副作用 (Side-effect free)、相同輸入必得相同輸出**的純函式。

---

## 4. 模組化 (Modularity：高內聚、低耦合)

1. **嚴格單向依賴鏈**：
   - 依賴順序由 `.agents/project.toml` 的 `[architecture] layers` 定義（預設：`entrypoints ➔ adapters ➔ services ➔ domain ➔ config`）。
   - 下層模組**絕對禁止**逆向引用上層模組，禁止循環依賴（由 `agentctl check` / `agentctl graph` 自動檢查）。
2. **明確的公開介面與私有封裝**：
   - 模組內部輔助函式必須標記為私有（Python `_helper()`、JS/TS 不匯出、Go 小寫開頭、Rust 無 `pub`），禁止跨模組直接呼叫私有實作。

---

## 5. Atomic 原子化原則（函式、狀態、Git 三維度）

### 5.1 Atomic Functions (原子化函式 — 門檻可於 `.agents/project.toml` `[quality]` 調整)
- **一個函式只做一件事**，且函式內的所有語句維持在同一抽象層級。
- **預設量化指標**（由 `review_guard.py` 支援 Python / JS / TS / Go / Rust 自動檢查）：
  - 單一函式目標 **$\le 40$ 行**（新專案的 `max_function_lines = 40`，超過是警告；硬上限 `hard_max_function_lines = 80`，超過會擋 commit）。
  - 函式參數 **$\le 4$ 個**（`max_params = 4`，超過時封裝為 DTO / Options 結構）。
  - 縮排層級 **$\le 3$ 層**（`max_nesting = 3`，優先使用 **Guard Clauses / Early Return**）。

### 5.2 Atomic State Operations (原子化狀態與補償操作)
- **狀態變更與外部副作用不可留半套狀態**：若先扣減資源、預留庫存或開啟交易，當後續外部呼叫失敗時，必須在錯誤處理區塊執行對應的補償或回滾函式（各專案可於 `.agents/project.toml` 的 `[project_rules] paired_calls` 設定專屬的成對函式檢查）。
- **並發鎖原子區間最小化**：`Lock` 只包住記憶體或本地儲存的 `Read ➔ Modify ➔ Write`，並在 `finally` / `defer` 中保證釋放鎖；**嚴禁在持有鎖期間執行外部網路請求**。

### 5.3 Atomic Commits (原子化的 Local Git 提交)
- 每次透過 `python3 scripts/agentctl.py commit` 提交的變更必須是**單一邏輯單元**，且能獨立通過離線測試。
- 只想提交部分檔案時，使用 `--task TASK-NNN`（任務卡的 paths）或 `--paths <dir>`。
