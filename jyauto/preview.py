"""Render an approximate first-frame preview of a draft (no 剪映 needed)."""

from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, r"F:\JYAutoEdit")
from jyauto import drafts  # noqa: E402


def font(size: int) -> ImageFont.FreeTypeFont:
    for p in (r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc",
              r"C:\Windows\Fonts\simhei.ttf"):
        if os.path.isfile(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def render(draft_name: str, frame_index: int = 0, out: str = "") -> str:
    """frame_index is a subtitle index; the picture is looked up by time."""
    d = drafts.resolve(draft_name)
    c = d.load_content()
    W = int(c["canvas_config"]["width"])
    H = int(c["canvas_config"]["height"])
    img = Image.new("RGB", (W, H), (0, 0, 0))

    videos = {m["id"]: m for m in c["materials"].get("videos", [])}
    texts = {m["id"]: m for m in c["materials"].get("texts", [])}
    vt = [t for t in c["tracks"] if t["type"] == "video"]
    tt = [t for t in c["tracks"] if t["type"] == "text"]

    at_us = 0
    text_line = ""
    if tt and tt[0]["segments"]:
        segs = tt[0]["segments"]
        idx = max(0, min(frame_index, len(segs) - 1))
        seg = segs[idx]
        at_us = seg["target_timerange"]["start"] + seg["target_timerange"]["duration"] // 2
        mat = texts.get(seg["material_id"])
        if mat:
            text_line = json.loads(mat["content"]).get("text", "")

    if vt:
        for seg in vt[0]["segments"]:
            r = seg["target_timerange"]
            if r["start"] <= at_us < r["start"] + r["duration"]:
                mat = videos.get(seg["material_id"])
                if mat and os.path.isfile(mat["path"]):
                    src = Image.open(mat["path"]).convert("RGB")
                    scale = float(seg["clip"]["scale"].get("x", 1.0) or 1.0)
                    base = min(W / src.width, H / src.height)
                    nw = max(1, int(src.width * base * scale))
                    nh = max(1, int(src.height * base * scale))
                    src = src.resize((nw, nh), Image.LANCZOS)
                    img.paste(src, ((W - nw) // 2, (H - nh) // 2))
                break

    draw = ImageDraw.Draw(img)
    if text_line:
        style = json.loads(texts[tt[0]["segments"][frame_index]["material_id"]]["content"])
        base = max(16, int(style["styles"][0].get("size", 5.0) * W / 135))
        f, tw, th = None, 0, 0
        for size in range(base, 15, -2):
            f = font(size)
            bbox = draw.textbbox((0, 0), text_line, font=f, stroke_width=6)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            if tw <= W * 0.92:
                break
        y = int(H * (0.5 + 0.73 * 0.5)) - th // 2
        draw.text(((W - tw) // 2, y), text_line, font=f, fill=(255, 222, 0),
                  stroke_width=6, stroke_fill=(0, 0, 0))

    if not out:
        out = rf"F:\JYAutoEdit\data\preview_{draft_name}_{frame_index}.png"
    img.save(out)
    return out


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "口播成品-01"
    idx = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    print(render(name, idx))
