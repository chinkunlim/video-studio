# 一鍵安裝與後期平滑更新規範 (One-Click Installation & Lifecycle Updates)

> **任務載入時機**：專案環境初始化、封裝發布、編寫安裝腳本、規劃部署與更新流程時必讀。

---

## 1. 核心原則：使用者極簡、零手動除錯

軟體交付與發布的最高品質標準是：**使用者無需手動執行繁複指令，即可一鍵完成安裝並啟動；後續升級時也能平滑過渡，既有資料與設定不丟失**。

1. **一鍵安裝 (Zero-Friction Install)**：
   - 提供專屬的一鍵啟動/安裝腳本（如 `./install.sh`、`python3 scripts/agentctl.py setup` 或 Makefile 整合入口）。
   - 封裝所有前置作業，使用者只需單一步驟即可使專案進入可運行狀態。
2. **平滑更新 (Seamless In-Place Upgrade)**：
   - 升級時不得覆蓋使用者的客製化設定與業務資料。
   - 資料庫變更必須支援自動向下相容遷移（Schema Evolution）。

---

## 2. 一鍵安裝實作標準清單

安裝腳本或初始化流程必須自動依序完成以下動作：

1. **執行環境自檢**：
   - 檢查系統必要前置工具（如 Python 3.11+、Node 20+、uv、pnpm、Git、Homebrew）。
   - 若缺少依賴，給出具體友善的安裝建議或自動引導。
2. **依賴環境隔離安裝**：
   - 使用鎖定檔安裝，確保跨主機重現性：
     - Python：`uv sync --frozen`
     - Node：`pnpm install --frozen-lockfile`
   - 嚴禁污染主機全域環境。
3. **設定檔自動防呆建立**：
   - 自動檢測 `.env` 是否存在；若無，自動複製 `.env.example` 為 `.env`。
   - 若包含必要第三方 API 金鑰，提示使用者填寫並指示安全設定。
4. **外部資料目錄與日誌初始化**：
   - 自動呼叫 `python3 scripts/agentctl.py doctor --fix` 建立 `DATA_DIR` 的標準子資料夾（`input/`、`output/`、`logs/`、`db/`、`state/`）。
5. **資料庫結構遷移**：
   - 若專案啟用資料庫（`--with db`），自動執行遷移至最新版本（例如 `uv run alembic upgrade head`）。
6. **安裝自檢與啟動指引**：
   - 執行基本健康檢查（如 `python3 scripts/agentctl.py check`），輸出明確的成功啟動方式（如 Web UI、CLI 或 MCP 伺服器網址）。

---

## 3. 後期平滑更新守則 (Post-Launch Update Strategy)

在進行版本升級或維護時，必須保證既有使用者的平滑升級：

1. **資料與設定防覆蓋保護 (Data & Config Guard)**：
   - 升級腳本（如 `python3 scripts/agentctl.py update`）嚴禁覆蓋或重設 `.env`。
   - 嚴禁動用或清空 `DATA_DIR` 內的使用者檔案、日誌與 SQLite 資料庫。
2. **資料庫遷移向下相容**：
   - 所有資料庫結構調整必須透過 Alembic 產生新遷移檔。
   - 新增欄位需具備預設值或允許 NULL，禁止粗暴重建表格導致歷史資料遺失。
3. **依賴更新同步**：
   - 代碼拉取（`git pull`）後，自動執行 `uv sync` / `pnpm install` 更新依賴鎖定。
4. **說明文件登記**：
   - 在專案根目錄 `README.md` 的「安裝與快速上手」段落，必須同時列出：
     - **【全新安裝】**：一鍵安裝指令。
     - **【後期更新】**：一鍵升級與遷移指令。
