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
