# 開發環境與依賴管理規範 (Environment & Dependencies)

> **AI Agent 載入時機**：要安裝、升級或移除任何套件，要執行程式或工具，或要設定本機服務之前，**必須閱讀並遵守本文件**。
>
> **原則**：主機只放「整台電腦共用一份」的工具（git、uv、nvm、gh、brew 安裝的系統程式）；專案用到的一切都裝在專案資料夾內，並由鎖定檔固定版本。主機本身的安裝步驟見 `00 init_dev_env` 的 macOS SOP，本文件只規範「在專案裡怎麼做」。

---

## 1. 指令對照表

| 要做的事 | 使用 | 禁止 |
|---|---|---|
| 新增 Python 套件 | `uv add <套件>` | `pip install`、`pip install --user`、`sudo pip`、`brew install python-<套件>` |
| 新增 Python 開發工具（測試、lint） | `uv add --dev <套件>` | 全域安裝 ruff / mypy / pytest |
| 移除 Python 套件 | `uv remove <套件>` | 手動改 `.venv` |
| 執行 Python 程式 / 測試 | `uv run python ...`、`uv run <指令>` | 用系統 `python3` 跑專案程式、`source .venv/bin/activate` 後忘記離開 |
| 安裝全部依賴（換電腦） | `python3 scripts/agentctl.py setup --install` | 升級系統 pip、`pip install -r requirements.txt` 到全域 |
| 改 Python 版本 | 改 `.python-version` 後 `uv sync` | `brew install python@3.x` 給專案用 |
| 常用 CLI 工具（非專案依賴） | `uv tool install <工具>` | `pip install <工具>` 到全域 |
| 新增 Node 套件 | `pnpm add <套件>`、開發工具 `pnpm add -D <套件>` | `npm install`、`npm install -g`、`yarn` |
| 執行專案內的 Node 工具 | `pnpm exec <工具>`、`pnpm run <script>` | `npx <工具>`、全域安裝 |
| 臨時執行一次 Node 工具 | `pnpm dlx <工具>` | `npx <工具>` |
| 切換 Node 版本 | 在專案內 `nvm use`（讀 `.nvmrc`） | 改系統 Node |
| 啟用 pnpm | `corepack enable`（版本由 `packageManager` 決定） | `npm install -g pnpm`、`pnpm setup` |
| 系統工具（ffmpeg、libpq…） | 寫進專案的 `Brewfile`，`brew bundle` 安裝 | 不記錄就 `brew install` |
| 本機服務 | 綁 `127.0.0.1`，網址 `http://127.0.0.1:<port>` | 綁 `0.0.0.0`、網址寫 `localhost` |
| 手機 App 測試 | 模擬器（Android 用 `adb reverse`）；實機用 `pnpm tunnel` | `expo start --lan`、後端綁 `0.0.0.0` |

任何 `sudo` 指令、改動家目錄設定檔（`~/.zshrc`、`~/.zprofile`）、或全域安裝，Agent 都必須先徵求使用者同意。

---

## 2. 為什麼不會重複存放依賴（uv 與 pnpm 的共用倉庫）

| | Python（uv） | Node（pnpm） |
|---|---|---|
| 共用倉庫 | `~/.cache/uv` | `~/Library/pnpm/store` |
| 專案內位置 | `.venv/` | `node_modules/` |
| 連結方式 | macOS 預設 APFS clone（寫入時才複製），Linux / Windows 用硬連結 | 硬連結（content-addressable store） |
| 直譯器 / 執行環境 | uv 下載的 Python 放在 `~/.local/share/uv/python`，所有專案共用 | nvm 的 Node 放在 `~/.nvm/versions/node`，依 `.nvmrc` 切換 |
| 鎖定檔（要 commit） | `uv.lock`、`.python-version` | `pnpm-lock.yaml`、`.nvmrc`、`package.json` 的 `packageManager` |

- 同一版套件在硬碟上只有一份，10 個專案共用；刪掉某個專案的 `.venv/` 或 `node_modules/` 不影響其他專案。
- 限制：共用倉庫和專案必須在同一個磁碟。專案放在外接硬碟時會改成複製（只是佔空間）。
- pip 不支援這種共用，每個 venv 都會完整複製一份，所以專案內不使用 pip。

