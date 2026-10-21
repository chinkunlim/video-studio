# split-voice：讲稿配音工具

| 工具 | 做什么 | 需要 |
|---|---|---|
| **工具一 `extract_audio/`** | 从影片（mp4）提取音档；也可以切成声音样本，给 Voicebox 建复制声音 | ffmpeg |
| **工具二 `narrate/`** | 讲稿 → Voicebox 配音 → 拼接 → 字幕（YouTube / PowerPoint / VLC，繁体中文） | Voicebox、ffmpeg、uv（自动安装 faster-whisper、opencc） |
| **工具三 `video/`** | 配音 + 画面 → 完整影片：PowerPoint（保留动画）或海报（镜头移动 + 提示栏），烧字幕、验收 | ffmpeg、PowerPoint（PowerPoint 方式）；见 [video/README.md](video/README.md) |

以 Voicebox 生成为主，不再把自己的录音拼进配音（音色和语气接不起来）。

**在 Ollama + Open WebUI 里使用**：把 [`openwebui/split_voice_tool.py`](openwebui/split_voice_tool.py) 加成 Open WebUI 的工具，就能在对话里直接操作，出错会回报原因。安装与用法见 [openwebui/README.md](openwebui/README.md)。

## 程式和资料分开放

所有档案和资料夹都用英文命名；讲稿、字幕的**内容**照样是中文。整体设计（三种工作、所有素材组合、确认关卡）见 [docs/DESIGN.md](docs/DESIGN.md)。

**程式**（换电脑时复制这个；可以放进 Git）：

```text
~/Desktop/projects/Old/split-voice/
├── sv.py                         工作管理：list / init / check / approve
├── common/                       共用模组：找工作、检查输入档
├── templates/                    每一种输入档的范本（job.toml、script.md、scenes.toml、brief.md、cues.tsv、vocabulary.tsv）
├── extract_audio/extract.py      工具一
├── narrate/                      工具二：narrate.py、core/、config.toml、traditional_fixes.tsv
├── video/                        工具三：video.py、engine/、config.toml、README.md
├── openwebui/                    Open WebUI 工具与说明
└── docs/DESIGN.md                设计
```

**工作区**（你的资料；自己备份）。位置设在 `narrate/config.toml` 的 `[paths] workspace`，或用环境变数 `SPLIT_VOICE_WORKSPACE`：

```text
~/Desktop/split-voice-workspace/
├── shared/
│   ├── vocabulary.tsv            词汇表（所有工作共用）
│   ├── voice/samples/            建立复制声音 My Voice 用的样本
│   ├── vocab_tries/              词的试听档
│   └── demos/                    示范影片
├── extract/<name>/               只提取声音
├── dub/<name>/                   给影片，用 Voicebox 重新配音
└── generate/<name>/              完整生成（讲稿、pptx、海报…任意组合）
    ├── job.toml                  这份工作的设定：标题、输入档名、声音、字幕、影片方式
    ├── input/                    你给的素材（templates/ 里是范例）
    ├── review/                   工具起草、等你确认的档案（确认后用 sv.py approve 移进 input/）
    ├── work/                     中间档：takes/、takes.json（每句选用的音档，不要删）、log
    └── output/v1, v2, …          成品，每次产生新版本，不覆盖旧版本
```

工作名称一律小写英文、数字、连字号，例如 `bart-risk-taking`；中文标题写在 `job.toml` 的 `title`。指令里可以只写名称，也可以写 `generate/bart-risk-taking`。

### 工作管理 `sv.py`

| 指令 | 做什么 |
|---|---|
| `uv run sv.py list` | 列出所有工作与最新成品版本 |
| `uv run sv.py init generate final-report --title "期末报告"` | 建立新工作（类型：extract / dub / generate），附上范本 |
| `uv run sv.py check final-report` | 检查 job.toml 与所有输入档，错误会指出档案、行号、栏位 |
| `uv run sv.py approve final-report scenes.toml` | 确认 review/ 里的草稿，移进 input/（原本的备份到 input/.previous/） |

测试样本 `generate/bart-risk-taking/`（心研法海报）另外保留了：
- `output/legacy/`：旧流程的 `final_v2.wav`，以及 `final_v4_original_pronunciation.wav`（Adjusted BART、Eysenck 换成原始录音的发音）。
- `input/original_subtitles/`：对齐**原始影片**（你自己的声音）的繁体字幕，以及依据的逐字时间戳 `voice_words.json`。

