# 在 Ollama + Open WebUI 里使用

`split_voice_tool.py` 是 Open WebUI 的「工具」（Tool）。装好之后，在对话里直接跟模型说「帮我把这份讲稿做成配音」，模型就会呼叫专案里的 `sv.py`、`extract_audio`、`narrate` 和 `video`。任何一步出错，原因都会显示在对话和状态列上。

环境照《macOS 新機開發與本地 AI 環境安裝 SOP》安装即可（本文简称「SOP」）。本文只补充这个工具需要的部分，写法也照 SOP：程式码区块里不放 `#` 注解，本机服务一律用 `127.0.0.1`。

---

## 一、前置条件（SOP 已涵盖的部分）

| 需要 | SOP 章节 |
|---|---|
| Homebrew、`uv`、`ffmpeg` | 第 1、2.1 节（`brew install gh uv ffmpeg`） |
| Python 3.11 | 第 3.1 节 |
| Ollama 与 `qwen2.5` 模型 | 第 2.1、5 节 |
| Open WebUI（`uv tool` 安装 + `launchd` 常驻，`http://127.0.0.1:8080`） | 第 6 节 |

SOP 的 `launchd` 设定里，`PATH` 已经包含 `/opt/homebrew/bin` 和 `$HOME/.local/bin`，所以工具找得到 `uv` 和 `ffmpeg`，不用另外设定。

**SOP 以外还要装的**：
1. **Voicebox**（Mac 版），并建立或汇入复制声音 **My Voice**。做法见专案 [README](../README.md) 的「移植到另一台电脑」。
2. 这个专案资料夹 `split-voice/`。

---

## 二、专案放哪里：注意 macOS 隐私权限制

Open WebUI 由 `launchd` 在背景执行。macOS 预设**不让背景程式读取「桌面」「文件」「下载」**，跟 SOP 第 0 节提到终端机读不到桌面是同一种限制。如果专案放在 `~/Desktop` 底下，工具可能会报错：

> macOS 拒绝 Open WebUI 读取这个资料夹（Operation not permitted）

**最常见的情况：第一次使用时 macOS 会跳出询问**

> 「python3.11」想要取用「桌面」资料夹中的档案。

按「**允许**」就好（2026-10-18 在这台 Mac 上实测：允许之后，Open WebUI 就能读写桌面上的专案）。询问视窗可能被其他视窗挡住；工具看起来「卡住没反应」时，先找找这个视窗。允许的对象是 Open WebUI 用的 `python3.11`，如果日后 uv 换了 Python 版本，可能会再问一次。

如果按了「不允许」，或者没看到询问视窗，可以用下面两种方式处理：

**方式 1：把程式和工作区搬到不受保护的位置**，例如 `~/Projects/`：

```bash
mkdir -p ~/Projects
```

```bash
mv ~/Desktop/projects/Old/split-voice ~/Projects/split-voice
```

```bash
mv ~/Desktop/split-voice-workspace ~/Projects/split-voice-workspace
```

搬完后：
- 把 `narrate/config.toml` 的 `[paths] workspace` 改成新的工作区路径；
- 到工具的「阀门」把 `project_dir` 改成新的程式路径。

**方式 2：让 Open WebUI 的 Python 可以读取所有档案**：
1. 系统设定 → 隐私权与安全性 → 完全取用磁碟 → ＋
2. 按 ⌘⇧G，输入 `~/.local/share/uv/tools/open-webui/bin/`，选 `python`
3. 重启 Open WebUI 服务（`bootout` 和 `bootstrap` 之间要隔 5 秒，见 SOP 第 6.4 节）：

```bash
launchctl bootout gui/$(id -u)/com.openwebui.service
sleep 5
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.openwebui.service.plist"
```

装好工具后执行一次 `check_environment`，就知道有没有被挡。

---

## 三、加入工具

1. 浏览器打开 `http://127.0.0.1:8080` → **工作区（Workspace）→ 工具（Tools）→ ＋**。
2. 把 `split_voice_tool.py` 的**整个内容**贴上，储存。
3. 点工具旁的 ⚙️「**阀门（Valves）**」：

   | 阀门 | 设定 |
   |---|---|
   | `project_dir` | **程式**资料夹的完整路径，例如 `/Users/你的帐号/Desktop/projects/Old/split-voice` |
   | `workspace_dir` | **工作区**（所有工作与共用词汇表）的完整路径；留空就用 `narrate/config.toml` 的设定（目前是 `~/Desktop/split-voice-workspace`） |
   | `extra_path` | 找 `uv`、`ffmpeg` 的额外路径；照 SOP 安装的话不用改 |
   | `voicebox_url` | `http://127.0.0.1:17493`，不用改 |
   | `timeout_minutes` | 单一工作最长几分钟，预设 90 |

4. **工作区 → 模型（Models）**，编辑 `qwen2.5`（或 `llama3.1`）：
   - 「工具」勾选 **Split Voice 讲稿配音**
   - 「进阶参数」的 **Function Calling** 设成 **Native**
   - 「系统提示」贴上下面这段：

   ```text
   你是讲稿配音与影片助手，用工具 Split Voice 处理讲稿、配音、字幕和影片。
   - 开始前先呼叫 check_environment。
   - 每份资料都属于一个「工作」：extract（只提取声音）、dub（给影片重新配音）、generate（完整生成）。新工作用 create_job，名称用小写英文与连字号，中文放 title。
   - 执行配音或做影片前先呼叫 check_job；有错误就照报告请使用者修改，不要自己猜。
   - review/ 里的草稿（例如 scenes.toml）要等使用者明确确认后，才呼叫 approve_review。
   - 工具回传「❌ 错误」时，把错误原样告诉使用者，并照错误里的指示请使用者处理；不要假装已经完成。
   - 需要 Voicebox 的工作（build_narration、audition_line、try_spellings）前，提醒使用者先从 Dock 打开 Voicebox，并在 app 里生成一句话。
   - 英文缩写、人名等特殊词要放进 {{key}}，并用 set_vocabulary 加进词汇表。
   - clean_voicebox_history 只能在使用者明确同意后才用 confirm=true 呼叫。
   ```

