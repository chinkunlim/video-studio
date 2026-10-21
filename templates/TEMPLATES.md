# 工作範本說明 (TEMPLATES)

建立新工作時，`video-studio job init <type> <name>` 指令會依工作類型把範本複製到工作目錄 `<workspace>/<type>/<name>/`（`job.toml` 放在工作資料夾最上層，其餘素材放在 `input/`）。

每份範本開頭都寫了用途和填寫規則，並附完整範例。規格說明見 [`docs/specs/003-templates-and-inputs.md`](../docs/specs/003-templates-and-inputs.md) 與 [`docs/architecture/ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md)。

## 範本清單

| 檔案 | 工作類型 | 必填 | 內容說明 |
|---|---|---|---|
| `extract/job.toml` | extract | ✔ | 影片檔名、時間範圍、是否產出聲音樣本／Whisper 逐字稿／字幕 |
| `dub/job.toml` | dub | ✔ | 影片、講稿、聲音樣本、時間長度超限時的處理策略、字幕樣式、輸出格式 |
| `dub/input/script.md` | dub | 有講稿時 | 講稿分頁與行格式（同 generate 模式） |
| `dub/input/cues.tsv` | dub | 原片無人聲時 | 每一行講稿在原片畫面中的精確開始時間點 |
| `generate/job.toml` | generate | ✔ | 素材來源（簡報或海報）、畫面動畫方式、聲音檔、字幕樣式、輸出設定 |
| `generate/input/script.md` | generate | 有講稿時 | 投影片分頁、段落、`[click]` 動畫觸發點、`{{詞彙}}` 標註 |
| `generate/input/brief.md` | generate | 無講稿與素材時 | 主題、觀眾對象、預期長度、重點摘要、資料來源、禁止事項 |
| `generate/input/scenes.toml` | generate | 選填（無則自動起草） | 每一幕的畫面來源、海報裁切區域、提示欄文字、畫面浮水印與插播 |
| `shared/vocabulary.tsv` | 共用 | ✔ | 特殊專有名詞的字幕繁體顯示與 Voicebox TTS 發音念法對照 |

## 填寫與維護共同規則

1. **欄位名稱固定為英文**，**請勿修改欄位名稱**；欄位值可為中文。
2. **文字值必須使用雙引號**；若該欄位暫時無值請保留空字串 `""`，請勿直接刪除該行。
3. **檔案路徑皆為相對於 `input/` 的相對檔名**，不需填寫絕對路徑。
4. 填寫完成後可執行檢查指令 `video-studio job check <job-name>`；若有格式錯誤，系統會清楚指出是哪個檔案、第幾行或第幾幕、哪個欄位有誤以及具體的修復建議。
