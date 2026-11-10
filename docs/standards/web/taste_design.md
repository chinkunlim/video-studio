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
