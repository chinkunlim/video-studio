---
name: compliance-scanner
description: >-
  Comprehensive project compliance & architecture scanner: audits framework version synchronization
  with the template, unidirectional architecture layering, code review guard rules, dependency graph
  cleanliness, external DATA_DIR isolation, offline test passing, and core iron laws (including Rule 14
  one-click installation and seamless updates). Activate whenever the user asks about project architecture
  compliance, template synchronization, framework health check, or overall project audit.
---

# Compliance Scanner — 專案架構合規與母版同步全面掃描

> **可執行工具**：[`scripts/scan_compliance.py`](scripts/scan_compliance.py)（或統一入口 `python3 scripts/agentctl.py scan`）

當使用者在任何專案對話中詢問以下問題時，**主動調用本 Skill 進行全方位掃描**：
- 「專案架構符合規範嗎？」、「檢查一下架構」、「架構合規嗎？」
- 「有沒有跟上母版更新？」、「專案是否為最新版本？」
- 「專案健檢」、「全面掃描專案」、「檢查所有規範落實情況」

---

## 1. 執行方式

### 1.1 標準全面掃描（終端可讀報告）
```bash
python3 scripts/agentctl.py scan
# 或
python3 .agents/skills/compliance-scanner/scripts/scan_compliance.py
```

### 1.2 快速掃描（略過跑完整測試套件）
```bash
python3 scripts/agentctl.py scan --skip-tests
```

### 1.3 掃描並自動安全修復（Auto-Fix）
自動執行 `doctor --fix`、`sync` 與 `tree`：
```bash
python3 scripts/agentctl.py scan --fix
```

### 1.4 JSON 機器讀取模式（供 Agent / CI 流程）
```bash
python3 scripts/agentctl.py scan --json
```

---

## 2. 6 大全方位審查維度

| 維度 | 審查內容 | 判定標準 |
|---|---|---|
| **1. 框架與母版同步** | 檢查 `.agents/framework.lock` 版本與母版差異 | 比對專案框架版本（如 `v3.5.0`），預覽是否有未套用的母版框架或規範更新。 |
| **2. 分層與代碼規範** | 調用 `code-review-guard` 與 `agentctl check` | 檢查函式完整註解（用途與參數說明）、行數上限（$\le 40$ 行）、巢狀層級（$\le 3$）、禁止反向引用上層、禁止黑名單套件。 |
| **3. 依賴拓撲與圖譜純淨** | 調用 `build_graph.py` 分析依賴拓撲 | 檢測模組是否有循環依賴（Circular Imports）、分層穿透或孤島模組；檢查 `.graphifyignore` 是否正確排除第三方噪聲。 |
| **4. 環境隔離與 DATA_DIR** | 調用 `doctor.py` 檢查本機運行環境 | 驗證 `DATA_DIR` 是否嚴格置於專案目錄外、憑證檔權限（`chmod 600`）、`.env.example` 存在性與 Git Hooks 啟用狀態。 |
| **5. 核心鐵律防線落實** | 檢查各項核心約束（尤其是鐵律 14 與 13） | **【鐵律 14】**：是否具備一鍵安裝腳本（`install.sh` / `agentctl setup`），`README.md` 是否具備安裝與更新說明；**【鐵律 13】**：Web/API 需具備 FastAPI 與 MCP 雙入口；**【鐵律 9】**：本機服務嚴禁綁定 `0.0.0.0`。 |
| **6. 離線測試套件** | 執行專案 `[commands] test` 離線測試 | 確保單元測試與整合測試 100% 斷網通過。 |

---

## 3. 評分與改善指引

掃描器會計算綜合評分（0~100）並給出等級評定：
- **A+ (95~100)**：完全合規，架構與規範落地無瑕疵。
- **A (85~94)**：良好，僅有輕微風格建議。
- **B (70~84)**：需調整，存在少數規範違規或版本落後。
- **C / F (<70)**：存在嚴重違規（如循環依賴、破壞分層、測試失敗）。

報告結尾會附帶明確的下一步改善動作指令，引導使用者或 Agent 快速完成修復。
