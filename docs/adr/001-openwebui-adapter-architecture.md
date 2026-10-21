# ADR-001：Open WebUI 工具配接與本地 AI 服務隔離架構

- **狀態**：Accepted
- **日期**：2026-10-22
- **Agent**：`antigravity`
- **任務**：`TASK-001`
- **相關規格**：[`SPEC-001`](../specs/001-openwebui-tool.md)

## 1. 背景與問題

舊專案中的 `split_voice_tool.py` 為直接供 Open WebUI 載入的單一巨型腳本，混雜了 subprocess 執行、檔案系統操作與 business logic，且在呼叫底層影音指令時若遇到例外會直接拋出 Traceback，導致 Open WebUI 網頁端對話直接終止。

在遷移至新架構時，需要決定如何將 Open WebUI 工具整合至標準架構中，同時兼顧：
1. 嚴格符合架構分層原則（Adapters 層隔離）。
2. 對 LLM 與網頁端保證防呆：所有例外必須被捕獲並回傳友善指引字串。
3. 嚴格限制所有微服務（Voicebox、Open WebUI 等）僅綁定與連線 `127.0.0.1`。

## 2. 評估過的方案

| 方案 | 優點 | 缺點 |
|---|---|---|
| A. 直接在 Adapters 層以單一類別包裝所有函式，內部透過 `_guard` 統一攔截例外 | 介面完全相容 Open WebUI 原生 Tool 規範；使用者無需額外起獨立 HTTP 服務 | 類別行數較多（約 600 行） |
| B. 拆分為獨立的 FastAPI HTTP Microservice，Open WebUI 透過 OpenAPI 串接 | 程式碼分層徹底，可跨多台主機呼叫 | 需維護獨立守護行程與連接埠，增加本機使用門檻與記憶體開銷 |
| C. 保持舊腳本原樣作為 legacy 存在 | 完全免修改 | 無法通過型別檢查（mypy strict）、分層測試與程式碼守衛 |

## 3. 決策與理由

**採用方案 A**：
1. 將舊腳本搬遷重構為 `video_studio.adapters.openwebui_tool.Tools` 與 `video_studio.adapters.openwebui_runner`。
2. 透過 `_guard` 裝飾器 / 上下文管理器攔截所有未預期例外，格式化輸出錯誤原因與建議修復指令。
3. 遵循 Open WebUI Tool 的 `Valves` 與 `UserValves` 定義，所有參數（`voicebox_url`、`workspace_dir`、`timeout_minutes`）均可由管理員自訂。
4. 呼叫底層 `video_studio.services` 的業務函式，達成配接層與服務層的單向依賴。

## 4. 影響與代價

- **正面影響**：
  - Open WebUI 使用者可一鍵將 `openwebui_tool.py` 貼入 Custom Tools 即可運作。
  - 對話模型能收到結構化錯誤說明（如：「工作設定檔不存在，請先執行 create_job」），能自主進行自我修正與對話回覆。
- **代價**：
  - `openwebui_tool.py` 需涵蓋多項子操作，檔案長度突破 500 行門檻，目前以 Code Review Guard 暫時記錄，後續可依功能領域拆分為多個 Helper。
