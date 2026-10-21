# 工具三 `video/`：配音 + 画面 → 完整影片

先用 `narrate.py build` 产生配音（`output/vN/narration.wav`、`timeline.json`、字幕），再用这个工具做影片。原则跟《用 AI 做影片》的工作流一样：**先配音、量时长，再决定每一页多长**，不用猜。

素材由工作的 `job.toml` 的 `[inputs]` 指定（`pptx`、`poster`、`scenes`），放在 `input/`。成品放在配音同一个版本资料夹 `<job>/output/vN/`：

| 档案 | 内容 |
|---|---|
| `video.mp4` | 完整影片（画面＋配音），字幕另外用 `subtitles_*.srt/vtt` |
| `video_subtitled.mp4` | 字幕烧进画面的版本（繁体） |
| `video_check.txt` | 验收结果：有没有画面和声音、长度、音量 |
| `video_contact_sheet.jpg` | 每一页抽一格的缩图总览，给你用眼睛检查 |
| `slide_timing.tsv` | 每一页的起止时间与 [click] 时间 |

渲染完请马上把成品复制到你会备份的地方，或在 `job.toml` 设定 `[output] backup_dir`，会自动复制。

---

## 先看每一页该多长

```bash
uv run video/video.py timing bart-risk-taking
```

---

## 方式一：PowerPoint（保留动画与转场）

**你要给的**：做好的 `.pptx`，放在 `input/`，档名填进 `job.toml` 的 `[inputs] pptx`。pptx 里内嵌的旧录音会在副本里自动移除。

**讲稿要对应的地方**：
- pptx 的页数 = 讲稿的 `## 投影片` 数量，顺序一样。
- 有「点一下才出现」的动画时，在讲稿里**念到要出现的那一行开头加 `[click]`**。每页的 `[click]` 数量要跟该页的点击动画数量一样。`[click]` 不会被念出来，也不会出现在字幕里。

```text
## 投影片 4
所以这个研究的目的有两个：
[click] 一是检查 {{BART}} 这个作业本身是否运作合理，也就是它的实验特性；
[click] 二是看 {{BART}} 的分数，和问卷测到的风险特质、以及真实生活中的风险行为有没有关联。
```

**执行**：

```bash
uv run video/video.py pptx bart-risk-taking
```

工具会：
1. 检查页数与点击动画数，对不上就列出是哪几页。
2. 写一份调整过动画时间的副本（**原本的 pptx 不会被改动**）：每个点击动画改成在配音念到 `[click]` 那一行时自动出现。动画种类、方向、速度都不变。
3. 让 PowerPoint 照每页的时间汇出 mp4。PowerPoint 会自动打开，汇出期间请不要操作它。
4. 合成配音、烧字幕、验收。

第一次执行时，macOS 会询问是否允许控制 Microsoft PowerPoint，请按「好」。在 Open WebUI 里执行时，询问的对象是 `python3.11`。

**自己汇出也可以**：用 `timing` 的秒数在 PowerPoint 里设定每页换页时间，汇出 mp4 后执行：

```bash
uv run video/video.py mux bart-risk-taking --video ~/Movies/my_export.mp4
```

---

## 方式二：海报 + pptx 分镜（推荐）

**你要给的**：
- 海报原图：**PDF 最好**（放大不会糊），其次是高解析 PNG（长边 4000 像素以上）。填进 `[inputs] poster`。
- 分镜 pptx：**每一页都是同一张海报**，用裁切／位置决定这一页要看海报的哪里，页与页之间用「转化（Morph）」转场；需要的话加上底部提示栏、外框、结尾大字。填进 `[inputs] pptx`。

工具会从 pptx 读出每一页的镜头区域、提示栏文字（可以多行）、提示栏颜色与字级、外框、结尾大字（例如「匯報完畢」），然后**用海报原图重新渲染**，所以画面比 PowerPoint 汇出更清楚，换页时镜头平滑移动。

1. 起草分镜，并画出区域预览图：

   ```bash
   uv run video/video.py scenes bart-risk-taking
   ```

   产生 `review/scenes.toml` 与 `review/scenes_preview.jpg`。pptx 不是「同一张海报不同裁切」时，会改成把海报平均分配给每一页（也可以用 `--source pptx` 或 `--source even` 指定）。

2. 看预览图，需要的话改 `review/scenes.toml`（格式见下面的方式三），确认后移进 `input/`：

   ```bash
   uv run sv.py approve bart-risk-taking scenes.toml
   ```

3. 渲染：

   ```bash
   uv run video/video.py poster bart-risk-taking
   ```

## 方式三：只有海报

没有分镜 pptx 时，`scenes` 会把海报由上到下平均分给每一页，起草到 `review/scenes.toml`。每一页一段（完整范本：`templates/generate/input/scenes.toml`）：

```text
[[scene]]
slide = 7
intent = "解释 Adj BART 的定义"
visual = "poster"
region = [0.0, 0.35, 1.0, 0.10]
callout = "Adj BART：蓝色气球中，未爆炸者的平均打气次数"
```

- `region = [x, y, 宽, 高]`：海报上要看的区域，用占海报宽、高的比例（0～1）表示。
  - 区域比画面宽：整块放进画面。
  - 区域太高：宽度对齐，在这一页的时间内从上卷到下。
- `callout`：底部重点提示栏的文字，留空就不显示；要分行就用 `\n`。可以写简体，会自动转成繁体。
- `intent`：这一幕想要怎样，给 AI 和你自己看，不会出现在画面。

检查区域位置（不加 `--review` 看的是 `input/scenes.toml`）：

```bash
uv run video/video.py preview bart-risk-taking --review
```

改好后照方式二的第 2、3 步确认、渲染。

换页时镜头移动 0.8 秒，换页前 0.4 秒停止卷动（都可以在 `video/config.toml` 调整）。同样的设定每次渲染出来的每一格都一样。

## 规划中

- `visual = "html"`：AI 依 `on_screen` 的文字排版，用 HTML + HyperFrames 渲染。
- `visual = "ai-clip"`：生成式影片服务产生插播画面（要先决定服务与 API 金钥）。

进度与顺序见 [docs/DESIGN.md](../docs/DESIGN.md) 第六节。

---

## 设定 `video/config.toml`

| 区段 | 内容 |
|---|---|
| `[output]` | 解析度 1920×1080、30 fps、H.264 品质、配音后多停几秒 |
| `[camera]` | 镜头移动秒数、卷动停止时间、底色、PDF 转图的宽度 |
| `[callout]` | 提示栏高度、颜色、字级、开头的 ✓（有分镜 pptx 时，以 pptx 读到的为准） |
| `[subtitle]` | 烧录字幕的字级、颜色、黑边 |
| `[font]` | 繁体中文字型（预设黑体-繁；苹方是系统私有字型，Python 读不到） |

## 已知限制

- 这台的 ffmpeg 没有文字绘制（drawtext / libass），所以字幕和提示栏用 Python（Pillow）画。
- 「✓」在黑体-繁里没有这个字，所以用线条画。
- Mac 版 PowerPoint 的 AppleScript 不能修改动画触发方式，所以改 pptx 里的动画时间表（2026-10-18 用 PowerPoint 16.114 实测可行）。
