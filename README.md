# video-studio

AI 語音配音、字幕生成與影片製作工作站（整合 Voicebox、ffmpeg、Whisper 與 PowerPoint/海報鏡頭動畫）。

本專案提供講稿配音、音訊切分提取、多格式字幕產生（YouTube SRT、PowerPoint VTT、VLC ASS）以及畫面合成。支援命令列 CLI 與 Open WebUI 本機工具整合。

## 功能模組與 CLI 指令

| 子命令 | 用途 | 範例 |
|---|---|---|
| `video-studio job` | 工作管理（建立、清單、檢查、核可草稿） | `uv run video-studio job list` |
| `video-studio extract` | 從影片提取音訊、切分聲音樣本 | `uv run video-studio extract video.mp4 --samples samples/` |
| `video-studio narrate` | 講稿配音、單句試聽、組裝字幕 | `uv run video-studio narrate build my-job` |
| `video-studio video` | 配音與畫面合成、海報分鏡渲染、PPTX 匯出 | `uv run video-studio video poster my-job` |

Open WebUI 使用者可直接載入 `src/video_studio/adapters/openwebui_tool.py` 作為 Tool。詳細規格請參閱 [`docs/specs/`](docs/specs/) 與 [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md)。

## 第一次在這台電腦使用

1. 取得程式（已經在本機就略過）

```bash
git clone <repo-url> && cd video-studio
```

2. 檢查並修復環境：啟用 git hook、建立 `.env`、建立 DATA_DIR、檢查 uv（只修這個專案，不安裝全域工具）

```bash
python3 scripts/agentctl.py doctor --fix
```

3. 打開 `.env` 填入金鑰與設定（`.env` 不會被 commit）。

4. 安裝依賴：uv sync（專案內 `.venv/`）

```bash
python3 scripts/agentctl.py setup --install
```

> 換電腦時：資料不在 git 裡，另外複製整個 `DATA_DIR`（路徑寫在 `.env`）。
> 搬移或改名專案資料夾後：執行一次 `python3 scripts/agentctl.py doctor --fix`（重建記住舊位置的 `.venv`）。

新增 Python 套件：`uv add <套件>`（開發工具 `uv add --dev <套件>`）；執行程式：`uv run ...`。Python 版本由 uv 依 `.python-version` 自動下載，不會動到主機的 Python / pip。

## 確認一切正常

註解、分層、秘密、lint、型別、目錄樹

```bash
python3 scripts/agentctl.py check
```

專案測試

```bash
uv run python -m unittest discover -s tests -v
```

## 和 AI Agent 一起開發

用 Claude Code、Antigravity、Cursor 等工具打開這個資料夾，Agent 會自動讀 `AGENTS.md`。直接用口語下指令：

| 你說 | Agent 會做 |
|---|---|
| 「開工」「繼續上次的」 | 看交接看板、上次的下一步、未完成的任務 |
| 「新功能：…」 | 建任務卡，寫測試與程式 |
| 「commit」 | 檢查後本機 commit（英文訊息，不會推送） |
| 「去上課」「先暫停」 | 記下進度，下次接著做 |
| 「收工」 | 測試、寫對話紀錄與摘要、更新交接看板、commit |
| 「推上去」 | 列出要推送的 commit，等你同意 |
| 「出版本」「專案完成了」 | 完成驗收；`--tag` 時升版並打 tag |

完整對照表見 [`AGENTS.md`](AGENTS.md) §1。

## 常用指令

```bash
python3 scripts/agentctl.py status
```

```bash
python3 scripts/agentctl.py task create "標題" --agent <名字>
```

```bash
python3 scripts/agentctl.py commit --agent <名字>
```

```bash
python3 scripts/agentctl.py closeout --agent <名字>
```

全部子指令

```bash
python3 scripts/agentctl.py --help
```

## 文件索引

- [`AGENTS.md`](AGENTS.md) — Agent 規則與「文件放哪裡」對照表
- [`.agents/handoff/LATEST.md`](.agents/handoff/LATEST.md) — 交接看板
- `.agents/conversations/` — 每次對話的逐字稿與摘要（本機，不進 git）
- [`docs/adr/DECISIONS.md`](docs/adr/DECISIONS.md) — 架構決策
- [`docs/known-issues/KNOWN_ISSUES.md`](docs/known-issues/KNOWN_ISSUES.md) — 已知問題
- [`docs/specs/SPECS.md`](docs/specs/SPECS.md) — 需求規格
- [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md) — 系統架構與目錄樹（依賴圖、審計報告需要時用 `agentctl graph` / `agentctl audit` 產生）
- [`docs/standards/PROJECT_RULES.md`](docs/standards/PROJECT_RULES.md) — 本專案特有的規則
- [`CHANGELOG.md`](CHANGELOG.md) — 版本變更
