# 專案完整檔案與資料夾結構樹 (PROJECT_TREE)

> ⚠️ 本檔案由 `python3 scripts/agentctl.py tree` 自動產生，請勿手動編輯。

```text
video-studio/
├── .agents/                                # 【AI Agent 框架層】專案設定、共用函式庫、Skills、任務卡與交接紀錄
│   ├── bin/                                # [框架腳本] commit、任務、收尾、doctor、update…（由 agentctl 呼叫）
│   │   ├── agent_task.py
│   │   ├── agentctl.py
│   │   ├── audit_trail.py
│   │   ├── auto_commit.py
│   │   ├── build_graph.py
│   │   ├── check_staged.py
│   │   ├── conversations.py
│   │   ├── doctor.py
│   │   ├── finish.py
│   │   ├── setup_env.py
│   │   ├── sync_agent_adapters.py
│   │   ├── update_framework.py
│   │   └── update_tree.py
│   ├── handoff/                            # [交接紀錄] 頂部即時狀態看板 + 歷史交接時間軸，開工前必讀
│   │   └── LATEST.md                       # [即時交接看板] 目前分支、進行中/待接手任務、已完成與待辦事項
│   ├── hooks/                              # [版本控管的 git hooks] 由 core.hooksPath 啟用（pre-commit、pre-push）
│   │   ├── pre-commit
│   │   └── pre-push
│   ├── lib/                                # 框架共用 Python 函式庫 (設定載入、目錄樹註解)
│   │   ├── framework_install.py
│   │   ├── project_config.py
│   │   └── tree_annotations.py
│   ├── skills/                             # 按任務觸發的模組化 Agent Skills (SKILL.md + scripts/*.py)
│   │   ├── adr-issue-tracker/              # [Skill] ADR 與 Known Issues 自動編號與索引
│   │   │   ├── scripts/
│   │   │   │   └── tracker_cli.py
│   │   │   └── SKILL.md
│   │   ├── api-adapter-scaffold/           # [Skill] 外部 API 防腐層產生器
│   │   │   ├── scripts/
│   │   │   │   └── scaffold_adapter.py
│   │   │   └── SKILL.md
│   │   ├── code-review-guard/              # [Skill] 註解、分層、秘密與函式大小靜態審查
│   │   │   ├── scripts/
│   │   │   │   └── review_guard.py
│   │   │   └── SKILL.md
│   │   ├── legacy-migration/
│   │   │   ├── scripts/
│   │   │   │   └── migration_status.py
│   │   │   ├── FLASK_TO_FASTAPI.md
│   │   │   └── SKILL.md
│   │   ├── session-closeout/               # [Skill] 收尾：測試、對話紀錄（逐字稿＋摘要）、交接、Commit
│   │   │   ├── scripts/
│   │   │   │   └── closeout_runner.py
│   │   │   └── SKILL.md
│   │   ├── tdd-bugfix/                     # [Skill] 測試驅動開發與離線 Fixture 產生
│   │   │   ├── scripts/
│   │   │   │   └── tdd_runner.py
│   │   │   └── SKILL.md
│   │   └── catalog.json                    # [Skills 目錄] 各 skill 的分層 (core/stack/optional)、觸發時機與指令
│   ├── tasks/                              # [任務卡] 建立、接手、交接、完成 (agentctl task)
│   │   ├── TASK-001-1-adapters-api-i-o.json
│   │   ├── TASK-002-2-services.json
│   │   ├── TASK-003-3-readme.json
│   │   └── TASK-004-4.json
│   ├── framework.lock                      # [框架鎖定檔] 框架版本與檔案雜湊，供 update_framework 判斷是否被修改
│   └── project.toml                        # [專案設定・各專案自訂] 語言、分層、品質門檻、指令、業務規則
├── .cursor/                                # [Agent 轉接] Cursor 規則 (自動產生)
│   └── rules/
│       └── 00-project-constitution.mdc
├── .github/                                # 【自動化護欄層】CI、PR 範本與 Copilot 入口
│   ├── workflows/                          # CI/CD 自動化檢查工作流程
│   │   └── ci.yml                          # 金鑰掃描、目錄樹檢查、程式審查與離線測試
│   └── copilot-instructions.md             # [Agent 轉接檔] GitHub Copilot 入口 (自動產生)
├── .vscode/
│   ├── extensions.json
│   ├── launch.json
│   └── settings.json
├── .windsurf/                              # [Agent 轉接] Windsurf 規則 (自動產生)
│   └── rules/
│       └── 00-project-constitution.md
├── docs/                                   # 【工程知識庫】架構、規格、決策、已知問題、維運、規範
│   ├── adr/                                # [架構決策庫] 一決定一檔案
│   │   ├── _TEMPLATE.md                    # ADR 範本 (tracker_cli 會套用)
│   │   └── DECISIONS.md                    # 架構決策總表
│   ├── architecture/                       # [系統架構與資料模型]
│   │   ├── ARCHITECTURE.md                 # 系統架構總覽 (手動) 與自動報告索引
│   │   └── PROJECT_TREE.md                 # 完整檔案結構樹 (自動產生)
│   ├── known-issues/                       # [已知問題庫] 一問題一檔案
│   │   ├── _TEMPLATE.md                    # 已知問題範本 (tracker_cli 會套用)
│   │   └── KNOWN_ISSUES.md                 # 已知問題總表 (🔴/🟡/🟢)
│   ├── migration/                          # [遷移紀錄] 舊專案搬移清單、批次與完成標準
│   │   └── MIGRATION.md
│   ├── specs/                              # [功能規格書] PRD / API Contract
│   │   ├── _TEMPLATE.md                    # 規格範本
│   │   └── SPECS.md                        # 規格清單
│   ├── standards/                          # [工程規範] 依任務載入 (Progressive Disclosure)
│   │   ├── ARCHITECTURE_RULES.md           # 分層依賴與系統架構守則
│   │   ├── CODING_PRINCIPLES.md            # 註解規範、Karpathy 原則、SOLID、DRY、Atomic
│   │   ├── ENVIRONMENT_AND_DEPENDENCIES.md # uv / pnpm / Brewfile / 127.0.0.1 環境與依賴規範
│   │   ├── GIT_AND_VERSIONING.md           # Local Git、變更片段、發布與收尾規範
│   │   ├── LOCAL_AI_ENVIRONMENT.md
│   │   ├── MULTI_AGENT_COLLABORATION.md    # Agent 輪流接力：開工、交接、收尾與溯源
│   │   ├── PROJECT_RULES.md
│   │   └── TESTING_AND_QUALITY.md          # 測試金字塔與 DoD 驗收清單
│   └── TEMPLATE_FEEDBACK.md
├── legacy/                                 # [遷移中] 舊專案原始檔，逐批搬到新結構後刪除（見 docs/migration/MIGRATION.md）
├── scripts/                                # 【專案腳本】agentctl.py 是框架的單一入口；其餘放本專案自己的腳本
│   └── agentctl.py                         # [單一入口] 轉呼叫 .agents/bin/agentctl.py
├── src/                                    # 【核心原始碼層】分層與依賴方向定義於 .agents/project.toml
│   └── video_studio/
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── openwebui_runner.py
│       │   └── openwebui_tool.py
│       ├── config/
│       │   ├── __init__.py
│       │   ├── logging_setup.py
│       │   └── settings.py
│       ├── domain/
│       │   ├── __init__.py
│       │   └── models.py
│       ├── entrypoints/
│       │   ├── __init__.py
│       │   └── cli.py
│       ├── services/
│       │   ├── common/
│       │   │   ├── __init__.py
│       │   │   ├── check.py
│       │   │   ├── job.py
│       │   │   └── material.py
│       │   ├── extract_audio/
│       │   │   ├── __init__.py
│       │   │   └── extract.py
│       │   ├── narrate/
│       │   │   ├── core/
│       │   │   │   ├── __init__.py
│       │   │   │   ├── audio.py
│       │   │   │   ├── concat.py
│       │   │   │   ├── generate.py
│       │   │   │   ├── numbers.py
│       │   │   │   ├── script.py
│       │   │   │   ├── subtitles.py
│       │   │   │   ├── takes.py
│       │   │   │   ├── vocab.py
│       │   │   │   ├── voicebox.py
│       │   │   │   └── whisper.py
│       │   │   ├── __init__.py
│       │   │   └── narrate.py
│       │   ├── video/
│       │   │   ├── engine/
│       │   │   │   ├── __init__.py
│       │   │   │   ├── align.py
│       │   │   │   ├── media.py
│       │   │   │   ├── overlay.py
│       │   │   │   ├── poster.py
│       │   │   │   ├── pptx.py
│       │   │   │   ├── storyboard.py
│       │   │   │   └── timing.py
│       │   │   ├── __init__.py
│       │   │   └── video.py
│       │   ├── __init__.py
│       │   ├── greeting.py
│       │   └── sv.py
│       └── __init__.py
├── tests/                                  # 【測試層】單元與整合測試
│   ├── __init__.py
│   ├── test_cli.py
│   ├── test_greeting.py
│   ├── test_openwebui_tool.py
│   └── test_services_core.py
├── .editorconfig
├── .env.example                            # [設定範本] 環境變數清單與預設值說明
├── .gitignore                              # [版控排除] 排除依賴、機密 .env、憑證與執行期快取
├── .python-version                         # [Python 版本釘選] 供 uv / pyenv / mise 自動讀取
├── AGENTS.md                               # [AI 協作憲法・唯一規則來源] 所有 AI Agent 共用的開發原則與 Skills 路由
├── CHANGELOG.md                            # [版本歷史] commit 寫入 Unreleased；agentctl finish --tag 發布版本
├── CLAUDE.md                               # [Agent 轉接檔] Claude Code 入口，匯入 AGENTS.md (自動產生)
├── GEMINI.md                               # [Agent 轉接檔] Gemini CLI 入口，指向 AGENTS.md (自動產生)
├── pyproject.toml                          # [PEP 621 單一真相來源] Python 中繼資料、依賴分組、pytest 與 ruff 設定
└── README.md                               # [唯一 README] 專案入口、快速開始與文件索引
```
