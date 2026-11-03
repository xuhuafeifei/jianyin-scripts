"""Contact sheet: every picture slot as a thumbnail with its timecode.

Meant for the human review pass — one image to eyeball the whole edit instead
of scrubbing the timeline.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from PIL import Image, ImageDraw

from . import drafts
from .common import DATA_DIR, US, ensure_dir
from .preview import font

THUMB_W = 480
THUMB_H = 270
COLS = 4
PAD = 10
LABEL_H = 34


def build_sheet(draft_name: str, out_path: str = "",
                cols: int = COLS) -> str:
    d = drafts.resolve(draft_name)
    c = d.load_content()
    W = int(c["canvas_config"]["width"])
    H = int(c["canvas_config"]["height"])
    videos = {m["id"]: m for m in c["materials"].get("videos", [])}
    texts = {m["id"]: m for m in c["materials"].get("texts", [])}

    vt = [t for t in c["tracks"] if t["type"] == "video"]
    tt = [t for t in c["tracks"] if t["type"] == "text"]
    text_segs = tt[0]["segments"] if tt else []
    if not vt or not vt[0]["segments"]:
        raise RuntimeError("草稿里没有图片轨")

    def line_at(t_us: int) -> str:
        for s in text_segs:
            r = s["target_timerange"]
            if r["start"] <= t_us < r["start"] + r["duration"]:
                try:
                    return json.loads(texts[s["material_id"]]["content"]).get("text", "")
                except Exception:
                    return ""
        return ""

    frames = []
    for i, seg in enumerate(vt[0]["segments"]):
        r = seg["target_timerange"]
        mid = r["start"] + r["duration"] // 2
        mat = videos.get(seg["material_id"])
        if not mat or not os.path.isfile(mat.get("path", "")):
            continue
        src = Image.open(mat["path"]).convert("RGB")
        base = min(W / src.width, H / src.height)
        nw, nh = max(1, int(src.width * base)), max(1, int(src.height * base))
        src = src.resize((nw, nh), Image.LANCZOS)
        canvas = Image.new("RGB", (W, H), (0, 0, 0))
        canvas.paste(src, ((W - nw) // 2, (H - nh) // 2))

        sub = line_at(mid)
        if sub:
            dr = ImageDraw.Draw(canvas)
            f = font(max(24, int(W / 135 * 5.0 * 0.55)))
            bbox = dr.textbbox((0, 0), sub, font=f, stroke_width=6)
            tw = bbox[2] - bbox[0]
            y = int(H * (0.5 + 0.73 * 0.5)) - (bbox[3] - bbox[1]) // 2
            dr.text(((W - tw) // 2, y), sub, font=f, fill=(255, 222, 0),
                    stroke_width=6, stroke_fill=(0, 0, 0))

        frames.append({
            "no": i + 1,
            "start": r["start"] / US,
            "end": (r["start"] + r["duration"]) / US,
            "thumb": canvas.resize((THUMB_W, THUMB_H), Image.LANCZOS),
        })

    rows = (len(frames) + cols - 1) // cols
    sheet_w = cols * THUMB_W + (cols + 1) * PAD
    sheet_h = rows * (THUMB_H + LABEL_H) + (rows + 1) * PAD
    sheet = Image.new("RGB", (sheet_w, sheet_h), (18, 18, 18))
    dr = ImageDraw.Draw(sheet)
    lab = font(20)

    for idx, f in enumerate(frames):
        r, col = divmod(idx, cols)
        x = PAD + col * (THUMB_W + PAD)
        y = PAD + r * (THUMB_H + LABEL_H + PAD)
        sheet.paste(f["thumb"], (x, y))
        dr.text((x + 4, y + THUMB_H + 6),
                f"图{f['no']:02d}  {f['start']:6.1f}s → {f['end']:6.1f}s",
                font=lab, fill=(190, 190, 190))

    if not out_path:
        out_path = os.path.join(DATA_DIR, "reports", f"{draft_name}-总览.jpg")
    ensure_dir(os.path.dirname(out_path))
    sheet.save(out_path, quality=88)
    return out_path
