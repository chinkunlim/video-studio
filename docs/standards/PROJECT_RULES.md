# 本專案專屬規則 (PROJECT_RULES)

> 規則分兩層：`docs/standards/` 的其他文件是**所有專案通用**的規範（由專案模板提供，`agentctl update` 會更新）；
> 本檔是**只適用這個專案**的規則，由這個專案自己維護，模板更新時不會被覆蓋。每次開工都要讀。

## 1. 領域知識與術語

- **工作類型 (Job Types)**：
  - `extract`：純語音提取工作。從原始影片或音檔中萃取 48kHz 音訊、切分聲音樣本、或產生 Whisper 逐字稿與對齊時間軸。
  - `dub`：原片配音置換工作。保留原影片畫面，依講稿與時間軸重新合成配音與字幕，並替換原音軌。
  - `generate`：完整影音生成工作。依講稿、PowerPoint 簡報或高解析度海報，生成配音、字幕並渲染輸出全新影片。
- **工作區角色分層結構**：依 [ADR-006](../../docs/adr/006-data-dir-role-layout-and-releases.md) 位於 `DATA_DIR` 各角色目錄下（以 `<job-name>` 關聯）：
  - `input/<job-name>/`：使用者或原始專案素材（唯讀，程式不可直接寫入）。
  - `needs_review/<job-name>/`：AI 或自動工具起草之草稿、試聽檔與 `review_history/`（需由使用者審閱後透過 `approve` 移入 `input/`）。
  - `work/<job-name>/`：運算中間暫存區（如單句 takes、中間切片，可隨時清理重建）。
  - `state/<job-name>/job.toml`：各工作的設定檔（含 `type`、`title`、配音與字幕參數）。
  - `output/<job-name>/v1, v2, ...`：驗收產出的成品版本庫，採嚴格版本遞增編號，永不覆蓋既有產物。
  - `output/<job-name>/releases/<vN>/`：該工作唯一最新定稿交付區（僅硬連結 `.mp4` 與 `subtitles_{youtube,vlc}.srt`，發布新版時舊定稿自動退回未發布狀態）。
- **語音與字幕技術名詞**：
  - `Voicebox`：本機語音合成服務，綁定 `http://127.0.0.1:17493`，需搭配目標講者參考音訊樣本執行聲音複製。
  - `Take`：單行講稿錄音版本，檔名格式為 `line_NNN_vM.wav`，選定最佳版本後以符號連結（symlink）至 `line_NNN.wav`。
  - `cues.tsv`：講稿每行在原影片或投影片中的對齊時間點（格式：`slide\tline\tstart\tend\ttext`）。
  - `vocabulary.tsv`：專有名詞發音校正表，區分字幕顯示與 TTS 念法（例如 `BART` 念為「霸特」）。

## 2. 本專案特有的規則

- **本機服務安全性**：Voicebox、Open WebUI 等所有內部 API 與微服務呼叫，一律只連接 `127.0.0.1`，禁止使用 `localhost` 或綁定公開介面。
- **先聲後影時間基準**：在 `generate` 模式下，影片各段落長度必須由配音（`narration.wav`）實際量測秒數主導，畫面切換與鏡頭動畫依配音長度延展。
- **草稿變更安全流程**：任何由 Open WebUI 或自動化指令起草的檔案（如 `script.md`、`scenes.toml`），必須先寫入 `needs_review/<job-name>/`，待使用者檢核並明確確認後，再執行 `approve` 移入 `input/`。
- **字幕繁簡轉換規範**：字幕檔案（SRT、VTT、ASS）一律透過 OpenCC 轉換為繁體中文（臺灣標準），講稿原始文字則保留原樣。
- **成品版本遞增**：所有透過 `finish_video` 渲染之成品目錄 `output/v<N>/`，必須自動偵測最新版號並 `+1` 寫入新資料夾，保留歷史紀錄。

## 3. 和通用規範不同的例外（要寫理由）

- **Open WebUI Tool 對外方法參數數量例外**：
  - `video_studio.adapters.openwebui_tool.Tools.create_job`（5 參數）與 `set_vocabulary`（7 參數）：
  - 理由：Open WebUI Tool 需將扁平化型別參數直接暴露給 LLM Function Calling Schema 解析，若封裝為 DTO 會影響模型參數填寫；此處維持扁平參數（Code Review Guard 僅顯示 Warning，不阻擋建置）。原舊專案遷移之 `services.video.engine.{media,poster,pptx}` 已完成重構，不再需要例外寬限。

## 4. 禁止事項

- **嚴禁將影音媒體檔案存入 Git**：所有影片（`.mp4`）、大容量音檔（`.wav`）、簡報檔（`.pptx`）與暫存切片必須放在 `DATA_DIR`，禁止放入 Git 追蹤路徑。
- **嚴禁覆寫 `input/` 原始檔案**：程式或 AI 不得在未經備份與核可的情況下直接修改 `input/` 內的任何原始檔案。
- **嚴禁覆寫已生成的 `output/v<N>/` 成品**：每次輸出新版成品時必須產生新的版本號目錄。
- **嚴禁向外部未授權之公有雲 API 傳輸語音原始檔**：聲音複製（Voicebox）、音訊提取與 Whisper 轉錄一律於本機端執行；若使用者明確設定 `[voice] engine = "edge-tts"`，僅傳送純文字講稿至微軟 TTS（不傳送任何個人語音樣本，見 ADR-004）。
