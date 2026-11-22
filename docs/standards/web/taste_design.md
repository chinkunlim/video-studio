# 前端品味、UI/UX 與視覺設計審批 (Frontend Taste, UI/UX & Prerequisite Mockup Gate)

> **任務載入時機**：設計網頁前端、元件排版、視覺風格或美化介面時必讀。

---

## 1. Step 0 前置原型審查關卡 (Prerequisite Mockup Gate)

**鐵律：在寫入任何前端程式碼（HTML/CSS/JS）前，必須先過本關卡**。

1. **Figma 視覺構思**：
   - 拒絕純文字想像，必須以設計師視角構思整頁排版，規劃 Header、Hero、主功能區、狀態回饋與 Footer。
   - 審查各區塊之視覺焦點、間距節奏（Whitespace Rhythm）與按鈕視覺權重。
2. **受眾心理學分析 (Audience Psychology)**：
   - 依據專案目標使用者角色（如研究生、學者、一般大眾）套用對應的認知理論：
     - **認知負荷理論 (Cognitive Load)**：關鍵路徑一目了然，去除干擾視覺元件。
     - **席克定律 (Hick's Law)**：減少選項分支，核心操作一鍵觸達。
     - **格式塔完形心理學 (Gestalt Principles)**：相關控制項在視覺上群組化，留白合理。
3. **原型生成與展示確認**：
   - 使用 Markdown ASCII Mockup、結構線框或截圖生成原型展示給使用者審查。
   - 必須獲得使用者明確確認與同意後，方可進入實體代碼開發。

---

## 2. 核心設計度量衡 (Design Dials)

1. **Density (資訊密度)**：依受眾調整元件內距（Padding）與間距（Gap）。儀表板採高密度緊湊排版，展示型頁面採寬鬆留白。
2. **Elevation (層次感)**：利用細微邊框（Subtle Border）與多層柔和陰影建立立體維度，避免生硬純黑陰影。
3. **Color & Hierarchy (色彩層級)**：嚴格定義主色、次色與中性灰階。背景與文字對比度必須通過 WCAG 2.1 AA 標準。
4. **Interactive States (互動狀態反饋)**：按鈕與連結必須定義完整的 Default, Hover, Active, Focus-visible, Disabled 狀態。

---

## 3. 禁忌 AI Slop 特徵清單 (Banned AI Slop Patterns)

- ❌ 無意義的紫色或彩虹漸層按鈕/背景。
- ❌ 浮誇無功能性的發光霓虹邊框（Glow effects）。
- ❌ 沒有內容依據的通用卡片堆疊與過度圓角（Full rounded pill cards）。
- ❌ 失去焦點的同質化科技風暗黑主題。

---

## 4. 標準網頁開發流程 (Standard Web Dev Pipeline)

1. **設計理念對齊**：撰寫程式前先對齊 `DESIGN.md` 與 Step 0 原型審批。
2. **三入口同步實作**：同一 `services` 同步接好 HTTP 路由、MCP 工具與網頁互動，並維持文檔／介面用語一致（純文字膠囊語彙、不混雜冗餘 emoji）。
3. **三視口自適應驗證**：檢查桌面、平板與手機三種視口；僅保留有意義之留白與層級，不強制單一固定版型。
4. **動效與狀態一致性**：所有彈窗、抽屜與按鈕統一引用 `styles.css` 中的 Motion Tokens（`--dur-hover` / `--dur-slide` / `--ease`），同類交互節奏溫潤一致並尊重 `prefers-reduced-motion`。
5. **審計與收尾**：執行 `frontend-design` 審查與 `python3 scripts/agentctl.py check`、靜態契約測試 `tests/test_web_contracts.py` 皆須零錯誤。

---

## 5. 跨裝置觸控與無建置前端規範

1. **觸控友善熱區**：所有互動控制項於 `@media (pointer: coarse)` 下確保觸控目標 $\ge 44\text{px}$（最低不小於 $36\text{px}$），拖曳把手須加 `touch-action: none`；平板與手機無鍵盤時重要功能必備顯式按鈕入口。
2. **Zero-Build 前端核心 (`web/api_client.js`)**：
   - `apiFetch` 僅在網路斷線時對 `GET` 自動重試 1 次，對 `POST` / `PUT` / `PATCH` / `DELETE` **絕不自動重試**，並統一顯示離線提示條 `#offlineBanner`。
   - 跨模組狀態同步採用輕量 `createEventBus()` 與 `createStateStore()`，避免全域變數緊耦合。
3. **離線 Vendor 打包**：外部字型或 JS 庫一律以 `pnpm` 鎖版安裝後透過腳本複製進 `web/vendor/`（或 `static/vendor/`），確保斷網完全可用且自動受 `code-review-guard` 與 `.graphifyignore` 排除。
