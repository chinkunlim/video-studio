# 現代 Web 標準與 Baseline 指南 (Modern Web Guidance)

> **任務載入時機**：撰寫 HTML / CSS / JavaScript 前端元件、互動效果、佈局或重構舊版網頁程式碼時必讀。
> **上游參考**：[`GoogleChrome/modern-web-guidance`](https://github.com/GoogleChrome/modern-web-guidance)（由 Google Chrome、Microsoft Edge、Mozilla Firefox 與 MDN 共同維護）。
> **分工關係**：[`taste_design.md`](taste_design.md) 與 `frontend-design` 負責**視覺品味、Design Tokens 與 UI 狀態**；本檔負責**底層現代原生 Web 平台標準與 Baseline 相容性**，兩者互補。

---

## 1. 為什麼需要本規範

LLM 訓練資料包含大量 2019 年以前的舊式前端寫法（例如用上百行自製 JavaScript 模擬彈窗、手刻浮層定位、舊式 CSS Hack）。除非明確約束，否則 AI 容易預設產出冗長、效能差或無障礙不完整的前端碼。

**原則：優先使用跨瀏覽器 Baseline 原生 HTML / CSS / Web API，取代自製 JS 輪子與過時寫法。**

---

## 2. 優先採用的現代原生寫法（Baseline 基準）

| 需求場景 | ❌ 避免舊式寫法 | ✅ 優先採用現代原生標準 |
|---|---|---|
| **彈窗 / 對話框 (Modal)** | `<div class="modal">` + 手刻 focus trap / ESC 監聽 / body scroll lock | 原生 `<dialog>`（`showModal()`）搭配 `::backdrop` 與 `@starting-style` 進出場過渡 |
| **浮層 / 下拉選單 / Tooltip** | 全域 `click` 監聽 + 手算座標 / 龐大定位套件 | 原生 **Popover API**（`popover`、`popovertarget`）與 CSS Anchor Positioning（視目標瀏覽器 Baseline 支援度加 fallback） |
| **元件響應式佈局** | 依賴 JS `ResizeObserver` 切換 class 或只看全局 `@media` | CSS **Container Queries**（`@container`）與 `:has()` 選取器 |
| **表單驗證與互動** | 完全靠 JS 攔截並重建基本格式檢查 | 原生語意化 `<input>` 屬性 + Constraint Validation API（`checkValidity()` / `:user-invalid`），再輔以自訂錯誤提示 |
| **主執行緒防卡頓與請求取消** | 長迴圈阻塞 UI、無取消機制的 `fetch()` | `scheduler.yield()` 分段讓出主執行緒（需確認 fallback）；`AbortController` 取消過期請求 |
| **暗色/亮色與動效無障礙** | 重複寫兩套完整變數、強制執行動畫 | `color-scheme` / `light-dark()` 與 `@media (prefers-reduced-motion: reduce)` |

---

## 3. 與本模板環境隔離規則整合

1. **禁止直接執行 `npx modern-web-guidance@latest`**：依 `AGENTS.md` 核心規則 8，專案內嚴禁隨意使用 `npx` 或全域安裝污染本機環境。
2. **建議接入方式（擇一）**：
   - **Agent Plugin / Skill 層（推薦，本環境已安裝）**：Antigravity 環境已啟用 `modern-web-guidance-plugin`（含 `modern-web-guidance`、`chrome-extensions`）與配套的 `chrome-devtools-plugin`（含 `chrome-devtools`、`a11y-debugging`、`debug-optimize-lcp` 等），寫前端或除錯時可直接按需調用。
   - **Node 專案依賴層**：若專案本身已使用 `pnpm` 管理前端工具鏈，再將其加入專案鎖定檔或以 `pnpm` 受控執行。
3. **漸進揭露**：不將整份指南複製進 `AGENTS.md`；僅在動手寫特定互動元件或審查舊式前端碼（`legacy-scan`）時，查詢對應主題並對齊 **Baseline** 瀏覽器支援目標。