清理不再使用的快取：

```bash
uv cache prune
```

```bash
pnpm store prune
```

---

## 3. Python 規則

1. 版本寫在 `.python-version`（預設 3.11），`pyproject.toml` 的 `[tool.uv] python-preference = "only-managed"` 讓 uv 只用自己下載的 Python，不會用到系統或 Homebrew 的 Python。
2. `uv.lock` 必須 commit。CI 用 `uv sync --locked`，lock 和 `pyproject.toml` 不一致會失敗。
3. 測試、lint、型別檢查都在 `.venv` 裡執行：`uv run python -m unittest ...`、`uv run ruff ...`、`uv run mypy`。
4. 框架腳本（`scripts/*.py`、`.agents/`）只用 Python 內建模組，可以直接用 `python3` 執行，不需要也不能替它們安裝套件。
5. 不要用 `sudo uvx` 或 `sudo uv`：會讓 `~/.cache/uv` 出現 root 擁有的檔案（`agentctl doctor` 會檢查）。
6. 套件的 import 名稱和 PyPI 名稱不同時（例如 `import yaml` → `PyYAML`），先確認再 `uv add`；`python3 scripts/agentctl.py setup --check` 會列出還沒宣告的 import。

---

## 4. Node 規則（pnpm 取代 npm）

1. 版本：`.nvmrc`（Node major）+ `package.json` 的 `"packageManager": "pnpm@x.y.z"`；corepack 會在每台電腦使用同一版 pnpm。
2. `pnpm-lock.yaml` 必須 commit。CI 用 `pnpm install --frozen-lockfile`。
3. `package.json` 的 `"engines": {"npm": "please-use-pnpm"}` 加上同資料夾 `.npmrc` 的 `engine-strict=true`，會讓 `npm install` 在寫入任何檔案前就停止（pnpm 不受影響）。
4. pnpm 預設不執行依賴套件的安裝腳本（安全設計）。少數套件（例如 esbuild、sharp）需要時，在專案內執行一次並 commit 產生的設定：

```bash
pnpm approve-builds
```

5. 不要在家目錄執行 `pnpm init` / `pnpm install`（會產生 `~/package.json` 影響所有工具判斷，`agentctl doctor` 會檢查）。

### 舊專案從 npm 轉成 pnpm

1. 從 `package-lock.json` 產生 `pnpm-lock.yaml`（保留原本鎖定的版本）：

```bash
pnpm import
```

2. 刪除 npm 的鎖定檔與舊的 `node_modules`：

```bash
rm -rf package-lock.json node_modules
```

3. 重新安裝：

```bash
pnpm install
```

4. 在 `package.json` 加上 `packageManager`（版本用 `pnpm -v` 的結果），再跑一次測試確認，然後 commit。

---

## 5. 系統工具（brew）與 `Brewfile`

brew 管的是整台電腦一份的程式，不會在專案裡重複存放，但必須讓其他電腦知道專案需要哪些。

1. 專案需要系統工具時（例如影片處理需要 `ffmpeg`），在專案根目錄建立 `Brewfile`：

```ruby
brew "ffmpeg"
```

2. 安裝（新電腦或新加了工具時）：

```bash
brew bundle --file Brewfile
```

3. `agentctl doctor` 會用 `brew bundle check` 檢查是否都已安裝（只檢查、不安裝）。
4. 只放專案真的需要的系統程式；Python / Node 套件不放 `Brewfile`。

---

## 6. 本機服務

