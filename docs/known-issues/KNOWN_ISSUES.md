# 已知問題 (Known Issues)

記錄「踩過的坑」：值得記住的 bug、外部服務的怪行為、環境問題，以及它們的根本原因與修正方式。
除錯時先查這裡：`grep -rn "關鍵字" docs/known-issues .agents/conversations`（後者只在本機）。

- 新增：`python3 .agents/skills/adr-issue-tracker/scripts/tracker_cli.py --add-issue <slug> --title "標題" --summary "錯誤訊息" --agent <名字>`
- 格式：[`_TEMPLATE.md`](_TEMPLATE.md)；在修正的程式碼註解加 `Refs: ISSUE-NNN`，並寫防回歸測試。
- 狀態：🔴 未解決 (open) → 🟡 已規避 (mitigated) → 🟢 已根治 (resolved)

> 命名規則：`_TEMPLATE.md` 是新增紀錄時要照著寫的範本；紀錄檔命名為 `NNN-<slug>.md`。整個專案只有根目錄一份 `README.md`。

## 總表

| ISSUE | 狀態 | 標題 | 現象 | 程式與測試 |
|---|---|---|---|---|
| [ISSUE-001](001-media-contact-sheet-missing.md) | 🟢 已根治 (Resolved) | 影片驗收驗證時缺少 video_contact_sheet.jpg 產出邏輯 | media.check 函式執行驗收時因缺少影格網格縮圖生成，造成驗收流程回傳錯誤 | `services/video/engine/media.py` / `test_workflow_video.py` |
| [ISSUE-002](002-host-python-tomllib-detection.md) | 🟢 已根治 (Resolved) | 舊版主機 Python 環境下執行 check 誤報 tomllib 未宣告依賴 | 當使用系統 Python 3.9 執行 agentctl check 時，因標準函式庫尚未內建 tomllib，導致 setup_env.py 誤判其為第三方未宣告套件 | `.agents/bin/setup_env.py` |
