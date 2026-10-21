# SPEC-003：工作範本與輸入規格

- **狀態**：Implemented
- **日期**：2026-10-22
- **相關任務 / ADR**：TASK-002 / TASK-003

## 1. 目標

定義三種工作類型（`extract`, `dub`, `generate`）所需的標準設定檔（`job.toml`）與輸入格式（`script.md`, `scenes.toml`, `brief.md`, `cues.tsv`, `vocabulary.tsv`），確保所有工作結構一致且可自動驗證。

## 2. 使用情境

使用者執行 `video-studio job init <type> <name>` 建立新工作時，系統自動將對應範本複製至 `<workspace>/<type>/<name>/`。

## 3. 需求

- **必須 (Must)**：
  - 欄位名稱一律使用小寫英文。
  - 檔名使用相對路徑，指向 `input/` 目錄。
  - 透過 `check_job` 驗證設定與檔案齊全度，錯誤時精確指出檔名、行號與修復建議。

## 4. 介面 / 檔案清單

- `templates/extract/job.toml`
- `templates/dub/job.toml`
- `templates/dub/input/script.md`
- `templates/dub/input/cues.tsv`
- `templates/generate/job.toml`
- `templates/generate/input/script.md`
- `templates/generate/input/brief.md`
- `templates/generate/input/scenes.toml`
- `templates/shared/vocabulary.tsv`

## 5. 驗收標準

- [x] `check_job` 與 `check_script` 單元測試通過
