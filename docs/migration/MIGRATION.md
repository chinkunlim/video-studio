# 專案遷移計畫 (MIGRATION)

> 舊專案的檔案目前在 `legacy/`（原封不動）。依下方批次逐一搬到新結構，**每一批都要符合新專案的所有規範**，全部完成後刪除 `legacy/`。

## 1. 來源

- **舊專案位置**：`/Users/limchinkun/Desktop/projects/Old/split-voice`
- **舊專案遠端**：`-`
- **遷移時的最後 commit**：`-`
- **git 歷史**：未保留（舊專案不是 git repo）
- **模式**：開發模式：Flask 必須全部改寫成 FastAPI（對照表：[`FLASK_TO_FASTAPI.md`](../../.agents/skills/legacy-migration/FLASK_TO_FASTAPI.md)）（舊專案未使用 Flask）
- **建立時間**：2026-10-21 16:53 UTC
- **檔案數**：46

## 2. 完成標準

### 每一批

每一批都必須做到（做到才可 `agentctl task done`）：

1. **兩個 commit：先搬、再整理**（保證 `git log --follow` 與 blame 追得到舊歷史）：
   - 第一個 commit 只用 `git mv legacy/舊路徑 新路徑` 搬移，內容一個字都不改：`agentctl commit --bump none -m "refactor(migration): move <檔名> from legacy"`。pre-commit 只對「從 legacy/ 原樣搬入」的檔案暫時放行註解、大小、分層與 print 問題（秘密與禁用套件仍會擋）。
   - 下一個 commit 必須把這批檔案全部整理到符合規範（第 2 點），否則任何 commit 與 `agentctl check` 都過不了，所以一批只搬少量檔案。
2. 依新規範修改：
   - **註解**：檔案開頭用途說明；每個函數/類別的說明、每個參數（`Args:` / `@param`）與回傳值（[`CODING_PRINCIPLES.md`](../standards/CODING_PRINCIPLES.md) §0）。
   - **型別**：Python 參數與回傳值都有型別，`uv run mypy` 通過（strict）。
   - **分層**：放到正確的層；環境變數只在 `config` 層讀取，其他層改收 `AppConfig` 參數（[`ARCHITECTURE_RULES.md`](../standards/ARCHITECTURE_RULES.md)）。
   - **函式大小**：符合 `[quality]` 門檻。
   - **Log**：除了 entrypoints，`print` 一律改成模組 logger；關鍵步驟、外部呼叫與例外都要記 log（[`CODING_PRINCIPLES.md`](../standards/CODING_PRINCIPLES.md) §0.4）。
   - **秘密**：金鑰移到 `.env`，`.env.example` 只留變數名稱。
   - **依賴**：只用 `uv add` / `pnpm add`（[`ENVIRONMENT_AND_DEPENDENCIES.md`](../standards/ENVIRONMENT_AND_DEPENDENCIES.md)）。
   - **本機服務**：綁 `127.0.0.1`，網址不用 `localhost`。
   - **測試**：搬移的程式要有測試（沿用舊測試或補寫，[`TESTING_AND_QUALITY.md`](../standards/TESTING_AND_QUALITY.md)）。
3. `python3 scripts/agentctl.py check` 與專案測試全部通過。
4. 下方「檔案清單」把這批的 ☐ 改成 ☑；過程中的重要決策寫 ADR、發現的舊 bug 寫 known-issue。
5. `python3 scripts/agentctl.py commit --agent <名字> --task TASK-NNN`，再 `agentctl task done TASK-NNN --summary ...`。

### 整個遷移

全部完成才算遷移成功（`python3 scripts/agentctl.py migration --verify` 會逐項檢查）：

- [x] `legacy/` 已刪除（所有檔案都搬到新結構或確認不需要）。
- [x] 舊資料已依 §4.5 複製到 `DATA_DIR`，程式透過 config 讀取路徑，專案資料夾內沒有資料檔。
- [x] 沒有 `requirements.txt`、`package-lock.json`、`yarn.lock`、`Pipfile`：依賴只在 `pyproject.toml` + `uv.lock`、`package.json` + `pnpm-lock.yaml`。
- [x] `python3 scripts/agentctl.py check` 全部通過（註解、分層、秘密、lint、mypy strict、目錄樹）。
- [x] 專案測試全部通過。
- [x] 所有遷移任務卡都是 `done`。
- [x] 模板的範例程式（`greeting` 相關的 services / domain / cli / api / 資料表 `greetings` 與其 Alembic revision、測試）已刪除或換成真正的程式。
- [x] `README.md` 改寫為這個專案的說明；`docs/architecture/ARCHITECTURE.md` 有系統概覽；主要功能在 `docs/specs/` 有規格。
- [x] 舊專案已知的問題記在 `docs/known-issues/`；遷移中的重要決策記在 `docs/adr/`。
- [x] `.env.example` 列出所有需要的變數（只有名稱）。
- [x] 最後執行 `agentctl closeout`（本機對話紀錄＋交接看板記下遷移完成）。

