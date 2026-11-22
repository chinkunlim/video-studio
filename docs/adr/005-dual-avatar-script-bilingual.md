# ADR-005：Dual-Engine Avatar Presenter, AI Script Drafting, and Bilingual Subtitles

- **狀態**：Accepted <!-- Proposed | Accepted | Superseded by ADR-NNN -->
- **日期**：2026-11-16
- **Agent**：`Antigravity`
- **任務**：`TASK-012`

## 1. 背景與問題

1. **Avatar 主講人疊加需求**：影片簡報除了純簡報畫面與配音外，使用者希望可在角落呈現主講人畫面（如人物頭像微動或 AI 對嘴），同時不想因未安裝龐大的 GPU 推論模型（如 SadTalker）而阻擋基本流程。
2. **AI 講稿起草與雙語字幕**：需要從 `input/` 的 PDF/PPTX/brief 自動整理「一句一行」口播講稿至審核區，並支援產生雙語對照字幕（SRT/ASS）。

## 2. 評估過的方案

| 方案 | 優點 | 缺點 |
|---|---|---|
| A：單一重型模型（僅支援 SadTalker） | 嘴型同步較逼真 | 依賴獨立 Python 環境與多 GB 權重，無安裝時完全無法產出 Avatar |
| B：雙引擎（Route B FFmpeg 輕量動畫 + Route A 隔離 SadTalker）與自動化講稿/雙語管線 | 零額外模型即可立即出片（Route B），可選升級 SadTalker；AI 講稿先落入審核區且支援雙語字幕 | 需維護兩條 Avatar 渲染路徑與 `script_bilingual.tsv` 對齊邏輯 |

## 3. 決策與理由

Support both Route B (lightweight FFmpeg animated presenter overlay) and Route A (isolated SadTalker lip-sync engine under `DATA_DIR/models/SadTalker`) behind `services/video/engine/avatar_engine.py` and `services/video/avatar_overlay.py`; add AI script drafting to `needs_review/<job>/script.md` (`services/script_drafter.py`) and bilingual subtitle translation/formatting (`services/narrate/core/bilingual.py` and `subtitles.py`).

## 4. 影響與代價

- **正面影響**：不依賴重型 GPU 模型即可於本機產出含主講人 PiP 的簡報影片；SadTalker 安裝於 `DATA_DIR/models/SadTalker` 的獨立 `.venv`，不污染專案 `uv` 環境。
- **代價與維護注意**：若啟用 Route A，使用者須自行透過設定頁指定 `SADTALKER_DIR` 並備妥 checkpoints；雙語字幕需確保譯文與 `script.md` 行數 1-to-1 對應，由 `parse_bilingual_output` 補齊與防護。
