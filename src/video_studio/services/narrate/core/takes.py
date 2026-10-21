"""takes.json：每句选用的音档。以「念法文字」的指纹当索引，所以：
- 讲稿或词汇表改了哪一句的念法，只有那一句会重做；
- 你挑选并锁定（locked）的版本，不会被重做掉。
"""
import hashlib, json
from pathlib import Path


def key(tts_text):
    return hashlib.sha1(tts_text.encode("utf-8")).hexdigest()[:12]


class Takes:
    def __init__(self, base_dir, path=None):
        """base_dir：音档路径的起点（工作资料夹）；path：takes.json 的位置（预设 work/takes.json）"""
        self.dir = Path(base_dir)
        self.path = Path(path) if path else self.dir / "work" / "takes.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def get(self, tts_text):
        t = self.data.get(key(tts_text))
        if t and (self.dir / t["clip"]).exists():
            return t
        return None

    def put(self, tts_text, clip, words, source, sim=None, locked=False):
        rel = Path(clip).resolve().relative_to(self.dir.resolve())
        self.data[key(tts_text)] = {"tts": tts_text, "clip": str(rel), "words": words,
                                    "source": source, "sim": sim, "locked": locked}
        self.save()

    def lock(self, tts_text, locked=True):
        self.data[key(tts_text)]["locked"] = locked
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
