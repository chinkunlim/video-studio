---
name: project-auditor
description: >-
  Project completion integrity auditor: scans all conversation records (.agents/conversations/*-summary.md),
  handoff notes, ADRs, Known Issues and CHANGELOG.md before project completion or release.
  Ensures all architectural decisions and bug root causes discussed in sessions have permanent records,
  identifies lingering TODOs, and can automatically scaffold missing documentation.
---

# Project Auditor — 專案結案完整性審計

> **可執行工具**：[`scripts/audit_project_integrity.py`](scripts/audit_project_integrity.py)（`agentctl finish` 也會調用此項檢查）

## 1. 執行方式

標準審計報告：
```bash
python3 .agents/skills/project-auditor/scripts/audit_project_integrity.py
```

自動補建遺漏的 ADR 與 Known Issue 骨架檔：
```bash
python3 .agents/skills/project-auditor/scripts/audit_project_integrity.py --fix
```

JSON 輸出（供 CI 或自動化腳本解析）：
```bash
python3 .agents/skills/project-auditor/scripts/audit_project_integrity.py --json
```

嚴格模式（若有遺漏記錄則回傳非 0 退出碼）：
```bash
python3 .agents/skills/project-auditor/scripts/audit_project_integrity.py --strict
```

## 2. 審計項目

| 類別 | 檢查項目 | 判定規則 |
|---|---|---|
| **架構決策 (ADR)** | 對話紀錄中的架構決策是否已落實 | 盤點對話摘要（`*-summary.md`）中的「做了什麼與決策」，比對 `docs/adr/` 與 `DECISIONS.md`。凡重大技術選型、架構分層調整皆必須有對應 ADR。 |
| **已知問題 (Known Issues)** | 對話中修復的 Bug 根因是否已歸檔 | 盤點對話摘要中的「錯誤與根因」，比對 `docs/known-issues/` 與 `KNOWN_ISSUES.md`。凡找到根本原因之 Bug 皆必須有對應 Known Issue 紀錄。 |
| **未完成標記** | 檢測文件與摘要中是否有殘留 `TODO` | 掃描 `docs/**/*.md` 與 `.agents/conversations/`，列出尚未補齊的 `TODO`。 |
| **版本變更** | CHANGELOG 與實際 Commit 覆蓋度 | 檢查 `CHANGELOG.md` 之 `## [Unreleased]` 是否涵蓋本次專案的所有功能與修復項目。 |
| **自動補全 (`--fix`)** | 一鍵提取與骨架生成 | 自動自對話紀錄中萃取主旨與描述，調用 `adr-issue-tracker` 快速建立草稿紀錄檔與更新索引。 |
