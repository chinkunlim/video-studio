# AGENTS.md — video-studio

> AI-assisted software project with standard structure and agent handoff.
>
> 本檔與 [`.agents/project.toml`](.agents/project.toml) 是所有 AI Agent（Claude Code、Gemini/Antigravity、Cursor、Windsurf、Copilot、Codex）的**唯一規則來源**。`CLAUDE.md`、`GEMINI.md` 等入口檔由 `python3 scripts/agentctl.py sync` 自動產生，請勿直接修改。

<!-- RULES_START -->
## 1. 使用者說什麼 → 執行什麼

能用指令完成的事，Agent **直接執行並貼出結果**，不要只叫使用者自己去跑。

| 使用者說 | 執行 |
|---|---|
| 「開工」「接手」「繼續上次的」（每次對話開始也要先跑） | `python3 scripts/agentctl.py status` |
| 「新工作 / 新功能」 | `python3 scripts/agentctl.py task create "標題" --agent <你的名字>` |
| 「接手 TASK-NNN」 | `python3 scripts/agentctl.py task claim TASK-NNN --agent <你的名字>` |
| 「檢查一下」「跑測試」 | `python3 scripts/agentctl.py check`，再跑 `[commands] test` |
| 「存檔」「commit」 | `python3 scripts/agentctl.py commit --agent <名字> --model <模型>`（訊息用英文） |
| 「去上課」「先暫停」「等一下回來」 | `python3 scripts/agentctl.py pause "<English reason>"` |
| 「換人做」「交給 Cursor」 | `python3 scripts/agentctl.py task handoff TASK-NNN --to <agent> --done-items ... --todo-items ...` |
| 「結束對話」「收工」「今天先這樣」 | `python3 scripts/agentctl.py closeout --agent <名字> --goal ... --decisions ... --issues ... --next ...` |
| 「推上去」 | 先列出未推送的 commit 並**確認**，同意後才 `agentctl commit --push` |
| 「出版本」「專案完成了」 | `python3 scripts/agentctl.py finish`（驗收清單）；要發布再加 `--tag`（Unreleased → 新版本 + 本機 tag） |
| 「做一個網頁」「給 Open WebUI / Ollama / Agent 用」 | **先依 [`LOCAL_AI_ENVIRONMENT.md`](docs/standards/LOCAL_AI_ENVIRONMENT.md) §2 確認需求**並請使用者確認摘要，再做 FastAPI + MCP（核心規則 13）；專案沒有 `api` 時先問使用者 |
| 「環境怪怪的」「換電腦了」 | `python3 scripts/agentctl.py doctor --fix` |

## 2. 核心規則（必須遵守）

1. **完整註解**：每個程式檔開頭寫用途；每個函數/類別寫功能、每個參數（`Args:` / `@param`）與回傳值（格式見 [`CODING_PRINCIPLES.md`](docs/standards/CODING_PRINCIPLES.md) §0，pre-commit 會擋缺漏）。
2. **出示執行證據**：不能只說「已修復 / 完成」，要貼出測試或指令的實際輸出。
3. **決策衝突要停下來問**：動手前先看 `docs/adr/` 中狀態為 Accepted 的決策；使用者的指令或你的做法和它衝突時，暫停並詢問，不要自行改掉。
4. **即時記錄，不要等到最後**：遇到錯誤並找到根因 → 立刻寫 known-issue；做了架構取捨 → 立刻寫 ADR（用 `adr-issue-tracker`）。同樣的錯不能犯第二次。
5. **秘密不進程式碼**：API key / token 只放 `.env`，只在 `config` 層讀取；憑證檔放 `~/.config/<專案>/`（權限 600）。
6. **資料和程式分開**：輸入、輸出、資料庫、log 都在 `.env` 的 `DATA_DIR`（專案資料夾之外）；程式透過 config 取得路徑，專案內只放程式、文件和小型測試樣本。
7. **單向分層**：依 `.agents/project.toml` 的 `[architecture] layers`，上層可依賴下層，反之禁止。
8. **環境隔離（不污染主機）**：Python 只用 `uv add` / `uv run`，Node 只用 `pnpm add` / `pnpm exec`；禁止 `pip install`、`npm`、`npx`、全域安裝與 `sudo`（見 [`ENVIRONMENT_AND_DEPENDENCIES.md`](docs/standards/ENVIRONMENT_AND_DEPENDENCIES.md)）。
9. **本機服務只綁 `127.0.0.1`**：網址寫 `http://127.0.0.1:<port>`，不寫 `localhost`、不綁 `0.0.0.0`。
10. **Git**：完成一個可通過測試的修改就用 `agentctl commit`；訊息一律英文；未經使用者明確同意不得 push（見 [`GIT_AND_VERSIONING.md`](docs/standards/GIT_AND_VERSIONING.md)）。
11. **通用規則回寫母版**：使用者提出「以後每個專案都要這樣」的規則時，寫進 [`docs/TEMPLATE_FEEDBACK.md`](docs/TEMPLATE_FEEDBACK.md)，由使用者決定是否更新專案模板；只適用本專案的規則寫進 [`PROJECT_RULES.md`](docs/standards/PROJECT_RULES.md)。
12. **Log 追蹤**：執行的開始與結束、外部呼叫、跳過與重試、例外都要記 log，不記秘密與個資。Python 每個模組用 `logger = logging.getLogger(__name__)`，只有 entrypoints 可 `print`，log 檔在 `DATA_DIR/logs/`，用 run id 追蹤一次執行（見 [`CODING_PRINCIPLES.md`](docs/standards/CODING_PRINCIPLES.md) §0.4）。
13. **網頁一定要能給 AI 工具用**：使用者要網頁、API，或要讓 Open WebUI / Ollama / 其他 Agent 使用時，先依 [`LOCAL_AI_ENVIRONMENT.md`](docs/standards/LOCAL_AI_ENVIRONMENT.md) §2 的清單確認需求（誰用、哪些動作會改資料、接哪些工具、要不要本機模型、資料、介面、啟動方式、埠號、驗收），整理成摘要請使用者確認；再一律用 FastAPI（`--with api`），不要做單純的網頁。同一組 `services` 由三個入口呼叫：HTTP 路由（OpenAPI 給 Open WebUI）、MCP 工具（`entrypoints/mcp_server.py`，給 Claude Code、Antigravity、OpenCode、Cursor、Open WebUI）與網頁。新增功能時三個入口一起接；會修改或刪除資料的 MCP 工具要有 `confirm` 參數。
<!-- RULES_END -->

