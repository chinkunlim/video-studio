# Flask → FastAPI 改寫對照（開發模式）

> 適用：舊專案要繼續開發時（母版的 `scripts/migrate_project.py --mode develop`，或之後執行 `agentctl migration --develop`）。完成條件：程式與依賴裡完全沒有 Flask（`code-review-guard` 會擋下 `import flask`，`agentctl migration --verify` 會檢查 `pyproject.toml`）。

## 1. 先加依賴

```bash
uv add fastapi 'pydantic>=2.7' uvicorn
```

```bash
uv add --dev httpx
```

改寫完成、測試通過後再移除 Flask：

```bash
uv remove flask
```

## 2. 對照表

| Flask | FastAPI | 說明 |
|---|---|---|
| `app = Flask(__name__)` | `def create_app(config: AppConfig) -> FastAPI` | 用工廠函式，設定當參數傳入，方便測試 |
| `@app.route("/items", methods=["GET"])` | `@router.get("/items")` | 路由放在 `APIRouter`，`create_app()` 用 `include_router` 組合 |
| `@app.route("/items", methods=["POST"])` | `@router.post("/items", response_model=ItemOut)` | 回傳型別即 API 格式 |
| `request.get_json()` + 手動檢查 | `def create(body: ItemIn)` | `ItemIn` 是 pydantic 模型，格式錯誤自動回 422 |
| `request.args.get("q")` | `def search(q: str = "")` | 查詢參數直接寫成函式參數（有型別） |
| `/items/<int:item_id>` | `/items/{item_id}` + `item_id: int` | 路徑參數 |
| `jsonify(data)` | 回傳 pydantic 物件 / dict | 自動轉 JSON |
| `abort(404)` | `raise HTTPException(status_code=404, detail="...")` | |
| `Blueprint("x", __name__, url_prefix="/x")` | `APIRouter(prefix="/x")` | |
| `@app.before_request` / `g` | `Depends(...)` | 依賴注入（例如 DB session、目前使用者） |
| `render_template("page.html", ...)` | `Jinja2Templates(directory=...).TemplateResponse(...)` | 需要伺服器產生頁面時；純前端改放 `web/` |
| `app.send_static_file` / `static/` | `app.mount("/", StaticFiles(directory=WEB_DIR, html=True))` | 靜態檔放 `web/` |
| `flask_sqlalchemy` 的 `db.Model` / `db.session` | SQLAlchemy 2.0 `Base` + `session_scope()` + repository | 放 `adapters/db/`，見 `alembic/DB.md` |
| `Flask-Migrate` (`flask db upgrade`) | `uv run alembic upgrade head` | 舊 `migrations/versions/` 的 revision 搬到 `alembic/versions/` |
| `app.run(host="0.0.0.0")` | `uv run <專案>-server`（uvicorn，`HTTP_HOST=127.0.0.1`） | 不要綁 0.0.0.0 |
| `app.test_client()` | `fastapi.testclient.TestClient(create_app(test_config))` | |

## 3. 步驟（每個 Blueprint / 路由檔一批）

> 開發模式下 `import flask` 會被擋下，所以 Flask 路由檔**不要先 `git mv` 進 `src/`**：直接在 `src/<pkg>/entrypoints/http/` 寫新的 FastAPI router，同一個 commit 刪除 `legacy/` 的舊檔，並在 commit 訊息與 MIGRATION.md 註明「舊檔 → 新檔」對應（歷史仍可用 `git log -- legacy/舊檔` 查到）。

1. 為這組路由寫 pydantic 的 `XxxIn` / `XxxOut`（放 `entrypoints/http/schemas.py`）。
2. 業務邏輯移到 `services/`（純函式或類別，不碰 request / response），資料庫存取移到 `adapters/db/` 的 repository。
3. 用 `APIRouter` 改寫路由，只做：驗證輸入 → 呼叫 service → 轉成輸出格式。
4. 把舊的 Flask 測試改成 `TestClient`，並確認回應內容與狀態碼和舊版一致（API 行為不變）。
5. `python3 scripts/agentctl.py check` 與測試通過後 commit。
6. 全部路由改完：`uv remove flask`、刪除 Flask 的 app 檔，確認 `agentctl migration --verify` 通過。
