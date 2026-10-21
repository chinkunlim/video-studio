"""
title: Split Voice 讲稿配音
description: 讲稿配音与影片：依工作（extract / dub / generate）管理素材，用 Voicebox 配音、产生繁体字幕，并用 pptx 分镜或海报做成影片。
version: 2.0.0
"""
# 安装：Open WebUI → 工作区（Workspace）→ 工具（Tools）→ 新增，把整个档案贴上并储存，
# 再到「阀门」（Valves）设定 project_dir。说明见 openwebui/README.md。

import asyncio
import json
import os
import re
import shutil
import tomllib
import urllib.request
from pathlib import Path

from pydantic import BaseModel, Field

PRIVACY_HINT = (
    "macOS 拒绝 Open WebUI 读取这个资料夹（Operation not permitted）。Open WebUI 由 launchd 在背景执行，"
    "预设没有读取「桌面」「文件」「下载」的权限。处理方式二选一：\n"
    "1. 把专案搬到不受保护的位置（例如 ~/Projects/split-voice），再到工具的「阀门」更新 project_dir；\n"
    "2. 系统设定 → 隐私权与安全性 → 完全取用磁碟 → ＋，按 ⌘⇧G 输入 "
    "~/.local/share/uv/tools/open-webui/bin/ 选 python，之后重启 Open WebUI 服务。"
)