1. 開發伺服器、API、預覽一律綁 `127.0.0.1`：例如 `--host 127.0.0.1`、`--bind 127.0.0.1`。
2. 設定檔和程式中的網址寫 `http://127.0.0.1:<port>`，不要寫 `localhost`（macOS 偶發名稱解析失敗）。
3. 本機 Ollama：`OLLAMA_BASE_URL=http://127.0.0.1:11434`（寫在 `.env`，由 config 層讀取）。
4. 上傳到本機模型或外部服務的內容一律視為不可信任；含金鑰、個資或私有原始碼的內容不要送到外部服務。
5. **手機 App（Expo，`--with mobile`）**：手機連不到 Mac 的 `127.0.0.1`，所以：
   - **預設在模擬器測試**：iOS Simulator 直接用 `127.0.0.1` 連 Mac；Android 模擬器先執行 `adb reverse tcp:<port> tcp:<port>`，App 裡一樣寫 `http://127.0.0.1:<port>`。
   - **真的手機只用 tunnel**：`pnpm tunnel`（= `expo start --tunnel`，`@expo/ngrok` 是 `mobile/` 的 devDependency，不全域安裝）。tunnel 只轉送 App 程式碼；需要後端的功能在模擬器測試。
   - **禁止**為了手機把開發伺服器或後端改綁 `0.0.0.0` 或用 `--lan`；真的需要實機連後端時先問使用者。
   - 系統工具：Xcode 從 App Store 安裝；Android Studio、watchman 寫在 `Brewfile`（`brew bundle --file Brewfile`）。
   - `mobile/pnpm-workspace.yaml`：pnpm 對「剛發布的套件」寫入的版本例外，要 commit；新增的例外要確認是官方套件。
   - `EXPO_PUBLIC_*` 變數會打包進 App，不放任何秘密；簽章檔（`*.jks`、`*.p8`、`*.p12`、`*.mobileprovision`）放 `~/.config/<專案>/`，pre-commit 會擋。

---

## 7. 資料資料夾（DATA_DIR）

- 每個專案在 `.env` 設定 `DATA_DIR`。預設是**相對路徑** `../../projects-data/<專案>`（從專案資料夾算起：`projects/<專案>` 旁邊的 `projects-data/<專案>`），整個資料夾一起搬移時不用改設定。大型資料可以放外接硬碟，這時寫絕對路徑，例如 `/Volumes/<硬碟>/projects-data/<專案>`。
- **不要把路徑寫死在程式裡**：程式只透過 config 拿 `DATA_DIR`；相對路徑一律從專案資料夾解析，不受執行指令時所在的資料夾影響。
- **專案 `.env` 的 `DATA_DIR` 優先於終端機的環境變數**：Open WebUI 的安裝步驟會在 `~/.zshrc` 加 `export DATA_DIR="$HOME/open-webui-data"`，這個通用名稱不能把專案的資料導到別處。啟動 log 與 `agentctl doctor` 都會顯示實際使用的資料夾（doctor 也會提示忽略了哪個終端機設定）。其他設定（例如 `LOG_LEVEL`）仍是暫時設定的環境變數優先。
- 建立標準子資料夾並檢查設定（`DATA_DIR` 在專案資料夾內時會警告）：

```bash
python3 scripts/agentctl.py doctor --fix
```

- 換電腦：git 只帶走程式與文件；資料要另外複製 `DATA_DIR` 整個資料夾，並在新電腦的 `.env` 設定路徑。
- 備份：定期備份 `DATA_DIR`（它不在 git 裡）。

## 8. 憑證檔（OAuth JSON、service account、clasp 登入）

- API key / token：放 `.env`。
- 憑證「檔案」：放 `~/.config/<專案>/`（不在專案內、也不在 `DATA_DIR`），權限只給自己：

```bash
chmod 600 ~/.config/<專案>/credentials.json
```

- 路徑寫在 `.env`（例如 `GOOGLE_CREDENTIALS_FILE=~/.config/<專案>/credentials.json`），由 config 層讀取。

## 9. macOS 原生工具優先（選用）

在 Apple Silicon Mac 上規劃方案時，先評估系統內建或原生加速的工具，再考慮大型跨平台套件，並說明比較：

| 需求 | 先評估 | 再考慮 |
|---|---|---|
| OCR 文字辨識 | Apple Vision（`VNRecognizeTextRequest`，零依賴、使用神經網路引擎） | Tesseract、PaddleOCR |
| 圖片轉檔 / 縮放 | `sips`、Core Graphics | Pillow、ImageMagick |
| PDF 解析 / 渲染 | PDFKit / Quartz | 依需求選 PyMuPDF 等 |
| 模型推理加速 | Metal / MPS、Core ML | 純 CPU 推理 |
| 本機大型模型 | Ollama（`http://127.0.0.1:11434`），呼叫前先過硬體檢查（`--with ollama`） | 雲端 API |
