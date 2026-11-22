# Web API、FastAPI 與 MCP 整合規範 (Web API, FastAPI & MCP Integration)

> **任務載入時機**：開發 Web 介面、HTTP 路由、FastAPI 服務或 MCP 工具時必讀。

---

## 1. 核心架構：一組 Services、三個入口

使用者要求網頁、API 或提供給 AI 工具使用時，**一律使用 FastAPI**（母版 `--with api`）。同一套業務邏輯只寫在 `services`，並由三個入口共同調用：

1. **HTTP 路由**：供 Web 前端與外部系統調用，自動產生 OpenAPI 規格。
2. **MCP 伺服器** (`entrypoints/mcp_server.py`)：供 Claude Code、Antigravity、OpenCode、Open WebUI 呼叫。
3. **網頁 UI**：使用者互動操作介面。

---

## 2. FastAPI 實作守則

1. **工廠模式**：路由由 `create_app(config, ...)` 組裝，禁止模組頂層全域宣告 `app = FastAPI()`。
2. **邊界驗證**：輸入輸出透過 Pydantic Schema（`entrypoints/schemas.py`）驗證，轉為 Domain 物件後才進入 Services。
3. **路由輕薄**：驗證 ➔ 調用 Service ➔ 回傳結果。業務邏輯嚴禁堆積在路由內部。
4. **本機綁定**：預設僅綁定 `127.0.0.1`，嚴禁綁定 `0.0.0.0`。
5. **OpenAPI 三重記錄**：
   - 代碼：宣告 `response_model`，欄位包含 `Field(description=...)`。
   - 介面：網頁導覽列需放置指向 `/docs` 的外部連結。
   - 文檔：在 `README.md` 與 `ARCHITECTURE.md` 登記規格網址。

---

## 3. MCP 伺服器實作守則

1. **雙協議支援**：
   - Streamable HTTP：掛載於 `/mcp`。
   - Stdio 模式：`uv run <name>-mcp` 供本地 Agent 工具串接。
2. **最低權限與確認機制 (Confirm Gate)**：
   - 唯讀工具（查詢、分析、預覽）可直接執行。
   - 會寫入、修改、刪除、提交或部署的工具，**必須包含 `confirm: bool = False` 參數**。若未獲明確確認，需拒絕執行並詳細回報預計變更範圍。
3. **Stdout 禁令**：
   - Stdio 模式下的 MCP 伺服器**絕對禁止直接 `print` 到 stdout**（stdout 為 JSON-RPC 通道），所有日誌一律走 Logger 寫入 stderr 或日誌檔。

---

## 4. FastAPI + DB 連線隔離、安全性、埠號預檢與入口拆分

1. **Request-Scoped DB Session 中介層（`--with api --with db` 內建）**：
   - 請求期間透過 `ContextVar`（`_DB_SCOPE`）綁定 `make_request_scoped_session`，並於 `add_db_session_scope` 中介層的 `finally` 自動呼叫 `registry.remove()` 歸還連線，根治執行緒池連線洩漏。
   - 背景 Worker、CLI 與 MCP stdio 另行使用獨立的 `with session_scope(factory):`，不混用 HTTP 請求級 session。
2. **本機 Web 安全與防快取三件套**：
   - `NoCacheStaticFiles`：所有靜態 HTML/CSS/JS 回傳 `Cache-Control: no-cache`，防止瀏覽器／Safari 延遲載入舊程式。
   - `add_local_only_guard`：驗證 `Host`（含 `HTTP_ALLOWED_HOSTS` 如 `host.docker.internal` 與 Tailscale 主機名，比對含埠或去埠主機名）與寫入請求之 `Origin`。
   - `safe_resolve_under(root, relative_path)`：所有下載與檔案輸出路由一律透過 `Path.resolve()` + `is_relative_to()` 阻斷 `../` 路徑穿越。
3. **啟動前埠號預檢 (`entrypoints/http/port_check.py`)**：
   - 啟動 `uvicorn` 前呼叫 `port_is_free(host, port)`（socket 啟用 `SO_REUSEADDR` 避免 `TIME_WAIT` 誤判）；若被佔用則以 `lsof` 顯示佔用行程 PID 並指引查詢 `~/Desktop/projects/00 init_dev_env/PORTS.md` 后安全停止。
4. **平行領域拆分**：當 `app.py` / `mcp_server.py` 隨業務增長接近 400–500 行時，主檔僅保留組裝根與 `lifespan`，業務路由拆入 `entrypoints/http/<domain>.py`（`APIRouter`）並對應 `entrypoints/mcp_<domain>.py`。
