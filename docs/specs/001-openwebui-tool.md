# SPEC-001：Open WebUI 工具整合

- **狀態**：Implemented
- **日期**：2026-10-22
- **相關任務 / ADR**：TASK-001 / ADR-001

## 1. 目標

讓使用者在 Ollama + Open WebUI 網頁介面對話中，直接下達自然語言指令呼叫 `video-studio` 進行講稿配音、音訊提取、分鏡製作與影片合成，並在發生錯誤時獲得清楚的指引。

## 2. 使用情境

使用者在瀏覽器打開 `http://127.0.0.1:8080`，向 LLM 模型（如 `qwen2.5`）詢問「幫我把這份講稿做成配音」，模型呼叫本工具的各項函式（`create_job`, `check_job`, `build_narration`, `render_video` 等）完成流程。

## 3. 需求

- **必須 (Must)**：
  - 遵循 Open WebUI Tool 規範定義 `Tools` 與 `Valves`。
  - 本機服務限綁定 `127.0.0.1`（Voicebox: `http://127.0.0.1:17493`）。
  - 工具所有例外均由 `_guard` 攔截，回傳友善錯誤字串，不使對話中斷。
  - 遵循嚴格型別註解與完整的 docstring。
- **可選 (Nice to have)**：
  - 支援 `timeout_minutes` 逾時控制。
  - 支援工作名稱快速解析（簡稱自動轉為完整型別路徑）。
- **不做 (Out of scope)**：
  - 不做外部網路 API 呼叫，全部基於本機服務與檔案系統。

## 4. 介面 / API

- 類別：`video_studio.adapters.openwebui_tool.Tools`
  - `check_environment(self) -> str`
  - `list_jobs(self) -> str`
  - `create_job(self, job_type: str, job_name: str, title: str, script_text: str = "", extra_files_json: str = "{}") -> str`
  - `check_job(self, job_name: str) -> str`
  - `build_narration(self, job_name: str, force_regenerate: bool = False) -> str`
  - `draft_scenes(self, job_name: str, source: str = "auto", force: bool = False) -> str`
  - `approve_review(self, job_name: str, filename: str) -> str`
  - `render_video(self, job_name: str, mode: str = "poster", version: str = "") -> str`
  - `set_vocabulary(self, key: str, subtitle: str, tts: str, category: str = "", note: str = "", tested: bool = False, confirm: bool = False) -> str`

## 5. 驗收標準

- [x] 單元測試 `tests/test_openwebui_tool.py` 通過
- [x] 通過 mypy strict 型別檢查與 code-review-guard
