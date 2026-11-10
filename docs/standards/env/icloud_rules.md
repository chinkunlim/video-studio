# iCloud 同步與外部儲存嚴格規範 (iCloud Synchronization Standards)

> **任務載入時機**：使用者要求同步產出至 iCloud，或處理外部雲端備份時必讀。

---

## 1. iCloud 同步四項鐵律

1. **當次明確授權原則**：
   - 只有在使用者**當次對話明確要求**（例如「同步到 iCloud」或告知「我不在電腦旁邊」）時，才允許將檔案複製至 iCloud。
   - 嚴禁 Agent 未經許可擅自將 iCloud 加入日常自動化排程或預設同步流程。
2. **最小核心交付原則 (Output-Only)**：
   - 僅同步使用者最關心的最終產出交付物（例如最終編譯成功的 PDF 筆記、匯出的報告檔案）。
   - **嚴禁同步原始資料**：中間原稿、除錯日誌、暫存快照、對話逐字稿與資料庫檔案一律禁止上傳至 iCloud。
3. **集中統一存放路徑**：
   - 強制集中存放在 iCloud Drive 下的 `project-data/<專案名稱>/` 目錄中。
   - **嚴禁在 iCloud 根目錄自建零散專案資料夾**，避免污染使用者雲端空間。
4. **沙盒權限邊界與防假回報**：
   - macOS 終端機或 Agent 沙盒可能受系統限制無權直接存取 `~/Library/Mobile Documents/com~apple~CloudDocs/`。
   - 若遇到 `Operation not permitted`，**必須誠實向使用者回報**並提供指令或檔案路徑指引，嚴禁偽造「已同步完成」之假狀態。
