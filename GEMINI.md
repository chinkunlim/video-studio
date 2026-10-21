# GEMINI.md — video-studio

> ⚠️ 由 `python3 scripts/agentctl.py sync` 自動產生，請勿直接修改；請改 `AGENTS.md` 或 `.agents/project.toml`。

完整規則、文件地圖與規範索引在 [`AGENTS.md`](AGENTS.md)；設定在 [`.agents/project.toml`](.agents/project.toml)。
以下規則段落**直接取自 AGENTS.md**。

- **本專案分層（上 ➔ 下，下層不可 import 上層）**：`entrypoints ➔ adapters ➔ services ➔ domain ➔ config`
- **測試指令**：`uv run python -m unittest discover -s tests -v`

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

## Skills
| Skill | 何時使用 | 指令 |
|---|---|---|
| `adr-issue-tracker` | 做出架構取捨、或發現需記錄的 bug/坑時 | `python3 .agents/skills/adr-issue-tracker/scripts/tracker_cli.py --add-adr <slug> --title <標題>` |
| `api-adapter-scaffold` | 串接新的外部 API / 服務時 | `python3 .agents/skills/api-adapter-scaffold/scripts/scaffold_adapter.py` |
| `code-review-guard` | 寫完或重構程式碼後、commit 前 | `python3 .agents/skills/code-review-guard/scripts/review_guard.py` |
| `legacy-migration` | 專案有 docs/migration/MIGRATION.md，要繼續或完成舊專案遷移時 | `python3 scripts/agentctl.py migration [--verify]` |
| `session-closeout` | 使用者說「結束對話 / 收工 / wrap up」時 | `python3 scripts/agentctl.py closeout --agent <name> --goal ... --issues ... --next ...` |
| `tdd-bugfix` | 實作新功能或修 bug 時（先寫失敗測試） | `python3 .agents/skills/tdd-bugfix/scripts/tdd_runner.py` |

詳細步驟：`.agents/skills/<skill>/SKILL.md`
