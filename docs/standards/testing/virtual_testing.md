# 4 層虛擬測試體系與樣本驅動測試 (Virtual Testing & Fixture-Driven Standards)

> **任務載入時機**：撰寫單元測試、整合測試、設計測試樣本或驗證功能時必讀。

---

## 1. 4 層虛擬測試體系

為確保各類應用在離線環境下均能進行出版級防錯驗證，測試分為 4 個層次：

| 層級 | 測試類型 | 存放路徑 | 網路連線 | 驗證重點 |
|---|---|---|---|---|
| **1** | **軟體單元測試** | `tests/test_<模組>.py` | **零網路**（純記憶體） | `services`、`domain` 純邏輯；`config` 驗證；`adapters` 解析函式 |
| **2** | **Dummy 樣本測試** | `tests/fixtures/` | **零網路**（靜態假資料） | 極端字元、畸形結構、超長字串、容錯邊界與防崩潰測試 |
| **3** | **虛擬使用者測試** | `tests/integration/` | **零網路**（記憶體 DB/假用戶端）| 模擬 Dummy 使用者完整 User Journey，跨模組狀態切換與流程一致性 |
| **4** | **Web 元件全量走測**| `tests/web/` 或 E2E 腳本 | **本機 127.0.0.1** | 遍歷 Web App 每一個按鈕、表單與功能元件，杜絕死按鈕與佈局破版 |
| **E2E**| **端對端整合** | `tests/e2e/`（預設略過） | **真實網路與外部服務** | 發布前或手動執行，驗證真實外部 API 與金鑰連線 |

---

## 2. 靜態樣本驅動測試 (Fixture-Driven Testing)

1. **解析邏輯絕不連網**：單元測試驗證外部網頁或 API 解析時，一律讀取 `tests/fixtures/` 中的樣本檔。
2. **樣本脫敏**：存入 `fixtures/` 的樣本檔必須去除真實 API 金鑰與個資，單檔大小不超過 1 MB。
3. **外部格式改版應對流程**：
   - 先建立 `docs/known-issues/NNN-xxx.md` 記錄變更點與根因。
   - 將新版回應樣本放入 `tests/fixtures/`。
   - 更新解析函式，並補上防回歸單元測試。

---

## 3. 契約測試、Protocol 模擬與系統路徑硬隔離

1. **靜態契約自動測試 (`tests/test_web_contracts.py`)**：
   - **DOM ID 一致性**：自動比對 `web/*.js` 中的 `getElementById(...)` 與 `web/index.html`（及 JS 動態建立之 `.id`），0.1 秒離線攔截死按鈕。
   - **OpenAPI 路由契約（`--with api --with web`）**：靜態掃描前端 `fetch()` / `apiFetch()` 呼叫路徑，比對 `app.openapi()["paths"]`，杜絕 404 假路徑。
2. **Protocol 介面 + 零網路全流程 E2E 測試**：
   - 在 `domain/protocols.py` 定義抽象 `Protocol`，測試以單一 `DummyClient` + 記憶體 `sqlite://` + `FastAPI TestClient` 執行零網路端到端使用者旅程。
3. **系統路徑測試硬隔離 (`safe_user_path`)**：
   - 所有寫入使用者系統目錄（如 `~/Desktop`、`~/.config/`）的功能，須透過 `entrypoints/wiring.py` 的 `safe_user_path()` 解析；當 `APP_ENV=test` 時自動隔離導向 `DATA_DIR/_test_isolated/`，嚴禁單元測試污染開發者本機目錄。
