"""Add picture and BGM tracks to an existing draft.

B-roll is placed on its own video track: the timeline is split into equal slots
(default: one picture per N subtitles) and every slot gets one photo. The BGM
goes on a fresh audio track covering the whole timeline.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Iterable, Optional

from . import drafts
from .builder import fragments
from .common import log, new_id, tr, uid4

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


def _support(materials: dict, frag: dict, kind: str, count: int = 1) -> list[str]:
    """Create `count` helper materials of a known kind, returning their ids."""
    ids = []
    for _ in range(count):
        m = copy.deepcopy(frag)
        m["id"] = new_id()
        materials.setdefault(kind, []).append(m)
        ids.append(m["id"])
    return ids


_KIND_BY_TYPE = {
    "speed": "speeds",
    "placeholder_info": "placeholder_infos",
    "canvas": "canvases",
    "material_animation": "material_animations",
    "sound_channel_mapping": "sound_channel_mappings",
    "material_color": "material_colors",
    "loudness": "loudnesses",
    "vocal_separation": "vocal_separations",
    "beats": "beats",
    "audio_fade": "audio_fades",
}


def _kind_for(material: dict) -> str:
    t = material.get("type", "")
    if t in _KIND_BY_TYPE:
        return _KIND_BY_TYPE[t]
    if "meta_type" in material:
        return "placeholder_infos"
    if "fade_out_duration" in material or "fade_in_duration" in material:
        return "audio_fades"
    if "ai_beats" in material:
        return "beats"
    return "placeholder_infos"


def photo_material(path: str) -> dict:
    frag = fragments()
    mat = copy.deepcopy(frag["videos"])
    mat["id"] = new_id()
    mat["unique_id"] = uid4().replace("-", "")
    mat["type"] = "photo"
    mat["path"] = path.replace("\\", "/")
    mat["material_name"] = os.path.basename(path)
    mat["local_material_id"] = uid4()
    mat["duration"] = 10800000000
    mat["category_name"] = "local"
    if Image is not None:
        try:
            with Image.open(path) as im:
                mat["width"], mat["height"] = im.size
        except Exception as e:
            log(f"  warn: 读取图片尺寸失败 {path}: {e}")
            mat["width"], mat["height"] = 1080, 1920
    return mat


def _photo_segment(material_id: str, start: int, duration: int,
                   materials: dict, scale: float = 1.0) -> dict:
    frag = fragments()
    seg = copy.deepcopy(frag["seg__video"])
    seg["id"] = new_id()
    seg["material_id"] = material_id
    seg["source_timerange"] = tr(0, duration)
    seg["target_timerange"] = tr(start, duration)
    seg["clip"]["scale"] = {"x": scale, "y": scale}
    seg["clip"]["transform"] = {"x": 0.0, "y": 0.0}
    refs = []
    for kind in _VIDEO_REF_KINDS:
        refs += _support(materials, _frag_list(kind)[0], kind)
    seg["extra_material_refs"] = refs
    return seg


_VIDEO_REF_KINDS = ("speeds", "placeholder_infos", "canvases", "material_animations",
                    "sound_channel_mappings", "material_colors", "loudnesses",
                    "vocal_separations")


def _frag_list(kind: str) -> list[dict]:
    f = fragments()
    arr = f.get(f"{kind}__variants") or [f[kind]]
    return [copy.deepcopy(x) for x in arr]


_VIDEO_REFS = None


def _init_refs() -> None:
    global _VIDEO_REFS
    if _VIDEO_REFS is not None:
        return
    _VIDEO_REFS = []
    for kind in ("speeds", "placeholder_infos", "canvases", "material_animations",
                 "sound_channel_mappings", "material_colors", "loudnesses",
                 "vocal_separations"):
        arr = _frag_list(kind)
        _VIDEO_REFS.append(arr[0])


def slot_plan(n_subtitles: int, per_image: int, n_images: int) -> list[tuple[int, int]]:
    """Return (first_subtitle_index, count) per image slot.

    per_image <= 0 means "one slot per picture": the subtitles are spread over
    exactly min(n_images, n_subtitles) slots, so every picture is used once and
    the slot lengths differ by at most one subtitle.
    """
    if per_image <= 0:
        n_slots = max(1, min(n_images, n_subtitles))
        base, extra = divmod(n_subtitles, n_slots)
        slots = []
        i = 0
        for k in range(n_slots):
            take = base + (1 if k < extra else 0)
            if take <= 0:
                continue
            slots.append((i, take))
            i += take
        return slots
    slots = []
    i = 0
    while i < n_subtitles:
        take = min(per_image, n_subtitles - i)
        slots.append((i, take))
        i += take
    return slots


def add_photos(draft: drafts.Draft, paths: Iterable[str],
               per_image: int = 0, fit: str = "contain",
               max_scale: float = 1.0, limit: int = 0) -> int:
    """Place one photo per group of subtitles on a new video track."""
    _init_refs()
    paths = [p for p in paths if os.path.isfile(p)]
    if limit:
        paths = paths[:limit]
    if not paths:
        return 0

    content = draft.load_content()
    materials = content.setdefault("materials", {})
    for k in ("videos", "canvases", "material_colors", "loudnesses"):
        materials.setdefault(k, [])

    text_tracks = [t for t in content.get("tracks", []) if t.get("type") == "text"]
    if not text_tracks:
        raise RuntimeError("草稿里没有文本轨，无法按字幕分组配图")
    subs = sorted(text_tracks[0]["segments"], key=lambda s: s["target_timerange"]["start"])
    if not subs:
        raise RuntimeError("文本轨是空的")

    slots = slot_plan(len(subs), per_image, len(paths))
    if len(slots) > len(paths):
        # more slots than pictures: reuse pictures from the start
        pass

    canvas = content.get("canvas_config") or {}
    cw, ch = int(canvas.get("width") or 1080), int(canvas.get("height") or 1920)

    track = {"id": new_id(), "type": "video", "segments": [], "is_default_name": True}
    timeline_end = int(content.get("duration") or 0)
    n = 0
    for idx, (first, count) in enumerate(slots):
        start = subs[first]["target_timerange"]["start"]
        nxt = first + count
        if nxt < len(subs):
            # run up to the next picture's first subtitle so no black frame
            # flashes through the inter-sentence pause
            end = subs[nxt]["target_timerange"]["start"]
        else:
            end = max(timeline_end,
                      subs[-1]["target_timerange"]["start"] + subs[-1]["target_timerange"]["duration"])
        dur = end - start
        if dur <= 0:
            continue
        # strictly sequential; wrap around if there are fewer pictures than slots
        photo = photo_material(paths[idx % len(paths)])
        scale = 1.0
        if fit == "cover" and photo.get("width") and photo.get("height"):
            cover = max(cw / photo["width"], ch / photo["height"])
            contain = min(cw / photo["width"], ch / photo["height"])
            scale = min(max_scale * 4, cover / contain) if contain else 1.0
        seg = _photo_segment(photo["id"], start, dur, materials, scale)
        materials["videos"].append(photo)
        track["segments"].append(seg)
        n += 1

    tracks = content.setdefault("tracks", [])
    existing = [i for i, t in enumerate(tracks) if t.get("type") == "video"]
    if existing:
        tracks[existing[0]] = track
    else:
        tracks.insert(0, track)

    content["duration"] = max(int(content.get("duration") or 0),
                              max(s["target_timerange"]["start"] + s["target_timerange"]["duration"]
                                  for s in track["segments"]))
    draft.save_content(content)
    counts = [c for _, c in slots]
    per = f"{min(counts)}-{max(counts)}" if min(counts) != max(counts) else str(counts[0])
    log(f"  已铺 {n} 张图片（每张 {per} 条字幕）")
    return n


def add_bgm(draft: drafts.Draft, path: str, volume: float = 0.08,
            fade_out_s: float = 1.8, loop: bool = True) -> None:
    """Add a BGM track covering the whole timeline."""
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    content = draft.load_content()
    materials = content.setdefault("materials", {})
    for k in ("audios", "audio_fades", "beats", "speeds", "placeholder_infos",
              "sound_channel_mappings", "vocal_separations"):
        materials.setdefault(k, [])

    total = int(content.get("duration") or 0)
    if total <= 0:
        raise RuntimeError("草稿时长为 0")

    src_dur = _audio_duration_us(path)
    if src_dur <= 0:
        raise RuntimeError(f"读不出音频时长: {path}")

    mat = {
        "id": new_id(),
        "unique_id": uid4().replace("-", ""),
        "type": "extract_music",
        "name": os.path.basename(path),
        "duration": src_dur,
        "path": path.replace("\\", "/"),
        "category_name": "local",
        "music_id": uid4(),
        "resource_id": uid4(),
        "local_material_id": uid4(),
        "similiar_music_info": {},
        "tts_benefit_info": {"benefit_type": "none"},
    }
    materials["audios"].append(mat)

    # cover the timeline, repeating the track when it is shorter than the video
    spans: list[tuple[int, int]] = []
    cursor = 0
    while cursor < total:
        dur = min(src_dur, total - cursor) if loop else total - cursor
        if dur <= 0:
            break
        spans.append((cursor, dur))
        cursor += dur
        if not loop:
            break

    segs = []
    for i, (start, dur) in enumerate(spans):
        refs = []
        for kind in ("speeds", "placeholder_infos", "audio_fades", "beats",
                     "sound_channel_mappings", "vocal_separations"):
            m = copy.deepcopy(_frag_list(kind)[0])
            m["id"] = new_id()
            if "fade_out_duration" in m:
                last = i == len(spans) - 1
                m["fade_out_duration"] = int(fade_out_s * 1_000_000) if last else 0
            materials.setdefault(kind, []).append(m)
            refs.append(m["id"])
        segs.append({
            "id": new_id(),
            "source_timerange": tr(0, dur),
            "target_timerange": tr(start, dur),
            "render_timerange": {},
            "volume": float(volume),
            "material_id": mat["id"],
            "extra_material_refs": refs,
            "enable_lut": False,
            "enable_adjust": False,
            "enable_hsl": False,
            "track_render_index": 4,
            "responsive_layout": {},
            "enable_adjust_mask": False,
            "source": "segmentsourcenormal",
        })

    track = {"id": new_id(), "type": "audio", "segments": segs, "is_default_name": True}
    content.setdefault("tracks", []).append(track)
    draft.save_content(content)
    log(f"  已加入 BGM：{os.path.basename(path)}（{src_dur/1_000_000:.1f}s，"
        f"{len(segs)} 段覆盖 {total/1_000_000:.1f}s，音量 {volume:.2f}）")


MUSIC_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")


def _column_flatness(im: "Image.Image") -> list[float]:
    """Per-column colour variance: gutters between comic panels are flat."""
    g = im.convert("L")
    w, h = g.size
    px = g.load()
    step = max(1, h // 120)
    ys = list(range(0, h, step))
    n = len(ys)
    out = []
    for x in range(w):
        s = 0
        s2 = 0
        for y in ys:
            v = px[x, y]
            s += v
            s2 += v * v
        mean = s / n
        out.append(s2 / n - mean * mean)
    return out


def _gutter_cuts(flat: list[float], n: int) -> list[int]:
    """Choose n-1 cut positions near the even splits, at the flattest columns."""
    w = len(flat)
    cuts = []
    for i in range(1, n):
        target = int(round(w * i / n))
        span = max(4, int(w * 0.10))
        lo = max(1, target - span)
        hi = min(w - 1, target + span)
        best = min(range(lo, hi), key=lambda x: flat[x])
        cuts.append(best)
    return cuts


def split_stack(paths: list[str], out_dir: str, canvas_w: int = 1080,
                canvas_h: int = 1920, min_ratio: float = 1.15) -> list[str]:
    """Turn wide pictures into portrait ones by cutting and stacking panels.

    A landscape comic page leaves huge black bands on a vertical canvas. Cutting
    it into n strips and stacking them fills the frame — and the cuts are placed
    on the flattest columns so panel gutters are used instead of bisecting
    artwork or speech bubbles.
    """
    if Image is None:
        return paths
    os.makedirs(out_dir, exist_ok=True)
    target = canvas_w / canvas_h
    out: list[str] = []
    for p in paths:
        try:
            with Image.open(p) as im:
                im = im.convert("RGB")
                w, h = im.size
                ratio = w / h
                if ratio <= min_ratio:
                    out.append(p)
                    continue
                n = max(1, round((ratio / target) ** 0.5))
                if n <= 1:
                    out.append(p)
                    continue
                cuts = _gutter_cuts(_column_flatness(im), n)
                edges = [0] + cuts + [w]
                strips = [im.crop((edges[i], 0, edges[i + 1], h)) for i in range(n)]
                cw = max(s.width for s in strips)
                compos = Image.new("RGB", (cw, h * n), (0, 0, 0))
                for i, s in enumerate(strips):
                    compos.paste(s, ((cw - s.width) // 2, i * h))
                name = os.path.splitext(os.path.basename(p))[0] + f"_stack{n}.png"
                dst = os.path.join(out_dir, name)
                compos.save(dst)
                out.append(dst)
        except Exception as e:
            log(f"  warn: 竖拼失败 {p}: {e}")
            out.append(p)
    return out


def find_music(directory: str, keyword: str = "", newest: bool = True) -> Optional[str]:
    """Pick a BGM file from a folder, by name keyword or newest."""
    if not os.path.isdir(directory):
        return None
    files = [os.path.join(directory, n) for n in os.listdir(directory)
             if n.lower().endswith(MUSIC_EXTS)]
    if keyword:
        hit = [f for f in files if keyword.lower() in os.path.basename(f).lower()]
        if hit:
            files = hit
    if not files:
        return None
    return max(files, key=os.path.getmtime) if newest else sorted(files)[0]


_MP3_BITRATES_V1L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
_MP3_BITRATES_V2L3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]
_MP3_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def _mp3_duration_us(path: str) -> int:
    """Estimate MP3 duration from the first frame header (CBR/VBR average)."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(256 * 1024)
    offset = 0
    if head[:3] == b"ID3":
        tag = head[6:10]
        offset = 10 + ((tag[0] << 21) | (tag[1] << 14) | (tag[2] << 7) | tag[3])
    for i in range(offset, min(len(head) - 4, offset + 200_000)):
        if head[i] != 0xFF or (head[i + 1] & 0xE0) != 0xE0:
            continue
        ver = (head[i + 1] >> 3) & 0x03      # 3=MPEG1, 2=MPEG2, 0=MPEG2.5
        layer = (head[i + 1] >> 1) & 0x03    # 1=Layer III
        if ver == 1 or layer != 1:
            continue
        br_idx = (head[i + 2] >> 4) & 0x0F
        sr_idx = (head[i + 2] >> 2) & 0x03
        if br_idx == 0 or br_idx == 15 or sr_idx == 3:
            continue
        table = _MP3_BITRATES_V1L3 if ver == 3 else _MP3_BITRATES_V2L3
        bitrate = table[br_idx] * 1000
        sample_rate = _MP3_RATES[ver][sr_idx]
        if bitrate <= 0:
            continue
        # Xing/Info header carries the exact frame count
        xing = head.find(b"Xing", i, i + 200) if hasattr(head, "find") else -1
        if xing < 0:
            xing = head.find(b"Info", i, i + 200)
        if xing > 0:
            flags = int.from_bytes(head[xing + 4:xing + 8], "big")
            pos = xing + 8
            if flags & 0x1:
                frames = int.from_bytes(head[pos:pos + 4], "big")
                spf = 1152 if ver == 3 else 576
                return int(frames * spf / sample_rate * 1_000_000)
        audio_bytes = max(0, size - offset)
        return int(audio_bytes / (bitrate / 8) * 1_000_000)
    return 0


def _audio_duration_us(path: str) -> int:
    """Best-effort audio duration."""
    try:
        from mutagen import File as MFile  # type: ignore
        f = MFile(path)
        if f is not None and f.info is not None:
            return int(f.info.length * 1_000_000)
    except Exception:
        pass
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".mp3":
            got = _mp3_duration_us(path)
            if got > 0:
                return got
            return int(os.path.getsize(path) / 16000 * 1_000_000)
        if ext == ".wav":
            size = os.path.getsize(path)
            with open(path, "rb") as f:
                head = f.read(64)
            rate, channels, bits = 44100, 2, 16
            if head[:4] == b"RIFF":
                idx = head.find(b"fmt ")
                if idx > 0:
                    channels = int.from_bytes(head[idx + 10:idx + 12], "little") or 2
                    rate = int.from_bytes(head[idx + 12:idx + 16], "little") or 44100
                    bits = int.from_bytes(head[idx + 22:idx + 24], "little") or 16
            return int((size - 44) / max(1, channels * bits // 8) / rate * 1_000_000)
    except OSError:
        pass
    return 180_000_000
