"""HTML/GSAP/HyperFrames 渲染引擎：將分鏡網頁與配音時間軸渲染為高畫質 MP4。"""

from __future__ import annotations

import html
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from video_studio.config.settings import PROJECT_ROOT

logger = logging.getLogger(__name__)


def _build_slide_sections(slides: list[Any], slide_texts: dict[int, list[str]]) -> list[str]:
    """依投影片時間與講稿文字產生確定性 HTML 分鏡區塊。

    Args:
        slides: Slide 時間物件列表。
        slide_texts: {投影片頁碼: [句子列表]} 字典。

    Returns:
        HTML section 字串列表。
    """
    sections: list[str] = []
    for s in slides:
        no = getattr(s, "slide", 1)
        dur = float(getattr(s, "duration", 3.0))
        lines = slide_texts.get(no, [])
        body = "".join(f"<p class='line'>{html.escape(line)}</p>" for line in lines)
        sections.append(
            f'<section class="slide" data-slide="{no}" data-duration="{dur:.3f}">'
            f'<div class="badge">Slide {no}</div>'
            f'<div class="content">{body}</div>'
            "</section>"
        )
    return sections


def draft_html(
    slides: list[Any],
    slide_texts: dict[int, list[str]],
    out_html: Path,
    title: str = "video-studio",
) -> Path:
    """產出符合 HyperFrames 規範的確定性 HTML 分鏡草稿（無隨機數、純本機字型）。

    Args:
        slides: Slide 時間物件列表。
        slide_texts: {投影片頁碼: [句子列表]} 字典。
        out_html: 輸出 HTML 檔案路徑。
        title: 簡報標題。

    Returns:
        產出的 HTML 檔案路徑。
    """
    out_html.parent.mkdir(parents=True, exist_ok=True)
    sections = "\n    ".join(_build_slide_sections(slides, slide_texts))
    timeline_data = [
        {
            "slide": getattr(s, "slide", 1),
            "start": float(getattr(s, "start", 0.0)),
            "duration": float(getattr(s, "duration", 3.0)),
        }
        for s in slides
    ]
    doc = f"""<!DOCTYPE html>
<html lang="zh-Hant" data-fps="30" data-width="1920" data-height="1080">
<head>
  <meta charset="UTF-8" />
  <title>{html.escape(title)}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      width: 1920px; height: 1080px; overflow: hidden;
      background: #f6f4ef; color: #1e2421;
      font-family: "PingFang TC", "Noto Sans TC", "Microsoft JhengHei", sans-serif;
    }}
    .stage {{ position: relative; width: 100%; height: 100%; }}
    .slide {{
      position: absolute; inset: 0; padding: 96px 120px;
      display: flex; flex-direction: column; justify-content: center; gap: 28px;
      opacity: 0;
    }}
    .slide.active {{ opacity: 1; }}
    .badge {{
      display: inline-block; align-self: flex-start;
      padding: 8px 18px; border-radius: 999px;
      background: #c85a27; color: #fff; font-size: 24px; font-weight: 600;
    }}
    .line {{ font-size: 46px; line-height: 1.5; font-weight: 500; }}
  </style>
</head>
<body>
  <main class="stage">
    {sections}
  </main>
  <script id="slide-timing" type="application/json">{json.dumps(timeline_data, ensure_ascii=False)}</script>
  <script>
    const slides = Array.from(document.querySelectorAll('.slide'));
    const timing = JSON.parse(document.getElementById('slide-timing').textContent || '[]');
    window.__renderAt = function(timeSec) {{
      let activeIdx = 0;
      for (let i = 0; i < timing.length; i++) {{
        if (timeSec >= timing[i].start) activeIdx = i;
      }}
      slides.forEach((el, idx) => el.classList.toggle('active', idx === activeIdx));
    }};
    if (slides.length > 0) slides[0].classList.add('active');
  </script>
</body>
</html>
"""
    out_html.write_text(doc, encoding="utf-8")
    return out_html


def render(html_path: Path, out_mp4: Path, cfg: dict[str, Any]) -> Path:
    """呼叫專案內 pnpm exec hyperframes 將 HTML 渲染為無聲 MP4 畫面。

    Args:
        html_path: 輸入 index.html 路徑。
        out_mp4: 輸出 MP4 路徑。
        cfg: 影片設定字典。

    Returns:
        產出的 MP4 檔案路徑。

    Raises:
        RuntimeError: hyperframes 執行失敗或未產出檔案時。
    """
    fps = int(cfg.get("output", {}).get("fps", 30))
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "pnpm",
        "exec",
        "hyperframes",
        "render",
        str(html_path.parent.resolve()),
        "-c",
        html_path.name,
        "-o",
        str(out_mp4.resolve()),
        "-f",
        str(fps),
        "--quality",
        "looks",
    ]
    logger.info("執行 HyperFrames 渲染：%s", " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    tail_lines: list[str] = []
    if proc.stdout:
        for raw in proc.stdout:
            line = raw.strip()
            if not line:
                continue
            tail_lines.append(line)
            if len(tail_lines) > 20:
                tail_lines.pop(0)
            logger.info("[hyperframes] %s", line)
    rc = proc.wait()
    if rc != 0 or not out_mp4.exists():
        raise RuntimeError(f"HyperFrames 渲染失敗（code={rc}）：{' | '.join(tail_lines[-5:])}")
    return out_mp4
