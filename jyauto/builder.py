"""Build a JianYing draft from a list of subtitle lines.

The generated draft, in its first stage, only contains the text track: one
subtitle segment per line, laid out back-to-back on a portrait canvas. That is
exactly the input stage JianYing's own "文本朗读" needs, and the stage the
alignment tool expects (subtitle count == voice count).
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import time
from typing import Iterable, Optional

from . import drafts
from .common import (DATA_DIR, DRAFT_ROOT, FONT_PATH, US, ensure_dir, log,
                     new_id, sec_to_us, tr, uid4)


FRAG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fragments")
_frag_cache: Optional[dict] = None
_skel_cache: Optional[dict] = None


def fragments() -> dict:
    global _frag_cache
    if _frag_cache is None:
        _frag_cache = json.load(open(os.path.join(FRAG_DIR, "fragments.json"), encoding="utf-8"))
    return _frag_cache


def skeleton() -> dict:
    global _skel_cache
    if _skel_cache is None:
        _skel_cache = json.load(open(os.path.join(FRAG_DIR, "skeleton.json"), encoding="utf-8"))
    return _skel_cache


TEXT_STYLE = {
    "fill": {
        "alpha": 1.0,
        "content": {"render_type": "solid",
                    "solid": {"alpha": 1.0, "color": [1.0, 0.8705882430076599, 0.0]}},
    },
    "font": {"id": "", "path": FONT_PATH},
    "range": [0, 1],
    "size": 5.0,
    "strokes": [{
        "alpha": 1.0,
        "content": {"render_type": "solid",
                    "solid": {"alpha": 1.0, "color": [0.0, 0.0, 0.0]}},
        "width": 0.07999999821186066,
    }],
    "useLetterColor": True,
}


def estimate_duration_us(text: str, chars_per_second: float = 4.8,
                         minimum_s: float = 0.6) -> int:
    n = len(text.strip())
    if n == 0:
        return sec_to_us(minimum_s)
    return sec_to_us(max(minimum_s, n / chars_per_second))


def _text_material(text: str, font_size: float = 5.0,
                   text_color: str = "#ffde00") -> dict:
    frag = fragments()
    mat = copy.deepcopy(frag["texts"])
    mat["id"] = new_id()
    mat["recognize_task_id"] = uid4()
    mat["recognize_text"] = text
    mat["type"] = "subtitle"
    style = copy.deepcopy(TEXT_STYLE)
    style["range"] = [0, max(1, len(text))]
    style["size"] = font_size
    style["fill"]["content"]["solid"]["color"] = _hex_to_rgb(text_color)
    mat["content"] = json.dumps({"styles": [style], "text": text}, ensure_ascii=False)
    mat["text_color"] = text_color
    mat["font_size"] = font_size
    mat["font_path"] = FONT_PATH
    mat["text_to_audio_ids"] = []
    mat["words"] = {}
    mat["current_words"] = {}
    return mat


def _hex_to_rgb(value: str) -> list[float]:
    v = value.lstrip("#")
    if len(v) == 6:
        return [int(v[0:2], 16) / 255.0, int(v[2:4], 16) / 255.0, int(v[4:6], 16) / 255.0]
    return [1.0, 0.87, 0.0]


def _words_for(text: str, duration_us: int) -> dict:
    """Evenly distribute per-character timings (ms) across the segment."""
    chars = [c for c in text]
    n = max(1, len(chars))
    step = duration_us / n / 1000.0
    starts, ends, toks = [], [], []
    for i, ch in enumerate(chars):
        starts.append(int(round(i * step)))
        ends.append(int(round((i + 1) * step)))
        toks.append(ch)
    return {"start_time": starts, "end_time": ends, "text": toks}


def _text_segment(material_id: str, start_us: int, duration_us: int,
                  words: dict, transform_y: float = -0.73) -> dict:
    frag = fragments()
    seg = copy.deepcopy(frag["seg__text"])
    seg["id"] = new_id()
    seg["material_id"] = material_id
    seg["target_timerange"] = tr(start_us, duration_us)
    anim = copy.deepcopy(frag["material_animations"])
    anim["id"] = new_id()
    seg["extra_material_refs"] = [anim["id"]]
    seg["clip"]["transform"] = {"x": 0.0, "y": transform_y}
    seg["_anim"] = anim  # popped by caller
    return seg


def build_text_content(lines: Iterable[str], width: int = 1080, height: int = 1920,
                       fps: float = 30.0, chars_per_second: float = 4.8,
                       font_size: float = 5.0, text_color: str = "#ffde00",
                       transform_y: float = -0.73) -> dict:
    content = copy.deepcopy(skeleton())
    content["id"] = uid4()
    content["name"] = ""
    content["canvas_config"] = {"width": width, "height": height}
    content["fps"] = fps
    content["duration"] = 0
    content["materials"] = {k: [] for k in content["materials"]}

    text_track = copy.deepcopy(fragments()["track__text"])
    text_track["id"] = new_id()
    text_track["segments"] = []

    cursor = 0
    materials = content["materials"]
    for line in lines:
        text = line.strip()
        if not text:
            continue
        dur = estimate_duration_us(text, chars_per_second)
        mat = _text_material(text, font_size=font_size, text_color=text_color)
        seg = _text_segment(mat["id"], cursor, dur, {}, transform_y=transform_y)
        anim = seg.pop("_anim")
        materials["texts"].append(mat)
        materials["material_animations"].append(anim)
        text_track["segments"].append(seg)
        cursor += dur

    content["tracks"] = [text_track]
    content["duration"] = cursor
    return content


def _support(materials: dict, kind: str, variant: int = 0) -> str:
    frag = fragments()
    arr = frag.get(f"{kind}__variants") or [frag[kind]]
    m = copy.deepcopy(arr[min(variant, len(arr) - 1)])
    m["id"] = new_id()
    materials.setdefault(kind, []).append(m)
    return m["id"]


AUDIO_REF_KINDS = ("speeds", "placeholder_infos", "audio_fades", "beats",
                   "sound_channel_mappings", "vocal_separations")


def _voice_material(clip, index: int) -> dict:
    from .common import uid4
    return {
        "id": new_id(),
        "unique_id": uid4().replace("-", ""),
        "type": "extract_music",
        "name": os.path.basename(clip.path),
        "duration": int(clip.duration_us),
        "path": os.path.abspath(clip.path).replace("\\", "/"),
        "category_name": "local",
        "music_id": uid4(),
        "resource_id": uid4(),
        "local_material_id": uid4(),
        "similiar_music_info": {},
        "tts_benefit_info": {"benefit_type": "none"},
    }


def _voice_segment(material_id: str, start_us: int, duration_us: int,
                   materials: dict) -> dict:
    refs = []
    for kind in AUDIO_REF_KINDS:
        mid = _support(materials, kind)
        if kind == "audio_fades":
            # the fragment is cloned from a BGM clip and carries a 1.8s fade;
            # a spoken sentence must not be faded or it sounds like it dies out
            for m in materials["audio_fades"]:
                if m["id"] == mid:
                    m["fade_in_duration"] = 0
                    m["fade_out_duration"] = 0
        refs.append(mid)
    return {
        "id": new_id(),
        "source_timerange": tr(0, duration_us),
        "target_timerange": tr(start_us, duration_us),
        "render_timerange": {},
        "volume": 1.0,
        "material_id": material_id,
        "extra_material_refs": refs,
        "enable_lut": False,
        "enable_adjust": False,
        "enable_hsl": False,
        "track_render_index": 3,
        "responsive_layout": {},
        "enable_adjust_mask": False,
        "source": "segmentsourcenormal",
    }


def build_voiced_content(clips, width: int = 1920, height: int = 1080,
                         fps: float = 30.0, font_size: float = 5.5,
                         text_color: str = "#ffde00",
                         transform_y: float = -0.73, gap_s: float = 0.12) -> dict:
    """Text track + voice track, segment timings taken from the audio."""
    content = copy.deepcopy(skeleton())
    content["id"] = uid4()
    content["name"] = ""
    content["canvas_config"] = {"width": width, "height": height}
    content["fps"] = fps
    content["materials"] = {k: [] for k in content["materials"]}
    materials = content["materials"]

    text_track = copy.deepcopy(fragments()["track__text"])
    text_track["id"] = new_id()
    text_track["segments"] = []
    audio_track = copy.deepcopy(fragments()["track__audio"])
    audio_track["id"] = new_id()
    audio_track["segments"] = []

    cursor = 0
    gap_us = int(gap_s * 1_000_000)
    for i, clip in enumerate(clips):
        text = clip.text.strip()
        if not text:
            continue
        dur = int(clip.duration_us)

        text_mat = _text_material(text, font_size=font_size, text_color=text_color)
        seg = _text_segment(text_mat["id"], cursor, dur, {}, transform_y=transform_y)
        anim = seg.pop("_anim")
        materials["texts"].append(text_mat)
        materials["material_animations"].append(anim)
        text_track["segments"].append(seg)

        voice_mat = _voice_material(clip, i)
        materials.setdefault("audios", []).append(voice_mat)
        audio_track["segments"].append(_voice_segment(voice_mat["id"], cursor, dur, materials))

        cursor += dur + gap_us

    content["tracks"] = [text_track, audio_track]
    content["duration"] = cursor
    return content


# ------------------------------------------------------------------ scaffold
def _pick_seed(exclude: str = "") -> drafts.Draft:
    """Newest draft folder that is not the destination and still has content."""
    exclude = os.path.abspath(exclude) if exclude else ""
    candidates = []
    for d in drafts.list_drafts():
        if os.path.abspath(d.path) == exclude:
            continue
        if not os.path.isfile(d.root_content_path):
            continue
        if not d.timeline_ids():
            continue
        candidates.append(d)
    if not candidates:
        raise RuntimeError("草稿库里没有可用作骨架的草稿")
    return max(candidates, key=lambda d: os.path.getmtime(d.root_content_path))


def _ignore_big(_dir: str, names: list[str]) -> set[str]:
    ignored = set()
    for n in names:
        if n in {".backup", "textReading", "Resources", "video", "matting",
                 "adjust_mask", "smart_crop", "qr_upload", "subdraft", "deepagent"}:
            ignored.add(n)
        elif n.lower().endswith((".mp4", ".wav", ".mp3", ".m4a", ".aac", ".flac", ".tmp", ".bak")):
            ignored.add(n)
    return ignored


def create_draft(name: str, lines: Iterable[str], seed: Optional[drafts.Draft] = None,
                 width: int = 1080, height: int = 1920, overwrite: bool = False,
                 clips=None, **style) -> drafts.Draft:
    dest = os.path.join(DRAFT_ROOT, name)
    if seed is None:
        seed = _pick_seed(exclude=dest)
    if os.path.exists(dest):
        if not overwrite:
            raise FileExistsError(f"草稿已存在: {dest}")
        shutil.rmtree(dest)
    log(f"  从模板草稿复制骨架: {seed.name}")
    shutil.copytree(seed.path, dest, ignore=_ignore_big)

    # drop stale content files; we write them ourselves
    for rel in ("draft_content.json", "draft_content.json.bak", "draft_content.json.jybox",
                "template-2.tmp"):
        p = os.path.join(dest, rel)
        if os.path.isfile(p):
            os.remove(p)
    tl = os.path.join(dest, "Timelines")
    if os.path.isdir(tl):
        for tid in os.listdir(tl):
            d = os.path.join(tl, tid)
            if not os.path.isdir(d):
                continue
            for rel in ("draft_content.json", "draft_content.json.bak",
                        "draft_content.json.jybox", "template-2.tmp"):
                p = os.path.join(d, rel)
                if os.path.isfile(p):
                    os.remove(p)

    draft = drafts.Draft(dest, seed.crypto)
    if clips:
        content = build_voiced_content(clips, width=width, height=height, **style)
    else:
        content = build_text_content(lines, width=width, height=height, **style)
    # content["id"] must be the timeline id, exactly like the engine writes it;
    # a random id makes 剪映 show an empty timeline even though it plays the clips
    tid = draft.active_timeline_id()
    if tid:
        content["id"] = tid
    draft.save_content(content)

    draft_id = uid4().upper()
    meta = draft.load_meta() or {}
    fold = dest.replace("\\", "/")
    meta.update({
        "draft_id": draft_id,
        "draft_name": name,
        "draft_fold_path": fold,
        "draft_root_path": DRAFT_ROOT.replace("/", "\\"),
        "draft_materials": [{"type": t, "value": []} for t in (0, 1, 2, 3, 6, 7, 8)],
        "draft_materials_copied_info": [],
        "draft_new_version": "",
        "draft_type": "",
        "draft_timeline_materials_size_": 0,
        "tm_duration": content["duration"],
        "tm_draft_create": int(time.time() * 1_000_000),
        "tm_draft_modified": int(time.time() * 1_000_000),
        "draft_cover": "draft_cover.jpg",
        "draft_is_invisible": False,
        "draft_need_rename_folder": False,
    })
    draft.save_meta(meta)

    _reset_sidecars(dest)
    drafts.register_in_root_meta(draft, draft_id, name, content["duration"])
    log(f"  草稿已生成: {dest}  （{len(content['tracks'][0]['segments'])} 条字幕, "
        f"{content['duration'] / US:.1f}s）")
    return draft


def _reset_sidecars(dest: str) -> None:
    kv = os.path.join(dest, "key_value.json")
    if os.path.isfile(kv):
        open(kv, "w", encoding="utf-8").write("{}")
    vs = os.path.join(dest, "draft_virtual_store.json")
    if os.path.isfile(vs):
        open(vs, "w", encoding="utf-8").write(
            '{"draft_materials":[],"draft_virtual_store":[]}')
    st = os.path.join(dest, "draft_settings")
    if os.path.isfile(st):
        now = int(time.time())
        open(st, "w", encoding="utf-8").write(
            "[General]\ncloud_last_modify_platform=windows\n"
            f"draft_create_time={now}\ndraft_last_edit_time={now}\n"
            "real_edit_seconds=0\nreal_edit_keys=1\n")
