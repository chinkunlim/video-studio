---
name: api-adapter-scaffold
description: >-
  Scaffolds new external service adapters in src/<pkg>/adapters/<category>/ (LLM providers, search engines,
  messaging platforms) with pure parser functions, immutable DTOs, ProviderError wrapping,
  and offline fixture unit tests. Activate when integrating a new external API.
---

# API Adapter Scaffold — 外部服務防腐層與備援擴充器

> **可執行工具**：[`scripts/scaffold_adapter.py`](scripts/scaffold_adapter.py)

當需要串接新的外部 API（新模型供應商、新搜尋引擎、新通訊管道）時，執行 `scaffold_adapter.py` 一鍵產生符合 **SOLID 開放封閉原則 (OCP)**、**里氏替換原則 (LSP)** 與 **離線樣本測試** 的標準結構。

---

## 1. 自動調用 Python 工具 (`scaffold_adapter.py`)

一鍵產生 src/<pkg>/adapters/<category>/<name>_adapter.py + tests/fixtures/<name>_sample.json + tests/test_<name>_adapter.py

```bash
python3 .agents/skills/api-adapter-scaffold/scripts/scaffold_adapter.py \
  --category search \
  --name brave_search
```