---

## 工具一：提取音档

提取整段音档，存成同名的 `.wav`（单声道 48kHz）：

```bash
uv run extract_audio/extract.py ~/Movies/talk.mp4
```

只取其中一段：

```bash
uv run extract_audio/extract.py ~/Movies/talk.mp4 --start 1:30 --end 2:10
```

另外依停顿切成 10–20 秒的声音样本，给 Voicebox 建复制声音：

```bash
uv run extract_audio/extract.py ~/Movies/talk.mp4 --samples ~/Desktop/split-voice-workspace/shared/voice/samples
```

建立复制声音：在 Voicebox app 新增声音档（语言选中文），放进 1–3 段样本，单段约 10–30 秒、内容清楚为佳。

---

## 工具二：讲稿 → 配音 + 字幕

### 每次使用前

1. **从 Dock 打开 Voicebox**。
2. **在 app 里用你的声音档生成一句话**，让模型载入。

这两步很重要。如果模型是由脚本第一次载入的，Voicebox 会出错，连 app 里也无法生成，只能 ⌘Q 后重开。脚本开跑前会检查，模型没载入就会停下来提示你。

### 1. 写讲稿 `input/script.md`

范本：`templates/generate/input/script.md`（建立工作时会复制到 `input/templates/`）。

讲稿格式范例（这是 `script.md` 的内容，不是终端机指令；「# 」开头的行是注解，不会念）：

```text
# 讲稿：心研法海报
## 投影片 1
大家好，我是锦坤。
今天要来介绍一篇关于心理学家如何使用一个打气球游戏，测量人有多爱冒险的研究。

## 投影片 2
这篇是 {{Lejuez}} 等人在二〇〇二年发表的文献。
作者开发了一个新的行为测验，叫 {{BART_full}}，简称 {{BART}}，
并在这篇研究中检验它能不能真正测出一个人的冒险倾向。
```

- **一行 = Voicebox 生成一次**。一句太长可以拆成两行，行尾用逗号。
- **空行 = 段落结束**，停顿比较长。**`## ` = 换投影片**。
- **`{{key}}` = 词汇表里的特殊词**。
- 数字照平常写就好，例如 86、5.7%、二〇〇二年。念的时候会自动转成「八十六、百分之五点七、二零零二年」，字幕照讲稿显示。

一般的讲稿（一段一段的）可以先自动拆成一句一行，再手动调整：

```bash
uv run narrate/narrate.py format speech.txt > ~/Desktop/split-voice-workspace/generate/new-talk/input/script.md
```

### 2. 词汇表 `shared/vocabulary.tsv`

| 栏位 | 说明 |
|---|---|
| key | 讲稿里写 `{{key}}` |
| type | 缩写 / 人名 / 术语…（备注用） |
| subtitle | **字幕显示**的文字 |
| tts | **送给 Voicebox 念**的文字，可以跟字幕不同 |
| tts_lang | 生成语言（目前一律 zh） |
| tested | 试听过的日期；空白表示还没确认念法 |
| note | 备注：念法的试听结果、来源 |

所有工作共用这张表。以后要换念法，只改 `tts` 栏，所有用到它的句子下次 build 都会自动重做。

| 指令 | 做什么 |
|---|---|
| `uv run narrate/narrate.py scan <job>` | 找出漏标的英文、表里没有的 key，列出每个词用在哪几行 |
| `uv run narrate/narrate.py vocab list` | 列出词汇表 |
| `uv run narrate/narrate.py vocab set Eysenck --subtitle Eysenck --tts 艾森克 --type 人名` | 新增或修改一个词 |
| `uv run narrate/narrate.py try "Adjusted bart" "Adjusted Bahrt" --lang en` | 试听几种写法 |
| `uv run narrate/narrate.py try "勒胡埃兹" "Lejuez" --carrier "这篇是 {} 等人的文献。"` | 用指定的句型试听 |

**改写法的原则**：要写成一个完整的词。像 `uh-JUST-it` 这种用连字号分音节的写法会被念成三个独立的词。可以试：
- 大小写：`BART` 可能被逐个字母念，`Bart` 会被当成人名
- 中文近音字：`巴特`
- 逐个字母：`B A R T`
- 英文模式（`--lang en`）
- 多音字：换成同音字，例如长条的「长」写成「常」

