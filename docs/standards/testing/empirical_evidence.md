# 實證檢驗鐵律與提交前完成定義 (Empirical Verification & Definition of Done)

> **任務載入時機**：修復 Bug、功能收尾、準備 Git Commit 或結束對話前必讀。

---

## 1. 實證檢驗鐵律 (Empirical Verification Iron Law)

**核心鐵律：嚴禁口頭斷言！Agent 絕不可在未出示客觀執行證據前宣稱「已完成」或「已修復」**。

所有任務的交付，必須出示以下三種實證之一或組合：

1. **客觀比對快照 (Snapshot Diff)**：
   - 針對資料轉換、排版輸出或檔案產出，出示變更前 vs. 變更後之清晰 Diff。
   - 包含字元數、行數或雜湊比對結果。
2. **真實運行日誌片斷 (Execution Log Evidence)**：
   - 貼出實際執行指令的輸出日誌，包含真實耗時、退出碼（Exit code 0）與成功關鍵指標。
3. **走測截圖或 Pilot 驗證 (Pilot Result)**：
   - 針對網頁前端或產出檔案，出示實際渲染產物、端對端流程截圖或抽樣截圖結果。

---

## 2. 提交前完成定義 (Definition of Done, DoD)

每次修改完成並執行 `python3 scripts/agentctl.py commit` 前，必須逐項確認：

- [ ] **Coding 原則檢核**：執行 `code-review-guard`，確保無缺漏註解、無跨層依賴、無硬編碼金鑰、函式指標合格。
- [ ] **離線測試 100% 通過**：執行 `[commands] test`，確保測試套件無報錯。
- [ ] **錯誤處理與防禦**：外部失敗具備適當降級或狀態回滾，且不洩漏 Stack Trace。
- [ ] **出示實證記錄**：已貼出測試或指令的實際執行結果證據。
- [ ] **同步知識庫**：重大架構調整已建 ADR，已知問題與踩坑已建 Known Issue，任務狀態已更新。
