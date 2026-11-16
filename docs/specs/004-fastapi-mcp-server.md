# SPEC-004: FastAPI HTTP API、MCP Server 與輕量管理網頁

- **狀態**: Implemented
- **日期**: 2026-11-16
- **相關模組**: `entrypoints/api.py`, `entrypoints/mcp_server.py`, `entrypoints/schemas.py`, `entrypoints/static/index.html`

## 1. 目標

遵循核心規則 13（「一組 `services`、三個入口」），讓 `video-studio` 同時透過以下三個入口提供服務，並維持本機隔離（`http://127.0.0.1:8772`）：
1. **HTTP OpenAPI 介面**（供 Open WebUI 工具伺服器與前端呼叫，`/docs` 提供 Swagger 文件）。
2. **MCP Server**（Streamable HTTP `/mcp` 與 Stdio `video-studio-mcp`，供 Claude Code、Antigravity、OpenCode、Open WebUI 呼叫）。
3. **輕量管理網頁**（`/`，提供工作狀態總覽、健康檢查與 `/docs` 連結）。

## 2. 權限與安全設計

- **唯讀操作**（直接執行）：`list_jobs`、`check_job`、`list_lines`、`scan_vocab`、`list_vocab`、`video_timing`、`video_check`。
- **變更資料操作**（MCP 工具強制要求 `confirm: bool = False`，未確認時回傳預覽說明並拒絕執行）：
  - `init_job`、`approve_file`、`set_vocab`、`audition_line`、`pick_take`、`build_narration`、`draft_scenes`、`render_poster_video`、`mux_external_video`、`extract_audio`。
- **本機防護中介層**：僅允許 `127.0.0.1` / `localhost` 的 `Host` 標頭，且非唯讀請求的 `Origin` 僅接受 `HTTP_ALLOWED_ORIGINS`。
- **Stdout 禁令**：`entrypoints/mcp_server.py` 在 Stdio 模式下禁止任何 `print()`，所有日誌寫入 stderr 或 `DATA_DIR/logs/`。
