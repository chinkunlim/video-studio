# 使用者視角流程對齊與知識圖譜純淨化 (Workflow Parity & Graphify Hygiene)

> **任務載入時機**：討論系統架構、重構業務流程、整合 Graphify 知識圖譜時必讀。

---

## 1. 使用者視角端到端流程與程式一致性 (End-to-End Workflow Parity)

1. **使用者視角出發**：
   - 討論專案功能或調整架構流程時，必須給出完整的 Mermaid 流程圖。
   - 流程圖必須從使用者最初的操作起點（CLI 觸發、網頁點擊、檔案輸入），一路延伸到最終交付產出位置（PDF 生成、資料庫儲存、報告下載）。
   - **嚴禁精簡中間步驟**：驗證、轉換、重試、降級、快取、檔案移動等所有環節必須完整繪出。
2. **Workflow 與程式雙向核對**：
   - 完成流程圖規劃後，必須與實體程式碼進行雙向比對，確保 100% 一致。
   - 若發現不一致：
     - 明確列出差異清單。
     - 深度評估應以 Workflow 為準重構程式，還是以程式限制為準調整 Workflow。
     - 向使用者詳細報告技術理由與架構影響，經確認後統一對齊。

---

## 2. Graphify 本體依賴純淨化 (.graphifyignore)

1. **排除第三方與產出噪音**：
   - 整合 Graphify 生成專案知識圖譜時，必須嚴格排除所有第三方函式庫、套件產物、虛擬環境與編譯輸出。
   - 專案根目錄必須配置 `.graphifyignore`，預設包含：
     - 第三方依賴：`assets/vendor/`、`node_modules/`、`.venv/`、`site-packages/`。
     - 產物與大型檔案：`dist/`、`build/`、`*.min.js`、`*.min.css`、`*.pdf`、圖檔。
     - 快取與資料目錄：`__pycache__/`、`projects-data/`、`output/`。
2. **純淨圖譜價值**：
   - 消除數千個外部節點雜訊，確保知識圖譜僅呈現專案本體的「God Nodes」、關鍵呼叫鏈與分層關係。
   - 定期從知識圖譜檢查專案模組耦合度與潛在架構孤島，指導系統重構。
3. **Graphify 自動更新 Hooks 與局部讀檔協議**：
   - `.agents/hooks/` 內建 `post-commit`、`post-merge`、`post-checkout` 與 `graphify-refresh.sh`（0-token 背景 AST 增量更新、`graphify-out/` 不存在時靜默略過、10 分鐘過期鎖自癒、最多保留 3 份日期備份、未安裝 `graphify` 時不阻擋 Git）。
   - `.graphifyignore` 預設排除 `.agents/`、`graphify-out/`、`static/vendor/`、`web/vendor/` 及自動報告。
   - **局部讀檔省 Token**：開啟大檔案前先查 `graphify-out/GRAPH_REPORT.md` 定位目標函式與行號，再用 `StartLine`/`EndLine` 局部讀取，避免全文載入浪費 Context。