### 3. 产生配音和字幕

| 指令 | 做什么 |
|---|---|
| `uv run narrate/narrate.py lines <job>` | 列出每一行：字幕文字、念法、有没有音档 |
| `uv run narrate/narrate.py build <job>` | 生成缺少的句子 → 拼接 → 字幕，输出到 `output/vN/` |

`build` 只会生成「还没有音档」的句子，已经有的直接沿用，所以中断后重跑也不会浪费时间。

每句的生成过程：
1. 前后加上「开始 / 结束」marker 送给 Voicebox。marker 一定要加，不加的话模型常会吞掉句子的头尾。
2. 用 Whisper 的逐字时间戳找到 marker，**只在真正的静音里下刀**。
3. 检查：头尾没有残留的「始」「结」，听写跟原文对得上，句尾的字在，英文完整。
4. 不通过就换一种 marker 写法再试，最多 8 次。Voicebox 会忽略 seed，所以只能靠换写法得到不同的结果。

### 4. 挑选个别句子

觉得某一句念得不好，例如第 46 行：

1. 生成 4 个版本，存在 `review/audition/line046/1.wav` … `4.wav`：

   ```bash
   uv run narrate/narrate.py audition bart-risk-taking 46 --takes 4
   ```

2. 听完后选用第 2 个，并锁定：

   ```bash
   uv run narrate/narrate.py pick bart-risk-taking 46 2
   ```

3. 重新拼出新版本：

   ```bash
   uv run narrate/narrate.py build bart-risk-taking
   ```

### 5. 清理 Voicebox 的生成纪录

`build`、`audition` 每生成一笔，把音档存进专案后，就会自动删掉 Voicebox 里的那一笔（`config.toml` 的 `cleanup = true`），所以 Voicebox 的纪录不会越积越多。
要一次清掉以前留下的全部纪录：

| 指令 | 做什么 |
|---|---|
| `uv run narrate/narrate.py clean` | 先告诉你有几笔，问过你才删 |
| `uv run narrate/narrate.py clean --keep-favorites` | 同上，但保留在 Voicebox 里加星号的 |

正在生成中的纪录会跳过。**不要在 build 执行中跑 clean**，不然正在生成的音档会被删掉。

### 6. 成品 `output/vN/`

| 档案 | 用途 |
|---|---|
| `narration.wav` | 完整配音，48kHz，响度依 config.toml 设定 |
| `subtitles_youtube.srt` | YouTube 上传 |
| `subtitles_powerpoint.vtt` | PowerPoint：选取影片 → 播放 → 插入字幕。没有编号、无 BOM |
| `subtitles_vlc.srt`、`subtitles_vlc.ass` | VLC 播放。ASS 用苹方繁体（PingFang TC），白字黑边 |
| `tts_vs_subtitle.tsv` | 每一行的字幕文字、实际送给 Voicebox 的文字、是否不同、音档来源、Whisper 听写 |
| `timeline.json` | 每一行在配音里的起止时间 |
| `script.md`、`vocabulary.tsv` | 这次 build 用的讲稿和词汇表（留底） |

- 字幕一律是**繁体中文**（OpenCC 台湾标准 s2tw，再套用 `traditional_fixes.tsv` 的修正），并且是**无 BOM 的 UTF-8**。
- 字幕时间直接用配音的时间轴，跟 `narration.wav` 完全对齐。
- 断句规则：句号、问号、分号一定断开；太长（超过 18 个字宽）从逗号断开；中间没有标点的长句，从停顿最久的地方断开。
- 停顿长度（`config.toml` 的 `[pause]`）：段落 0.85 秒、句号 0.5 秒、分号冒号 0.4 秒、逗号 0.25 秒；换投影片至少 0.85 秒。

---

## 移植到另一台电脑（Mac M 系列）

