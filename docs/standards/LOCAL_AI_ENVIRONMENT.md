# 本機 AI 工具環境與網頁需求確認 (Local AI Environment)

> **AI Agent 載入時機**：使用者要「網頁 / 介面 / API / 給 Open WebUI 或其他 AI 用 / 接本機模型」時，**動手前必讀**；要串接、測試或排除 AI 工具連線問題時也要讀。
>
> 這台電腦的安裝步驟見 `00 init_dev_env` 的 macOS SOP；本文件記錄「裝了什麼、各自在哪裡、專案要怎麼接」。版本是寫入時的狀態，以下面的檢查指令為準。

---

## 1. 這台電腦的 AI 工具

| 工具 | 位置 / 埠號 | 安裝方式 | 專案怎麼接 |
|---|---|---|---|
| **Ollama**（qwen2.5 對話、bge-m3 向量） | `http://127.0.0.1:11434` | `brew install --cask ollama` | 專案要用本機模型：`--with ollama`（硬體檢查、PromptRegistry） |
| **Open WebUI** | `http://127.0.0.1:8080`，**原生安裝、不是 Docker**，`launchd` 開機常駐 | `uv tool install open-webui` | OpenAPI 工具伺服器或 MCP（Streamable HTTP），見 §3 |
| **Claude Code**（本 App 的 Code 分頁）、**Claude Desktop** | — | App | MCP：專案根目錄 `.mcp.json`；Desktop 用自己的設定檔 |
| **Antigravity**（App + `agy` CLI） | — | App、官方腳本 | MCP：專案 `.agents/mcp_config.json`（CLI / IDE）；App 在 Settings → Customizations |
| **OpenCode v2**（CLI + 桌面版） | 背景服務 | `brew install anomalyco/tap/opencode-v2` | MCP：專案 `opencode.json`（`mcp → servers → 名稱`） |
| **Open Design** | `127.0.0.1:7456` | App | 透過 `agy` 呼叫工具 |
| （日後）Hermes Agent、OpenClaw | — | — | MCP，最低權限 |

檢查目前狀態（每行一個指令）：

