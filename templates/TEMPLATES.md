# 范本

建立新工作时，`init` 指令会依工作类型把范本复制到 `<工作>/input/`（`job.toml` 放在工作资料夹最上层）。
每份范本开头都写了用途和填写规则，并附完整范例。设计说明见 [docs/DESIGN.md](../docs/DESIGN.md)。

| 档案 | 工作类型 | 必填 | 内容 |
|---|---|---|---|
| `extract/job.toml` | extract | ✔ | 影片档名、范围、要不要声音样本／逐字稿／字幕 |
| `dub/job.toml` | dub | ✔ | 影片、讲稿、声音档、时间塞不进去时的处理方式、字幕、输出 |
| `dub/input/script.md` | dub | 有讲稿时 | 讲稿格式（同 generate） |
| `dub/input/cues.tsv` | dub | 原片没有人声时 | 每一行讲稿在原片的开始时间 |
| `generate/job.toml` | generate | ✔ | 要用哪些素材、画面方式、声音档、字幕、输出 |
| `generate/input/script.md` | generate | 有讲稿时 | 投影片、段落、`[click]`、`{{词汇}}` |
| `generate/input/brief.md` | generate | 没有讲稿也没有素材时 | 主题、观众、长度、重点、资料来源、禁止事项 |
| `generate/input/scenes.toml` | generate | 选填（没有会自动起草） | 每一幕的画面来源、海报区域、提示栏、画面文字、插播 |
| `shared/vocabulary.tsv` | 共用 | ✔ | 特殊词的字幕显示与 Voicebox 念法 |

共同规则：
- 栏位名称固定用英文，**不要改**；值可以是中文。
- 文字值加双引号；没有就写 `""`，不要整行删掉。
- 档名都是 `input/` 里的档名，不用写完整路径。
- 填完执行检查指令；格式错误会说出哪个档案、第几行或第几幕、哪个栏位、该怎么改。