## 3. 批次

| 順序 | 任務 | 內容 | 檔案數 |
|---|---|---|---|
| 1 | `TASK-001` | adapters 層（外部 API、資料庫、檔案 I/O） | 1 |
| 2 | `TASK-002` | services 層（業務流程） | 27 |
| 3 | `TASK-003` | 文件（README、規格、決策、已知問題） | 8 |
| 4 | `TASK-004` | 其他（資料、資源、需人工判斷） | 10 |

## 4. 依賴轉換

（舊專案沒有可自動轉換的依賴檔）

## 4.5 資料搬到 DATA_DIR（資料不進新專案）

- 舊專案沒有偵測到資料檔。

## 5. 風險

- 未發現機密檔或大型檔案。

## 6. 檔案清單

| 狀態 | 舊檔案 | 建議位置 | 批次 |
|---|---|---|---|
| ☑ | `legacy/openwebui/split_voice_tool.py` | `src/video_studio/adapters/` | adapters |
| ☑ | `legacy/common/__init__.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/common/check.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/common/job.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/common/material.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/extract_audio/extract.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/narrate/core/__init__.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/narrate/core/audio.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/narrate/core/concat.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/narrate/core/generate.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/narrate/core/numbers.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/narrate/core/script.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/narrate/core/subtitles.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/narrate/core/takes.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/narrate/core/vocab.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/narrate/core/voicebox.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/narrate/core/whisper.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/narrate/narrate.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/sv.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/video/engine/__init__.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/video/engine/align.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/video/engine/media.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/video/engine/overlay.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/video/engine/poster.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/video/engine/pptx.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/video/engine/storyboard.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/video/engine/timing.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/video/video.py` | `src/video_studio/services/` | services |
| ☑ | `legacy/README.md` | `README.md（改寫成新專案的說明）` | docs |
| ☑ | `legacy/docs/DESIGN.md` | `docs/architecture/ARCHITECTURE.md` | docs |
| ☑ | `legacy/openwebui/README.md` | `openwebui/OPENWEBUI.md（全專案只有根目錄一份 README）` | docs |
| ☑ | `legacy/templates/README.md` | `templates/TEMPLATES.md（全專案只有根目錄一份 README）` | docs |
| ☑ | `legacy/templates/dub/input/script.md` | `docs/specs/ 或 docs/adr/ 或 docs/known-issues/` | docs |
| ☑ | `legacy/templates/generate/input/brief.md` | `docs/specs/ 或 docs/adr/ 或 docs/known-issues/` | docs |
| ☑ | `legacy/templates/generate/input/script.md` | `docs/specs/ 或 docs/adr/ 或 docs/known-issues/` | docs |
| ☑ | `legacy/video/README.md` | `video/VIDEO.md（全專案只有根目錄一份 README）` | docs |
| ☑ | `legacy/.mcp.json` | `依用途判斷（資料 → DATA_DIR，靜態資源 → web/ 或 src/<pkg>/）` | other |
| ☑ | `legacy/narrate/config.toml` | `依用途判斷（資料 → DATA_DIR，靜態資源 → web/ 或 src/<pkg>/）` | other |
| ☑ | `legacy/narrate/traditional_fixes.tsv` | `依用途判斷（資料 → DATA_DIR，靜態資源 → web/ 或 src/<pkg>/）` | other |
| ☑ | `legacy/templates/dub/input/cues.tsv` | `依用途判斷（資料 → DATA_DIR，靜態資源 → web/ 或 src/<pkg>/）` | other |
| ☑ | `legacy/templates/dub/job.toml` | `依用途判斷（資料 → DATA_DIR，靜態資源 → web/ 或 src/<pkg>/）` | other |
| ☑ | `legacy/templates/extract/job.toml` | `依用途判斷（資料 → DATA_DIR，靜態資源 → web/ 或 src/<pkg>/）` | other |
| ☑ | `legacy/templates/generate/input/scenes.toml` | `依用途判斷（資料 → DATA_DIR，靜態資源 → web/ 或 src/<pkg>/）` | other |
| ☑ | `legacy/templates/generate/job.toml` | `依用途判斷（資料 → DATA_DIR，靜態資源 → web/ 或 src/<pkg>/）` | other |
| ☑ | `legacy/templates/shared/vocabulary.tsv` | `依用途判斷（資料 → DATA_DIR，靜態資源 → web/ 或 src/<pkg>/）` | other |
| ☑ | `legacy/video/config.toml` | `依用途判斷（資料 → DATA_DIR，靜態資源 → web/ 或 src/<pkg>/）` | other |
