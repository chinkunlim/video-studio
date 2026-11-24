# SDD、BDD 與 TDD 分級開發流程 (SDD / BDD / TDD Workflow)

> **任務載入時機**：規劃新功能、撰寫規格、實作功能或修復 Bug 時必讀。

---

## 1. 核心定位：三者如何分工

為避免 AI Agent「猜測需求、漏掉邊界、改 A 壞 B」，同時防止小修改陷入過度文書儀式，三者各司其職：

| 流程 | 回答的問題 | 產出物 |
|---|---|---|
| **SDD（規格驅動）** | 做什麼、不做什麼、介面與資料契約為何？ | `docs/specs/NNN-<slug>.md` |
| **BDD（行為驅動）** | 從使用者角度，正常／邊界／錯誤情境怎麼驗收？ | Spec §5 的 `Given / When / Then` 場景 |
| **TDD（測試驅動）** | 程式單元如何保證正確並防止回歸？ | `tests/` 中的失敗測試 → 最小實作 → 重構 |

---

## 2. 兩軌分級流程（務實不臃腫）

### Track A：一般 Bug 修復 / 內部重構（直接走 TDD）
1. **RED**：使用 `tdd-bugfix` 建立失敗測試與靜態 fixture，執行測試**親眼確認失敗**。
2. **GREEN**：撰寫通過測試所需的最小實作，確認全套測試綠燈。
3. **REFACTOR**：維持全綠下重構並通過 `code-review-guard`。
4. 若發現值得記錄的坑或根因，補寫 `docs/known-issues/NNN-*.md`。

### Track B：新功能 / API 變更 / 跨模組改動（SDD ➔ BDD ➔ TDD）
1. **SDD（先定規格）**：複製 `docs/specs/_TEMPLATE.md` 為 `docs/specs/NNN-<slug>.md`，明確寫出目標、介面與 Out of scope。
2. **BDD（行為場景）**：在 Spec §5 用 `Given / When / Then` 寫出正常、邊界、錯誤場景。
   - **不強制**引入 Cucumber / Gherkin 等額外框架；直接將每個場景對應為 `tests/` 中的 `unittest` / `pytest` 測試函式（可用註解或 docstring 標註對應場景）。
3. **TDD（紅綠重構）**：依序把 BDD 場景轉成失敗測試（RED）→ 最小實作（GREEN）→ 清理重構與 `code-review-guard`（REFACTOR）。

---

## 3. 鐵律提醒

- **沒有先看到失敗的測試，就不准寫正式產品程式碼**（見 `.agents/skills/tdd-bugfix/SKILL.md`）。
- **Spec 與實作同步**：若實作過程中調整了介面或邊界行為，必須同步更新對應的 `docs/specs/NNN-*.md`。
