# 測試金字塔與品質驗收規範 (Testing & Quality Standards)

> **AI Agent 載入時機**：當新增功能、修復 Bug、調整外部資料解析邏輯或準備執行提交前驗收 (DoD) 時，**必須閱讀並遵守本文件**。專案專屬測試指令與品質門檻定義於 [`.agents/project.toml`](../../.agents/project.toml)。

---

## 1. 三層測試

測試資料夾：Python `tests/`、Node / GAS `test/`、手機 App `mobile/test/`（檔名 `test_*.py`、`*.test.js`、`*.test.ts`）。

| 層級 | 放哪裡 | 網路 | 何時跑 | 測什麼 |
|---|---|---|---|---|
| **單元** | `tests/test_<模組>.py` | **不連網**（純記憶體） | 每次修改 | `services`、`domain` 的純邏輯；`config` 驗證；`adapters` 用靜態樣本解析 |
| **整合** | `tests/integration/` | **不連網**（假的 HTTP client、記憶體資料庫 `sqlite://`、FastAPI `TestClient`） | 每次 commit 前 | `entrypoints ➔ services ➔ adapters` 完整流程、錯誤處理、`[project_rules]` |
| **端對端** | `tests/e2e/`（預設不跑） | **真實網路與 API**（需要 `.env` 金鑰） | 手動或發布前 | 真實外部服務、備援切換 |

`[commands] test` 只跑前兩層；端對端測試要明確執行，並且不可成為 `agentctl check` 的一部分。

---

## 2. 靜態樣本驅動測試 (Fixture-Driven Testing)

1. 外部網頁、API 回應、Webhook payload 的解析邏輯，**單元測試不可直接連網**。
2. 先把真實回應去除個資後存到 `tests/fixtures/`（如 `sample_response.json`、`sample_page.html`，每個 ≤ 1 MB；pre-commit 允許這個資料夾的小樣本），再由單元測試讀檔驗證解析函式。
3. 外部服務格式改版導致解析失效時：
   - 先記錄 `docs/known-issues/NNN-xxx.md`
   - 把新版樣本存入 `tests/fixtures/`
   - 更新解析函式並補上防回歸測試。

---

## 3. 提交前完成定義 (Definition of Done, DoD)

每次修改完成並執行 `python3 scripts/agentctl.py commit` 前，必須確認（Python 測試與工具一律透過 `uv run` 在專案 `.venv` 執行）：

- [ ] **Coding 原則檢核**：通過 `python3 .agents/skills/code-review-guard/scripts/review_guard.py`（註解規範、單向依賴、秘密、Atomic 函式門檻與 `[project_rules]`）。
- [ ] **離線測試全數通過**：執行 `.agents/project.toml` `[commands] test` 設定之測試指令 100% 綠燈。
- [ ] **錯誤處理與狀態安全**：外部呼叫失敗時具備適當的降級或狀態回滾補償，且不會向終端使用者洩漏內部 Stack Trace 或機密資訊。
- [ ] **目錄樹、圖譜與金鑰檢查**：`python3 scripts/agentctl.py check`（含目錄樹、分層依賴）與金鑰掃描無異常。
- [ ] **知識庫與多 Agent 交接同步**：若有架構決策變更已更新 `docs/adr/DECISIONS.md`；若為踩坑修復已更新 `docs/known-issues/KNOWN_ISSUES.md`；任務狀態已透過 `agentctl task` 更新；結束對話時已補完本機對話摘要（`.agents/conversations/`）。