---

## 四、在对话里怎么用

| 你说 | 模型会呼叫 |
|---|---|
| 检查环境 | `check_environment` |
| 我有哪些工作？ | `list_jobs` |
| 用下面这份讲稿建立一个完整生成的工作，名称 final-report，标题「期末报告」：…… | `create_job`（存成 input/script.md 并检查） |
| 检查 final-report | `check_job` |
| 把 ~/Movies/talk.mp4 的声音抽出来，顺便切成声音样本 | `extract_audio` |
| final-report 有哪些英文词要处理？ | `scan_vocabulary` |
| 把 Eysenck 加进词汇表，字幕显示 Eysenck，念「艾森克」，是人名 | `set_vocabulary` |
| 试听 Lejuez 的几种念法：Lejuez、勒胡埃兹、乐瑞斯 | `try_spellings` |
| 产生 final-report 的配音和字幕 | `build_narration` |
| 第 12 行念得不好，给我 4 个版本 | `audition_line` |
| 第 12 行用第 3 个 | `pick_take`，再 `build_narration` |
| 清掉 Voicebox 的生成纪录 | 先问你，同意后才 `clean_voicebox_history` |
| bart-risk-taking 每一页该多长？ | `video_slide_timing` |
| 帮 bart-risk-taking 起草分镜 | `video_draft_scenes`（产生 review/scenes.toml 与预览图） |
| 分镜可以，确认 | `approve_review`（scenes.toml） |
| 做 bart-risk-taking 的海报影片 | `video_from_poster` |
| 用 PowerPoint 汇出 bart-risk-taking 的影片 | `video_from_pptx`（PowerPoint 会自动打开） |
| 把我汇出的 ~/Movies/x.mp4 跟配音合成 | `video_mux` |

工作名称一律用小写英文、数字和连字号（例如 `final-report`），中文标题另外给；名称不合格时工具会报错。素材（pptx、海报）请自己放进工作的 `input/`，档名填进 `job.toml` 的 `[inputs]`；每一种输入档的范本在 `input/templates/`。

成品在工作区的 `<类型>/<名称>/output/vN/`：
- `narration.wav`：配音
- `subtitles_youtube.srt`：YouTube
- `subtitles_powerpoint.vtt`：PowerPoint
- `subtitles_vlc.srt`、`subtitles_vlc.ass`：VLC
- `tts_vs_subtitle.tsv`：字幕与念法对照
- 做影片之后再加上：`video.mp4`、`video_subtitled.mp4`、`video_check.txt`、`video_contact_sheet.jpg`（见 [video/README.md](../video/README.md)）

`video_from_pptx` 第一次执行时，macOS 会询问是否允许 `python3.11` 控制 Microsoft PowerPoint，请按「好」。

---

## 五、常见错误

| 错误讯息 | 怎么处理 |
|---|---|
| macOS 拒绝 Open WebUI 读取这个资料夹 | 见第二节 |
| 工具一直卡住、没有反应 | macOS 可能在等你回应权限询问视窗（可能被其他视窗挡住），按「允许」；见第二节 |
| 找不到专案 | 阀门的 `project_dir` 路径不对 |
| 找不到工作 | 错误里会列出现有的工作；用其中的名称（例如 `bart-risk-taking`），或检查阀门的 `workspace_dir`／`config.toml` 的工作区路径 |
| 名称不合格 | 改用小写英文、数字、连字号，中文放在标题 |
| 找不到 uv / ffmpeg | 照 SOP 第 2.1 节安装；`which uv ffmpeg` 查得到的路径要在阀门的 `extra_path` 里 |
| 连不上 Voicebox | 从 Dock 打开 Voicebox |
| Voicebox 的模型还没载入 | 在 Voicebox app 里用声音档生成一句话，再试一次 |
| Voicebox 内部出错（no Stream(gpu…)） | Voicebox ⌘Q 后从 Dock 重开，在 app 里生成一句 |
| 有 N 句生成失败 | 多半是句子太短（例如「用来检验 H1。」），把它跟前一行合并成一行；或用 `audition_line` 多试几次 |
| 超过 N 分钟没完成 | 把阀门的 `timeout_minutes` 调大；已完成的句子都会保留，再执行一次会接着做 |
| Open WebUI 本身没回应 | 照 SOP 附录 B 检查：`curl -I http://127.0.0.1:8080`、`tail -n 30 ~/open-webui-data/service.err` |

---

## 六、限制

- `qwen2.5`（7B）偶尔会选错工具或参数填错。失败时工具会回报错误，换个说法或直接指定工具名称再试一次即可。
- 工具不会替你听音档。念得好不好要你自己听，再用 `audition_line` / `pick_take` 修正。
- 生成配音时，Voicebox（约 4.3 GB）、faster-whisper 和 Ollama 的模型都在同一台 Mac 上跑。记忆体紧的时候，生成期间可以先不要开其他大型模型。
