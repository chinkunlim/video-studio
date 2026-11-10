# 工程標準與規範總目錄 (Engineering Standards & Guidelines)

> 本目錄收錄所有由專案範本統籌之軟體工程準則、架構規範與品質驗收手冊。
>
> 為了防範 AI Agent 一次載入過多規範文件造成記憶混亂與 Token 浪費，所有規範採**漸進揭露架構 (Progressive Disclosure)**，依據當前工作任務精確載入對應子模組。

---

## 任務導向規範索引 (Task-Based Navigation)

| 任務領域 | 核心子模組 | 內容重點 | 完整母檔參照 |
|---|---|---|---|
| **程式碼註解與可觀測性** | [`coding/comments.md`](coding/comments.md) | 函式開頭用途、參數說明、Logger 規範、Karpathy 4 原則 | [`CODING_PRINCIPLES.md`](CODING_PRINCIPLES.md) §0 |
| **軟體設計與原子化** | [`coding/principles.md`](coding/principles.md) | SOLID、DRY、FP/OOP 混合、Atomic 門檻 | [`CODING_PRINCIPLES.md`](CODING_PRINCIPLES.md) §1-§5.3 |
| **資料寫入防護** | [`coding/data_guard.md`](coding/data_guard.md) | 格式與內容嚴格隔離、字元級零刪字稽核、指紋校驗 | [`CODING_PRINCIPLES.md`](CODING_PRINCIPLES.md) §5.4 |
| **系統架構分層** | [`architecture/layers.md`](architecture/layers.md) | 單向分層依賴（entrypoints ➔ adapters ➔ services ➔ domain ➔ config）、10 大工程守則 | [`ARCHITECTURE_RULES.md`](ARCHITECTURE_RULES.md) §1-§2 |
| **流程對齊與圖譜純淨** | [`architecture/workflow_parity.md`](architecture/workflow_parity.md) | 使用者視角端到端流程一致性、.graphifyignore 純淨圖譜 | [`ARCHITECTURE_RULES.md`](ARCHITECTURE_RULES.md) 守則 11-12 |
| **Web API 與 MCP 整合** | [`web/fastapi_mcp.md`](web/fastapi_mcp.md) | FastAPI 結構、OpenAPI 三重記錄、MCP confirm 機制 | [`ARCHITECTURE_RULES.md`](ARCHITECTURE_RULES.md) §3-§4 |
| **前端品味與原型審批** | [`web/taste_design.md`](web/taste_design.md) | Step 0 前置審批關卡、受眾心理學分析、Design Dials | - |
| **虛擬測試體系** | [`testing/virtual_testing.md`](testing/virtual_testing.md) | 4 層虛擬測試（單元、Dummy 樣本、虛擬使用者、Web 走測） | [`TESTING_AND_QUALITY.md`](TESTING_AND_QUALITY.md) §1-§2 |
| **實證檢驗與完成定義** | [`testing/empirical_evidence.md`](testing/empirical_evidence.md) | 實證檢驗鐵律（Snapshot/Log/Pilot）、DoD 清單 | [`TESTING_AND_QUALITY.md`](TESTING_AND_QUALITY.md) §1.1, §3 |
| **資料目錄規劃** | [`env/data_dir_layout.md`](env/data_dir_layout.md) | DATA_DIR 資料程式分離、releases/章節/archive 隔離劃分 | [`ENVIRONMENT_AND_DEPENDENCIES.md`](ENVIRONMENT_AND_DEPENDENCIES.md) §7 |
| **iCloud 同步規範** | [`env/icloud_rules.md`](env/icloud_rules.md) | 當次明確授權、Output-only、集中存放 project-data/ | [`ENVIRONMENT_AND_DEPENDENCIES.md`](ENVIRONMENT_AND_DEPENDENCIES.md) §7 |
| **多 Agent 協作與收尾** | [`MULTI_AGENT_COLLABORATION.md`](MULTI_AGENT_COLLABORATION.md) | 冷啟動引導、交接看板、對話逐字稿與個人習慣沉澱 | - |
| **環境隔離與套件相依** | [`ENVIRONMENT_AND_DEPENDENCIES.md`](ENVIRONMENT_AND_DEPENDENCIES.md) | uv / pnpm 零主機污染、127.0.0.1 本機綁定、Brewfile | - |
| **Git 規範與版本控制** | [`GIT_AND_VERSIONING.md`](GIT_AND_VERSIONING.md) | 英文 Commit 訊息、未經同意不 push、語意化版本 | - |
| **本機 AI 環境** | [`LOCAL_AI_ENVIRONMENT.md`](LOCAL_AI_ENVIRONMENT.md) | Ollama、Open WebUI 本機埠號與需求確認清單 | - |
| **專案特有規則** | [`PROJECT_RULES.md`](PROJECT_RULES.md) | 本專案特有業務領域知識、例外與禁忌（開工必讀） | - |