## 2.5 Agent 分工（選填，由使用者維護）

| Agent / 工具 | 負責 | 不負責 |
|---|---|---|
| （例）Claude Code | 後端、測試、重構 | UI 視覺設計 |
| （例）Antigravity | 前端、文件 | 資料庫結構變更 |

## 3. 文件放哪裡（Docs Map）

| 內容 | 位置 | 產生方式 |
|---|---|---|
| 交接看板、任務卡 | `.agents/handoff/LATEST.md`、`.agents/tasks/TASK-NNN-*.json` | `agentctl task` / `closeout` |
| 每次對話的逐字稿＋摘要（目標、決策、錯誤根因、下一步） | `.agents/conversations/YYYY-MM-DD-HHMM-<agent>-{transcript,summary}.md`（本機，不進 git） | `agentctl closeout` 產生，Agent 補完摘要 |
| 架構決策 | `docs/adr/NNN-*.md`（總表 `DECISIONS.md`） | `adr-issue-tracker` |
| 已知問題與根因 | `docs/known-issues/NNN-*.md`（總表 `KNOWN_ISSUES.md`） | `adr-issue-tracker` |
| 需求與規格 | `docs/specs/NNN-*.md`（清單 `SPECS.md`） | 手動，照 `_TEMPLATE.md` |
| 系統架構總覽、目錄樹 | `docs/architecture/ARCHITECTURE.md`、`PROJECT_TREE.md` | 手動 / 自動 |
| 版本變更 | `CHANGELOG.md` | commit 寫入 Unreleased；`finish --tag` 發布 |
| 設定 / 環境變數範本 | `.agents/project.toml` / `.env.example` | 手動 |
| 資料（輸入、輸出、資料庫、log） | `.env` 的 `DATA_DIR`（專案資料夾之外） | 程式執行時產生 |
| 給專案模板的改進建議 | `docs/TEMPLATE_FEEDBACK.md` | Agent 記錄，使用者決定 |

**命名規則**：整個專案只有根目錄一份 `README.md`；每個 `docs/` 子資料夾用全大寫的說明/總表檔（如 `KNOWN_ISSUES.md`），新增紀錄時照同資料夾的 `_TEMPLATE.md` 格式寫。

## 4. 規範文件（需要時再讀）

