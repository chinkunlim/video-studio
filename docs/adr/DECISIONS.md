# 架構決策 (Architecture Decision Records)

記錄「為什麼這樣設計」：每個重要的架構取捨一個檔案，之後的人（或 Agent）不用再猜。

- 新增：`python3 .agents/skills/adr-issue-tracker/scripts/tracker_cli.py --add-adr <slug> --title "標題" --agent <名字>`
- 格式：[`_TEMPLATE.md`](_TEMPLATE.md)；在相關程式碼註解加 `Refs: ADR-NNN`。
- 決策被推翻時不要刪檔，把狀態改成 `Superseded by ADR-NNN`。

> 命名規則：`_TEMPLATE.md` 是新增紀錄時要照著寫的範本；紀錄檔命名為 `NNN-<slug>.md`。整個專案只有根目錄一份 `README.md`。

## 總表

| ADR | 標題 | 狀態 | 日期 | 相關程式 |
|---|---|---|---|---|
| [ADR-001](001-openwebui-adapter-architecture.md) | Open WebUI 工具配接與本地 AI 服務隔離架構 | Accepted | 2026-10-22 | `adapters/openwebui_tool.py` |
| [ADR-002](002-workspace-isolation-and-review.md) | 工作區結構隔離與素材審核（Review/Approve）機制 | Accepted | 2026-10-22 | `services/common/job.py` |
| [ADR-003](003-dual-video-rendering-engines.md) | 影片合成渲染引擎之雙模式設計（PowerPoint 動畫與海報鏡頭動畫） | Accepted | 2026-10-22 | `services/video/engine/` |