1. 照《macOS 新機開發與本地 AI 環境安裝 SOP》装好基础环境。这个专案需要的是 SOP 里的 Homebrew、`uv`、`ffmpeg`（第 1、2.1 节）和 Python 3.11（第 3.1 节）；要在 Open WebUI 里用，还需要 Ollama 和 Open WebUI（第 5、6 节）。
2. 另外安装 **Voicebox**（Mac 版）。
3. 复制程式资料夹 `split-voice/`；工作区 `split-voice-workspace/` 视需要另外搬。工作区换了位置，就改 `narrate/config.toml` 的 `[paths] workspace`。放在「桌面」「文件」「下载」时，第一次用 Open WebUI 会跳出权限询问，按「允许」即可，见 [openwebui/README.md](openwebui/README.md) 第二节。
4. **带走复制声音**，二选一：
   - 在旧电脑的 Voicebox 汇出声音档（API 是 `GET /profiles/{id}/export`），在新电脑汇入（`POST /profiles/import`）；
   - 用工作区里的样本（`shared/voice/samples/`），在新电脑重新建立。

   声音档名称要跟 `narrate/config.toml` 的 `profile` 一样（目前是 `My Voice`）。
5. 第一次执行会自动下载 faster-whisper small 模型（约 480 MB，存在 `~/.cache/huggingface/`）。也可以直接从旧电脑复制这个资料夹。
6. 执行下面两个指令测试（不需要 Voicebox）：

   ```bash
   uv run narrate/narrate.py vocab list
   ```

   ```bash
   uv run sv.py check bart-risk-taking
   ```

### 搭配 Ollama + Open WebUI

- Ollama 跑的是大型语言模型，**取代不了 Voicebox（念稿）和 Whisper（检查）**，这两个还是要装。
- `narrate.py` 本身**不需要任何 AI 就能执行**，所有步骤都是固定的程式。
- 把 [`openwebui/split_voice_tool.py`](openwebui/split_voice_tool.py) 加成 Open WebUI 的工具后，就能在对话里操作全部功能，出错会回报原因。安装步骤见 [openwebui/README.md](openwebui/README.md)。

---

## 已知问题与原因（2026-10 调适的纪录）

| 问题 | 原因 | 现在的做法 |
|---|---|---|
| `/v1/audio/speech` 回 404 | Voicebox 没有 OpenAI 相容的 API | 用 `/generate`（非同步），轮询 `/history/{id}`，完成后从 `/audio/{id}` 下载 |
| `There is no Stream(gpu…)`，连 app 里也坏 | 模型由 API 第一次载入（Mac MLX 版） | 从 Dock 打开，先在 app 生成一句；脚本开跑前会检查 |
| 从终端机重启 Voicebox 后也坏 | 同上 | 只由你手动重开 |
| `/transcribe` 永远出错 | Voicebox 的 MLX 执行绪问题 | 检查改用本机 faster-whisper |
| 记忆体吃紧时 voicebox-server 崩溃 | 记忆体不足 | 脚本遇到连不上会停下，重开后再跑 build（已完成的句子会保留） |
| 重试的结果都一样 | Voicebox 忽略 seed | 换 marker 写法（8 种） |
| 不加 marker 时句子头尾被吞掉 | 模型的特性 | 一律加「开始 / 结束」 |
| 开头残留「始」、结尾残留「结」 | 切在音量低点而不是静音 | 只在真正的静音下刀，再检查头尾 |
| 「结束」被听成节目、介绍、谢谢 | 「结束」念得含糊 | 改找原文最后一个字 |
| 正文被当成 marker 切掉 | marker 和正文连着念 | 检查听写是否完整、句尾的字是否在 |
| 句尾是英文时对不上 | Whisper 把 bart 听成 Bud、爸… | 改找「结束」类的字之前的词，再检查英文是否完整 |
| 英文专有名词念不准 | TTS 读英文不稳；同一写法每次结果也不同 | 词汇表改写法 + audition 挑版本。把自己的录音或单独生成的词拼进句子，接缝都不自然，已经放弃 |
| 连字号拼法（uh-JUST-it）被念成三个词 | 连字号被当成断词 | 写成一个完整的词 |
| 简转繁把「只」误转成「隻」 | OpenCC 的歧义 | `traditional_fixes.tsv` 自动修正 |
| PowerPoint 读不了字幕 | 档案有 BOM | 所有字幕都是无 BOM 的 UTF-8；VTT 不加编号 |
| 剪映网页版汇入字幕显示空白 | 原因不明（换成 BOM / CRLF 格式也一样） | 不再支援剪映 |
