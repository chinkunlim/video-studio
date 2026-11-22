# ADR-006：DATA_DIR 角色分層結構與 output/<job>/releases 定稿發布

- **狀態**：Accepted
- **日期**：2026-11-20
- **Agent**：`Antigravity`
- **任務**：`TASK-015`

## 1. 背景與問題

原 [ADR-002](002-workspace-isolation-and-review.md) 將四層隔離目錄放在 `DATA_DIR/workspace/<type>/<job>/` 下，導致模板規定的 `DATA_DIR/input/`、`DATA_DIR/needs_review/`、`DATA_DIR/output/`、`DATA_DIR/state/` 長期為空；同時每個工作的 `output/vN/` 混放中繼驗收檔（`timeline.json`、`video_check.txt`）與最終影片，不利於終端交付與雲端同步。

## 2. 評估過的方案

| 方案 | 優點 | 缺點 |
|---|---|---|
| A. 改為 `DATA_DIR/{input,needs_review,work,state,output}/<job>/` 角色分層，並在 `output/<job>/releases/<vN>/` 透過硬連結發布唯一最新定稿 | 完全對齊母版 `DATA_DIR` 第一層規範；不重複複製大型影片（zero-copy）；保留所有歷史版本 `v1, v2, ...` | 需重構 `Job` 路徑對應與更新既有測試夾具 |
| B. 維持 `workspace/<type>/<job>/` 並僅於文件豁免 | 程式碼變動最少 | `DATA_DIR/input/`、`needs_review/`、`output/` 持續為空，與母版工具/文件不一致 |

## 3. 決策與理由

**採用方案 A**：
1. **`DATA_DIR` 第一層按角色分層**：`input/<job>/`（唯讀素材）、`needs_review/<job>/`（AI 草稿、韻律試聽與 `review_history/`）、`work/<job>/`（中間暫存）、`state/<job>/job.toml`（可寫工作設定）、`output/<job>/vN/`（版本庫）。
2. **`output/<job>/releases/<vN>/` 單一定稿機制**：呼叫 `publish_release`（Web UI / API / MCP / CLI）時，僅將 `*.mp4` 與 `subtitles_{youtube,vlc}.srt` 以硬連結（跨裝置自動降級為複製）發布至 `releases/<vN>/`；若已有舊版定稿，則自動從 `releases/` 移除連結，退回為僅存在於 `output/<job>/<old_vN>/` 的未發布狀態（零資料遺失）。
3. **停止複製 `templates/`**：專案範本統一保存在程式庫根目錄 `templates/`，不再於 `init_job` 時複製至 `input/<job>/templates/`。

## 4. 影響與代價

- **正面影響**：`DATA_DIR` 結構與專案模板、`agentctl doctor` 完全一致；`releases/` 內只存在唯一最新定稿交付物，且不佔額外硬碟空間。
- **代價**：`Job` 不再對應單一目錄，而是由 `state/<job>/job.toml` 推導各角色資料夾；所有版本掃描函式必須嚴格匹配 `v<數字>`，避免將 `releases/` 誤判為版本資料夾。