class Tools:
    class Valves(BaseModel):
        project_dir: str = Field(
            default=str(Path.home() / "Desktop/projects/Old/split-voice"),
            description="split-voice 程式资料夹的完整路径",
        )
        workspace_dir: str = Field(
            default="",
            description="工作区（讲稿、音档、成品）的完整路径；留空表示用 narrate/config.toml 的 [paths] workspace",
        )
        extra_path: str = Field(
            default="/opt/homebrew/bin:/usr/local/bin:~/.local/bin:~/.cargo/bin",
            description="找 uv、ffmpeg 用的额外路径（Open WebUI 的环境里常常找不到 Homebrew 装的程式）",
        )
        voicebox_url: str = Field(default="http://127.0.0.1:17493", description="Voicebox 本机 API")
        timeout_minutes: int = Field(default=90, description="单一工作最长执行几分钟（build 可能要很久）")

    def __init__(self):
        self.valves = self.Valves()

    # ---------- 共用 ----------

    def _env(self):
        env = dict(os.environ)
        extra = ":".join(os.path.expanduser(p) for p in self.valves.extra_path.split(":") if p)
        env["PATH"] = f"{extra}:{env.get('PATH', '')}"
        env["PYTHONUNBUFFERED"] = "1"
        if self.valves.workspace_dir:
            env["SPLIT_VOICE_WORKSPACE"] = os.path.expanduser(self.valves.workspace_dir)
        return env

    def _workspace(self):
        if self.valves.workspace_dir:
            ws = Path(os.path.expanduser(self.valves.workspace_dir))
        else:
            cfg = tomllib.loads((self._project() / "narrate" / "config.toml").read_text(encoding="utf-8"))
            ws = Path(os.path.expanduser(cfg.get("paths", {}).get("workspace", str(self._project()))))
        try:
            ws.mkdir(parents=True, exist_ok=True)
            next(iter(ws.iterdir()), None)
        except PermissionError:
            raise RuntimeError(f"{ws}：{PRIVACY_HINT}")
        return ws

    def _project(self):
        p = Path(os.path.expanduser(self.valves.project_dir))
        try:
            found = (p / "narrate" / "narrate.py").exists()
            if found:
                next(iter(p.iterdir()), None)          # 实际读一次，才会碰到 macOS 的隐私权限制
        except PermissionError:
            raise RuntimeError(f"{p}：{PRIVACY_HINT}")
        if not found:
            hint = f"\n（也可能是 {PRIVACY_HINT}）" if str(p).startswith(str(Path.home() / "Desktop")) \
                or str(p).startswith(str(Path.home() / "Documents")) else ""
            raise RuntimeError(f"找不到专案：{p}/narrate/narrate.py。请到工具的「阀门」设定 project_dir。{hint}")
        return p

    def _which(self, name):
        found = shutil.which(name, path=self._env()["PATH"])
        if not found:
            raise RuntimeError(f"找不到 {name}。请先安装（brew install {name}），或在「阀门」的 extra_path 加上它的路径。")
        return found

    def _job_dirs(self):
        ws = self._workspace()
        out = []
        for t in ("extract", "dub", "generate"):
            d = ws / t
            if d.exists():
                out += [f"{t}/{j.name}" for j in sorted(d.iterdir()) if (j / "job.toml").exists()]
        return out

    def _job(self, job):
        """检查工作存在；回传原名称（交给指令自己解析「名称」或「类型/名称」）"""
        names = self._job_dirs()
        if job in names or any(n.split("/", 1)[1] == job for n in names):
            return job
        raise RuntimeError(f"找不到工作「{job}」。现有工作：{', '.join(names) or '没有'}。新工作请先用 create_job 建立。")

    def _py(self, *parts):
        return str(self._project().joinpath(*parts))

    def _voicebox_ready(self):
        try:
            with urllib.request.urlopen(f"{self.valves.voicebox_url}/health", timeout=5) as r:
                health = json.loads(r.read())
        except Exception:
            raise RuntimeError("连不上 Voicebox。请从 Dock 打开 Voicebox，在 app 里用声音档生成一句话，再试一次。")
        if not health.get("model_loaded"):
            raise RuntimeError("Voicebox 的模型还没载入。请先在 Voicebox app 里用声音档生成一句话（由程式载入会让 Voicebox 出错），再试一次。")

    @staticmethod
    async def _status(emitter, text, done=False, error=False):
        if emitter:
            await emitter({"type": "status", "data": {"description": text, "done": done, "hidden": False,
                                                       **({"error": True} if error else {})}})

    async def _run(self, args, emitter, label, stdin_text=None):
        """在专案资料夹执行指令，进度即时显示在状态列；失败就丢出错误（附最后几行输出）"""
        proj = self._project()
        uv = self._which("uv")
        self._which("ffmpeg")
        await self._status(emitter, f"{label}…")
        proc = await asyncio.create_subprocess_exec(
            uv, "run", *args, cwd=proj, env=self._env(),
            stdin=asyncio.subprocess.PIPE if stdin_text is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        if stdin_text is not None:
            proc.stdin.write(stdin_text.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
        lines = []

        async def pump():
            async for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip()
                if line.startswith(("Installed ", "Downloaded ", "Resolved ", "Prepared ")) or "HF Hub" in line:
                    continue
                lines.append(line)                    # 空行也保留：讲稿里空行代表段落
                if not line:
                    continue
                if line.lstrip().startswith(("[", "第", "完成", "要生成", "停止")):
                    await self._status(emitter, f"{label}：{line.strip()[:90]}")
        try:
            await asyncio.wait_for(asyncio.gather(pump(), proc.wait()), self.valves.timeout_minutes * 60)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"{label}超过 {self.valves.timeout_minutes} 分钟没完成，已中止。最后的输出：\n"
                               + "\n".join(lines[-15:]))
        if proc.returncode != 0:
            tail = "\n".join(lines[-20:])
            if "Operation not permitted" in tail or "PermissionError" in tail:
                tail += f"\n\n{PRIVACY_HINT}"
            raise RuntimeError(f"{label}失败（结束代码 {proc.returncode}）：\n{tail}")
        await self._status(emitter, f"{label}完成", done=True)
        return "\n".join(lines)

    async def _guard(self, emitter, coro):
        """统一的错误回报：在状态列标示失败，并回传「❌ 错误」让模型转告使用者"""
        try:
            return await coro
        except Exception as e:
            await self._status(emitter, f"错误：{str(e).splitlines()[0][:100]}", done=True, error=True)
            return f"❌ 错误：{e}\n\n（请把这个错误原样告诉使用者，不要自行假设已经完成。）"

    # ---------- 环境与工作 ----------

    async def check_environment(self, __event_emitter__=None) -> str:
        """
        检查执行环境：程式、工作区、uv、ffmpeg、Voicebox 是否开着、模型是否已载入，并列出所有工作。
        开始之前、或任何功能出错时，先呼叫这个。
        """
        async def go():
            proj = self._project()
            report = [f"✅ 程式：{proj}", f"✅ 工作区：{self._workspace()}",
                      f"✅ uv：{self._which('uv')}", f"✅ ffmpeg：{self._which('ffmpeg')}"]
            try:
                self._voicebox_ready()
                report.append("✅ Voicebox：已开启，模型已载入")
            except RuntimeError as e:
                report.append(f"⚠️ Voicebox：{e}（提取音档、查看与检查工作不需要 Voicebox）")
            report.append(f"工作：{', '.join(self._job_dirs()) or '还没有'}")
            await self._status(__event_emitter__, "环境检查完成", done=True)
            return "\n".join(report)
        return await self._guard(__event_emitter__, go())

    async def list_jobs(self, __event_emitter__=None) -> str:
        """列出所有工作：类型（extract 只提取声音 / dub 给影片配音 / generate 完整生成）、名称、标题、最新成品版本。"""
        async def go():
            return await self._run([self._py("sv.py"), "list"], __event_emitter__, "列出工作")
        return await self._guard(__event_emitter__, go())

    async def create_job(self, job_type: str, name: str, title: str = "", script_text: str = "",
                         __event_emitter__=None) -> str:
        """
        建立一份新工作（资料夹含 job.toml、input/、review/、work/、output/，以及范本）。
        有讲稿全文时，会自动整理成一句一行，存成 input/script.md。
        :param job_type: extract（只提取声音）、dub（给影片，用 Voicebox 重新配音）、generate（完整生成）
        :param name: 资料夹名称，只能用小写英文、数字、连字号，例如 final-report
        :param title: 中文标题，例如「期末报告」
        :param script_text: 讲稿全文（选填）。可用「## 投影片 N」标示换页；空行分段落
        """
        async def go():
            if job_type not in ("extract", "dub", "generate"):
                raise RuntimeError("job_type 只能是 extract、dub、generate 其中一个")
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
                raise RuntimeError(f"名称「{name}」不合格：只能用小写英文、数字、连字号，例如 final-report。中文放在 title。")
            out = await self._run([self._py("sv.py"), "init", job_type, name, "--title", title or name],
                                  __event_emitter__, "建立工作")
            if script_text.strip() and job_type in ("dub", "generate"):
                d = self._workspace() / job_type / name / "input"
                raw = d / "speech_script.txt"
                raw.write_text(script_text, encoding="utf-8")
                body = await self._run([self._py("narrate", "narrate.py"), "format", str(raw)],
                                       __event_emitter__, "整理讲稿格式")
                text = body if "## " in script_text else "## 投影片 1\n" + body
                (d / "script.md").write_text(f"# 讲稿：{title or name}\n\n{text}\n", encoding="utf-8")
                out += "\n\n已存成 input/script.md（原文在 input/speech_script.txt）。"
                if "## " not in script_text:
                    out += "没有标示投影片，全部先放在「投影片 1」，请依实际页数加上「## 投影片 N」。"
            chk = await self._run_ok([self._py("sv.py"), "check", name], __event_emitter__, "检查工作")
            return out + "\n\n检查结果：\n" + chk
        return await self._guard(__event_emitter__, go())

    async def _run_ok(self, args, emitter, label):
        """检查类指令：有错误时结束代码不是 0，但结果本身就是要给使用者看的报告"""
        try:
            return await self._run(args, emitter, label)
        except RuntimeError as e:
            return str(e).split("：", 1)[-1]

    async def check_job(self, job: str, __event_emitter__=None) -> str:
        """
        检查一份工作的设定与所有输入档（job.toml、script.md、scenes.toml、词汇表、pptx…）。
        有错误时会说出哪个档案、第几行／第几幕、哪个栏位、该怎么改。执行配音或做影片前先检查。
        :param job: 工作名称，例如 bart-risk-taking
        """
        async def go():
            return await self._run_ok([self._py("sv.py"), "check", self._job(job)], __event_emitter__, "检查工作")
        return await self._guard(__event_emitter__, go())

    async def approve_review(self, job: str, file: str, __event_emitter__=None) -> str:
        """
        使用者确认 review/ 里的草稿后，把它移进 input/（原本的会备份到 input/.previous/）。
        只有使用者明确说「确认」「可以」之后才呼叫。
        :param job: 工作名称
        :param file: review/ 里的档名，例如 scenes.toml、script.md
        """
        async def go():
            return await self._run([self._py("sv.py"), "approve", self._job(job), file], __event_emitter__, "确认草稿")
        return await self._guard(__event_emitter__, go())

    # ---------- 只提取声音 ----------

    async def extract_audio(self, video_path: str, make_voice_samples: bool = False,
                            __event_emitter__=None) -> str:
        """
        从影片（mp4 等）提取音档，存成同名的 .wav（单声道 48kHz）。
        :param video_path: 影片的完整路径，例如 /Users/me/Movies/talk.mp4
        :param make_voice_samples: 是否另外切成 10–20 秒的声音样本（给 Voicebox 建复制声音），存在影片旁的「<影片名>_samples」
        """
        async def go():
            v = Path(os.path.expanduser(video_path))
            if not v.exists():
                raise RuntimeError(f"找不到影片：{v}")
            args = [self._py("extract_audio", "extract.py"), str(v)]
            if make_voice_samples:
                args += ["--samples", str(v.with_name(v.stem + "_samples"))]
            return await self._run(args, __event_emitter__, "提取音档")
        return await self._guard(__event_emitter__, go())

    # ---------- 配音 ----------

    async def list_lines(self, job: str, __event_emitter__=None) -> str:
        """
        列出讲稿的每一行：行号、投影片、字幕文字、送给 Voicebox 的念法，以及有没有音档。
        :param job: 工作名称
        """
        async def go():
            return await self._run([self._py("narrate", "narrate.py"), "lines", self._job(job)],
                                   __event_emitter__, "列出讲稿")
        return await self._guard(__event_emitter__, go())

    async def scan_vocabulary(self, job: str, __event_emitter__=None) -> str:
        """
        检查讲稿的词汇：没有放进 {{}} 的英文、词汇表里没有的 key，以及每个词用在哪几行、是否试听过。
        :param job: 工作名称
        """
        async def go():
            return await self._run([self._py("narrate", "narrate.py"), "scan", self._job(job)],
                                   __event_emitter__, "检查词汇")
        return await self._guard(__event_emitter__, go())

    async def list_vocabulary(self, __event_emitter__=None) -> str:
        """列出共用词汇表（shared/vocabulary.tsv）：key、类型、字幕显示、Voicebox 念法、是否试听过、备注。"""
        async def go():
            return await self._run([self._py("narrate", "narrate.py"), "vocab", "list"], __event_emitter__, "读取词汇表")
        return await self._guard(__event_emitter__, go())

    async def set_vocabulary(self, key: str, subtitle: str = "", tts: str = "", word_type: str = "",
                             tested: str = "", note: str = "", __event_emitter__=None) -> str:
        """
        新增或修改词汇表的一个特殊词。字幕显示和 Voicebox 念法可以不同（例如字幕 BART、念 bart）。
        :param key: 讲稿里 {{key}} 的名称，只能用英文字母、数字、底线，例如 Adjusted_BART
        :param subtitle: 字幕显示的文字（新词必填）
        :param tts: 送给 Voicebox 念的文字；留空表示同字幕
        :param word_type: 类型，例如 缩写、人名、术语
        :param tested: 试听通过的日期，例如 2026-10-18
        :param note: 备注
        """
        async def go():
            args = [self._py("narrate", "narrate.py"), "vocab", "set", key]
            for flag, val in (("--subtitle", subtitle), ("--tts", tts), ("--type", word_type),
                              ("--tested", tested), ("--note", note)):
                if val:
                    args += [flag, val]
            return await self._run(args, __event_emitter__, "更新词汇表")
        return await self._guard(__event_emitter__, go())

    async def build_narration(self, job: str, __event_emitter__=None) -> str:
        """
        产生配音和字幕：生成还没有音档的句子（Voicebox）→ 检查 → 拼接 → 字幕，输出到 <工作>/output/vN/。
        需要 Voicebox 开着且模型已载入。可能要几分钟到几十分钟。
        :param job: 工作名称
        """
        async def go():
            name = self._job(job)
            self._voicebox_ready()
            out = await self._run([self._py("narrate", "narrate.py"), "build", name], __event_emitter__, "产生配音")
            failed = [ln for ln in out.splitlines() if "全部失败" in ln]
            note = f"\n\n⚠️ 有 {len(failed)} 句生成失败：可用 audition_line 多试几次，或把太短的句子跟前一行合并。" \
                if failed else ""
            return out[-3000:] + note
        return await self._guard(__event_emitter__, go())

    async def audition_line(self, job: str, line: int, takes: int = 4, __event_emitter__=None) -> str:
        """
        某一行念得不好时，生成几个版本给使用者试听，存在 <工作>/review/audition/lineNNN/1.wav、2.wav…
        :param job: 工作名称
        :param line: 行号（list_lines 列出的编号）
        :param takes: 要几个版本，预设 4
        """
        async def go():
            name = self._job(job)
            self._voicebox_ready()
            return await self._run([self._py("narrate", "narrate.py"), "audition", name, str(line), "--takes", str(takes)],
                                   __event_emitter__, f"试听第 {line} 行")
        return await self._guard(__event_emitter__, go())

    async def pick_take(self, job: str, line: int, take: int, __event_emitter__=None) -> str:
        """
        选用 audition_line 产生的某个版本并锁定。选完再呼叫 build_narration 产生新版本。
        :param job: 工作名称
        :param line: 行号
        :param take: 版本编号（1、2、3…）
        """
        async def go():
            return await self._run([self._py("narrate", "narrate.py"), "pick", self._job(job), str(line), str(take)],
                                   __event_emitter__, "选用版本")
        return await self._guard(__event_emitter__, go())

    async def try_spellings(self, spellings: str, language: str = "zh", carrier: str = "",
                            __event_emitter__=None) -> str:
        """
        试听一个词的几种写法，存在工作区 shared/vocab_tries/。挑好后用 set_vocabulary 填进 tts。
        写法要是一个完整的词；用连字号分音节（uh-JUST-it）会被念成好几个词。
        :param spellings: 几种写法，用「|」分隔，例如「Adjusted bart|Adjusted Bahrt|Adjusted 巴特」
        :param language: zh（中文模式，配音用的模式）或 en（英文模式）
        :param carrier: 句型，用 {} 代表这个词，例如「这个分数就叫 {}。」；留空用预设句型
        """
        async def go():
            self._voicebox_ready()
            words = [w.strip() for w in spellings.split("|") if w.strip()]
            if not words:
                raise RuntimeError("没有写法：请用「|」分隔，例如「Adjusted bart|Adjusted Bahrt」")
            args = [self._py("narrate", "narrate.py"), "try", *words, "--lang", language]
            if carrier:
                args += ["--carrier", carrier]
            return await self._run(args, __event_emitter__, "试听写法")
        return await self._guard(__event_emitter__, go())

    async def clean_voicebox_history(self, confirm: bool = False, __event_emitter__=None) -> str:
        """
        删除 Voicebox 里所有生成纪录（音档都已经存在工作里；复制声音的样本不会动）。无法复原。
        只有在使用者明确同意后，才用 confirm=true 呼叫。
        :param confirm: 使用者已经明确同意删除时才设为 true
        """
        async def go():
            if not confirm:
                raise RuntimeError("这会删除 Voicebox 里所有生成纪录，而且无法复原。请先问使用者是否同意，同意后再用 confirm=true 呼叫。")
            return await self._run([self._py("narrate", "narrate.py"), "clean", "--yes"],
                                   __event_emitter__, "清除 Voicebox 纪录")
        return await self._guard(__event_emitter__, go())

    # ---------- 影片 ----------

    async def video_slide_timing(self, job: str, __event_emitter__=None) -> str:
        """
        列出每一页在配音里的起止时间、长度，以及每个 [click] 在页内第几秒。需要先 build_narration。
        :param job: 工作名称
        """
        async def go():
            return await self._run([self._py("video", "video.py"), "timing", self._job(job)],
                                   __event_emitter__, "计算每页时间")
        return await self._guard(__event_emitter__, go())

    async def video_draft_scenes(self, job: str, source: str = "auto", __event_emitter__=None) -> str:
        """
        起草分镜到 <工作>/review/scenes.toml，并画出区域预览图 review/scenes_preview.jpg 给使用者确认。
        source = auto：pptx 是「每一页都是同一张海报、不同裁切」就从 pptx 读镜头位置与提示栏；否则把海报平均分配。
        使用者确认后，再用 approve_review(job, "scenes.toml")。
        :param job: 工作名称
        :param source: auto、pptx 或 even
        """
        async def go():
            return await self._run([self._py("video", "video.py"), "scenes", self._job(job), "--source", source, "--force"],
                                   __event_emitter__, "起草分镜")
        return await self._guard(__event_emitter__, go())

    async def video_from_poster(self, job: str, __event_emitter__=None) -> str:
        """
        海报影片：依 input/scenes.toml，镜头在海报上移动，加上外框、提示栏，合成配音、烧字幕、验收。
        输出 video.mp4、video_subtitled.mp4、video_check.txt、video_contact_sheet.jpg（在配音同一个 output/vN/）。
        :param job: 工作名称
        """
        async def go():
            return await self._run([self._py("video", "video.py"), "poster", self._job(job)],
                                   __event_emitter__, "海报影片")
        return await self._guard(__event_emitter__, go())

    async def video_from_pptx(self, job: str, __event_emitter__=None) -> str:
        """
        PowerPoint 汇出影片（保留动画与转场）：先移除 pptx 内嵌的旧录音，依配音设定每页换页时间与 [click] 动画时间，
        让 PowerPoint 汇出，再合成配音、烧字幕、验收。pptx 由 job.toml 的 [inputs] pptx 指定。
        执行时 PowerPoint 会自动打开，请使用者不要操作它。
        :param job: 工作名称
        """
        async def go():
            return await self._run([self._py("video", "video.py"), "pptx", self._job(job)],
                                   __event_emitter__, "PowerPoint 影片")
        return await self._guard(__event_emitter__, go())

    async def video_mux(self, job: str, video_path: str, __event_emitter__=None) -> str:
        """
        把一支现成的画面影片跟配音合成，烧字幕并验收。
        :param job: 工作名称
        :param video_path: 画面影片（完整路径，或 input/ 里的档名）
        """
        async def go():
            return await self._run([self._py("video", "video.py"), "mux", self._job(job), "--video", video_path],
                                   __event_emitter__, "合成影片")
        return await self._guard(__event_emitter__, go())
