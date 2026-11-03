"""Human-checkable mapping report: which picture covers which lines, and when."""

from __future__ import annotations

import json
import os
from typing import Optional

from . import drafts, images
from .common import DATA_DIR, US, ensure_dir


def _text_of(material: dict) -> str:
    try:
        return json.loads(material["content"]).get("text", "")
    except Exception:
        return material.get("recognize_text", "")


def build_report(draft_name: str, out_path: str = "") -> str:
    d = drafts.resolve(draft_name)
    c = d.load_content()
    texts = {m["id"]: m for m in c["materials"].get("texts", [])}
    videos = {m["id"]: m for m in c["materials"].get("videos", [])}
    audios = {m["id"]: m for m in c["materials"].get("audios", [])}

    tt = [t for t in c["tracks"] if t["type"] == "text"]
    vt = [t for t in c["tracks"] if t["type"] == "video"]
    at = [t for t in c["tracks"] if t["type"] == "audio"]

    text_segs = tt[0]["segments"] if tt else []
    video_segs = vt[0]["segments"] if vt else []
    voice_segs = at[0]["segments"] if at else []

    def picture_at(t_us: int) -> tuple[str, int]:
        for i, s in enumerate(video_segs):
            r = s["target_timerange"]
            if r["start"] <= t_us < r["start"] + r["duration"]:
                m = videos.get(s["material_id"], {})
                return os.path.basename(m.get("path", "")), i + 1
        return "-", 0

    rows = []
    for i, s in enumerate(text_segs):
        r = s["target_timerange"]
        start, dur = r["start"], r["duration"]
        line = _text_of(texts.get(s["material_id"], {}))
        pic, idx = picture_at(start + dur // 2)
        voice = ""
        if i < len(voice_segs):
            voice = os.path.basename(audios.get(voice_segs[i]["material_id"], {}).get("path", ""))
        rows.append({
            "no": i + 1,
            "start": start / US,
            "end": (start + dur) / US,
            "dur": dur / US,
            "picture": pic,
            "pic_no": idx,
            "voice": voice,
            "chars": len(line),
            "text": line,
        })

    if not out_path:
        out_path = os.path.join(DATA_DIR, "reports", f"{draft_name}.md")
    ensure_dir(os.path.dirname(out_path))

    total = c["duration"] / US
    pics = len(video_segs)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# {draft_name} 对照表\n\n")
        f.write(f"- 画布：{c['canvas_config']['width']}×{c['canvas_config']['height']}\n")
        f.write(f"- 总时长：{total:.2f}s\n")
        f.write(f"- 字幕：{len(text_segs)} 条　语音：{len(voice_segs)} 条　图片：{pics} 张\n")
        f.write(f"- 平均每张图覆盖：{len(text_segs) / max(1, pics):.2f} 句\n\n")
        f.write("| # | 起 | 止 | 时长 | 图# | 图片文件 | 字数 | 文本 |\n")
        f.write("|---:|---:|---:|---:|---:|---|---:|---|\n")
        for r in rows:
            f.write(f"| {r['no']} | {r['start']:.2f} | {r['end']:.2f} | {r['dur']:.2f} "
                    f"| {r['pic_no']} | {r['picture']} | {r['chars']} | {r['text']} |\n")

        f.write("\n## 图片分段\n\n")
        f.write("| 图# | 文件 | 起 | 止 | 时长 | 覆盖字幕 |\n")
        f.write("|---:|---|---:|---:|---:|---|\n")
        for i, s in enumerate(video_segs):
            r = s["target_timerange"]
            m = videos.get(s["material_id"], {})
            first = next((x["no"] for x in rows
                          if r["start"] <= x["start"] < r["start"] + r["duration"]), "-")
            last = next((x["no"] for x in reversed(rows)
                         if r["start"] <= x["start"] < r["start"] + r["duration"]), "-")
            f.write(f"| {i + 1} | {os.path.basename(m.get('path', ''))} "
                    f"| {r['start'] / US:.2f} | {(r['start'] + r['duration']) / US:.2f} "
                    f"| {r['duration'] / US:.2f} | {first}–{last} |\n")

    return out_path