| 文件 | 何時讀 |
|---|---|
| [`CODING_PRINCIPLES.md`](docs/standards/CODING_PRINCIPLES.md) | 寫或重構程式前（含註解規範） |
| [`ARCHITECTURE_RULES.md`](docs/standards/ARCHITECTURE_RULES.md) | 新增模組、調整 import 或分層時 |
| [`MULTI_AGENT_COLLABORATION.md`](docs/standards/MULTI_AGENT_COLLABORATION.md) | 接手、交接、收尾時 |
| [`TESTING_AND_QUALITY.md`](docs/standards/TESTING_AND_QUALITY.md) | 寫測試、錯誤處理時 |
| [`GIT_AND_VERSIONING.md`](docs/standards/GIT_AND_VERSIONING.md) | commit、發版時 |
| [`LOCAL_AI_ENVIRONMENT.md`](docs/standards/LOCAL_AI_ENVIRONMENT.md) | 使用者要網頁 / API / 給 AI 工具用、要接 Ollama 或 Open WebUI、排除 AI 工具連線問題時（這台電腦的 AI 工具、埠號、需求確認清單） |
| [`ENVIRONMENT_AND_DEPENDENCIES.md`](docs/standards/ENVIRONMENT_AND_DEPENDENCIES.md) | 安裝/移除套件、執行工具、設定本機服務前（uv、pnpm、Brewfile、DATA_DIR、127.0.0.1） |
| [`PROJECT_RULES.md`](docs/standards/PROJECT_RULES.md) | **每次開工都讀**：本專案特有的規則（領域知識、例外、禁忌） |

## 5. 可用 Skills

<!-- SKILLS_START -->
| Skill | 何時使用 | 指令 |
|---|---|---|
| `adr-issue-tracker` | 做出架構取捨、或發現需記錄的 bug/坑時 | `python3 .agents/skills/adr-issue-tracker/scripts/tracker_cli.py --add-adr <slug> --title <標題>` |
| `api-adapter-scaffold` | 串接新的外部 API / 服務時 | `python3 .agents/skills/api-adapter-scaffold/scripts/scaffold_adapter.py` |
| `code-review-guard` | 寫完或重構程式碼後、commit 前 | `python3 .agents/skills/code-review-guard/scripts/review_guard.py` |
| `legacy-migration` | 專案有 docs/migration/MIGRATION.md，要繼續或完成舊專案遷移時 | `python3 scripts/agentctl.py migration [--verify]` |
| `session-closeout` | 使用者說「結束對話 / 收工 / wrap up」時 | `python3 scripts/agentctl.py closeout --agent <name> --goal ... --issues ... --next ...` |
| `tdd-bugfix` | 實作新功能或修 bug 時（先寫失敗測試） | `python3 .agents/skills/tdd-bugfix/scripts/tdd_runner.py` |

詳細步驟：`.agents/skills/<skill>/SKILL.md`
<!-- SKILLS_END -->

## 6. 目錄結構摘要

> 只列資料夾；含檔案的完整樹在 [`docs/architecture/PROJECT_TREE.md`](docs/architecture/PROJECT_TREE.md)。框架腳本在 `.agents/bin/`，`scripts/` 留給本專案自己的腳本。

<!-- TREE_START -->
```text
video-studio/
├── .agents/                                # 【AI Agent 框架層】專案設定、共用函式庫、Skills、任務卡與交接紀錄
│   ├── bin/                                # [框架腳本] commit、任務、收尾、doctor、update…（由 agentctl 呼叫）
│   ├── handoff/                            # [交接紀錄] 頂部即時狀態看板 + 歷史交接時間軸，開工前必讀
│   ├── hooks/                              # [版本控管的 git hooks] 由 core.hooksPath 啟用（pre-commit、pre-push）
│   ├── lib/                                # 框架共用 Python 函式庫 (設定載入、目錄樹註解)
│   ├── skills/                             # 按任務觸發的模組化 Agent Skills (SKILL.md + scripts/*.py)
│   └── tasks/                              # [任務卡] 建立、接手、交接、完成 (agentctl task)
├── docs/                                   # 【工程知識庫】架構、規格、決策、已知問題、維運、規範
│   ├── adr/                                # [架構決策庫] 一決定一檔案
│   ├── architecture/                       # [系統架構與資料模型]
│   ├── known-issues/                       # [已知問題庫] 一問題一檔案
│   ├── migration/                          # [遷移紀錄] 舊專案搬移清單、批次與完成標準
│   ├── specs/                              # [功能規格書] PRD / API Contract
│   └── standards/                          # [工程規範] 依任務載入 (Progressive Disclosure)
├── scripts/                                # 【專案腳本】agentctl.py 是框架的單一入口；其餘放本專案自己的腳本
├── src/                                    # 【核心原始碼層】分層與依賴方向定義於 .agents/project.toml
│   └── video_studio/
├── templates/
│   ├── dub/
│   ├── extract/
│   ├── generate/
│   └── shared/
└── tests/                                  # 【測試層】單元與整合測試
```
<!-- TREE_END -->