```bash
curl -s http://127.0.0.1:11434/api/version
```

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080
```

```bash
uv tool list
```

```bash
opencode --version
```

```bash
agy --version
```

### 已知的環境陷阱

- **`DATA_DIR` 撞名**：Open WebUI 的安裝步驟在 `~/.zshrc` 加了 `export DATA_DIR="$HOME/open-webui-data"`。框架已處理：專案 `.env` 的 `DATA_DIR` 優先，`agentctl doctor` 會顯示忽略了哪個終端機設定。新的設定名稱不要再用 `DATA_DIR`、`PORT`、`HOST` 這類通用名稱。
- **埠號**：已占用 `8080`（Open WebUI）、`11434`（Ollama）、`7456`（Open Design）、`8765`（literature-fetch）、`8766`（母版網頁）。新專案的 `HTTP_PORT` 選一個沒人用的，並寫進 `docs/standards/PROJECT_RULES.md`，避免同時開兩個專案時衝突。
- **OpenCode v2 快取**：改了 `opencode.json` 後，第一次 `opencode mcp list` 可能顯示舊結果，再執行一次。
- **`agy mcp list` 只列全域設定**：專案的 `.agents/mcp_config.json` 要在專案資料夾內的對話中確認（問它有哪些 MCP 工具）。
- **桌面資料夾權限**：從「終端機」以外的程式啟動（例如某些預覽工具）讀不到 `~/Desktop` 時，到「系統設定 → 隱私權與安全性 → 檔案和資料夾」授權。

---

## 2. 使用者說「要網頁」時：先確認需求，不要直接做

使用者提到網頁、介面、API，或「讓 Open WebUI / Ollama / 其他 Agent 用」，**先用下面的清單問清楚、整理成摘要請使用者確認，再動手**。已經在對話或規格裡回答過的就不要再問；一次問完，不要一題一題拖。

| # | 要確認的事 | 為什麼要問 / 影響什麼 |
|---|---|---|
| 1 | **誰用、在哪裡用**：只有自己在這台 Mac？要不要在手機上看？ | 預設只綁 `127.0.0.1`；要手機 → `--with mobile` 或另外討論（不可改成 `0.0.0.0`） |
| 2 | **要做哪些動作**：列出每個功能，標出哪些只讀、哪些會**新增 / 修改 / 刪除**資料或檔案 | 決定 services 的函式與 MCP 工具；會改資料的工具要 `confirm` |
| 3 | **要給哪些 AI 工具用**：Open WebUI？Claude Code / Desktop？Antigravity？OpenCode？ | 預設全部都接（OpenAPI + MCP）；Open WebUI 選 MCP（管理員）或 OpenAPI 工具伺服器 |
| 4 | **要不要本機模型**：程式自己要呼叫 Ollama 嗎（摘要、分類、改寫…）？用哪個模型？ | 要 → `--with ollama`；只是讓 Open WebUI 的模型呼叫本專案 → 不需要 |
| 5 | **資料**：輸入從哪來、輸出放哪、要不要保存紀錄 / 查詢歷史？ | 檔案放 `DATA_DIR`；要查詢與歷史 → `--with db`（SQLite） |
| 6 | **介面**：要完整網頁，還是只要 API + MCP（讓 Agent 操作就好）？ | 要網頁 → `--with web`；只要給 Agent 用可省略 |
| 7 | **怎麼啟動**：需要時手動開，還是開機自動常駐？ | 常駐要另外寫 `launchd` 設定（參考 SOP §6.4），預設手動 |
| 8 | **埠號與名稱**：預設埠號是否與 §1 衝突？ | 寫進 `.env` 的 `HTTP_PORT` 與 `PROJECT_RULES.md` |
| 9 | **驗收**：怎樣算完成（例如「在 Open WebUI 問一句就能新增一筆」）？ | 寫成測試與 `docs/specs/` 規格 |

確認後：

1. 把答案整理成 `docs/specs/NNN-<名稱>.md`（照 `_TEMPLATE.md`），重要取捨寫 ADR。
2. 新專案：`python3 scripts/init_project.py --target <資料夾> --stack python --with api [web] [db] [ollama]`（或用母版網頁）。
3. 既有專案沒有 `api`：先問使用者，再依 [`ARCHITECTURE_RULES.md`](ARCHITECTURE_RULES.md) §3 加上 FastAPI、`entrypoints/mcp_server.py` 與各工具設定檔（參考新專案產生的檔案）。

---

## 3. 實作規則（摘要；完整規則見 ARCHITECTURE_RULES §3）

- **一組 services、三個入口**：HTTP 路由（OpenAPI）、MCP 工具（`entrypoints/mcp_server.py`）、網頁。功能只寫一次在 `services`。
- **讓工具找得到**：專案根目錄的 `.mcp.json`（Claude Code）、`opencode.json`（OpenCode v2）、`.agents/mcp_config.json`（Antigravity）、`.cursor/mcp.json`、`.vscode/mcp.json` 由框架產生；其他工具的步驟在 `docs/INTEGRATIONS.md`。
- **Open WebUI 原生安裝**（這台電腦）：
  - MCP（管理員）：⚙ 設定 → 管理員 → Integrations → External Tool Servers → MCP (Streamable HTTP)，URL `http://127.0.0.1:<HTTP_PORT>/mcp`，Auth 選 None。
  - OpenAPI 工具伺服器（一般使用者）：⚙ 設定 → Integrations → Tools → ➕，URL `http://127.0.0.1:<HTTP_PORT>`；由瀏覽器呼叫，`.env` 的 `HTTP_ALLOWED_ORIGINS` 要有 `http://127.0.0.1:8080`（預設已有）。
  - 對話時用支援工具呼叫的模型（例如 `qwen2.5`）。
- **最低權限**：讀取的工具可以直接呼叫；新增、修改、刪除、提交、部署要有 `confirm` 參數並經使用者同意（SOP 附錄 A）。
- **只在本機**：綁 `127.0.0.1`；Host 只接受 127.0.0.1 / localhost；網頁送出的修改請求只接受本專案與 `HTTP_ALLOWED_ORIGINS`。
- **不可信任的內容**：上傳到模型的文件與模型輸出一律視為不可信任；含金鑰、個資、私有原始碼的內容不要送到外部模型服務。
- **測試**：TestClient 測 API（含 Host / Origin 防護）、`mcp.Client(build_mcp_server(...))` 在記憶體中測 MCP 工具；接上真實工具後至少實際呼叫一次（例如 `opencode mcp list` 顯示 connected）。
