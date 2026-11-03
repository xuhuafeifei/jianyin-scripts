"""Per-subtitle voice-over synthesis via Edge neural TTS.

Synthesising line by line is what makes the rest of the pipeline trivial: every
clip's exact duration is known up front, so subtitles are aligned by
construction and no post-hoc alignment pass is needed.

`rate="+30%"` gives the 1.3x pacing short-video platforms expect, without the
pitch artefacts of time-stretching the audio afterwards.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Iterable, Optional

from .common import ensure_dir, log
from .images import _audio_duration_us

DEFAULT_VOICE = "zh-CN-YunjianNeural"
DEFAULT_RATE = "+30%"
FFMPEG = r"F:\JianyingPro\11.6.0.14552\ffmpeg.exe"

# Edge TTS leaves a long tail of silence after every sentence (~0.7s measured),
# which stacks up into seconds of dead air. Trim both ends but keep a generous
# breath so sentences still sound human instead of clipped.
DEFAULT_KEEP_HEAD = 0.06
DEFAULT_KEEP_TAIL = 0.18
SILENCE_DB = "-50dB"


def _silence_filter(keep_head: float, keep_tail: float) -> str:
    return (
        f"silenceremove=start_periods=1:start_threshold={SILENCE_DB}:"
        f"start_silence={keep_head},"
        "areverse,"
        f"silenceremove=start_periods=1:start_threshold={SILENCE_DB}:"
        f"start_silence={keep_tail},"
        "areverse"
    )


def trim_silence(path: str, keep_head: float = DEFAULT_KEEP_HEAD,
                 keep_tail: float = DEFAULT_KEEP_TAIL) -> Optional[str]:
    """Strip leading/trailing silence. Returns the new path (wav) or None."""
    import subprocess
    if not os.path.isfile(FFMPEG):
        return None
    stem = os.path.splitext(path)[0]
    tmp = stem + ".trim.wav"
    out = stem + ".wav"
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
           "-i", path, "-af", _silence_filter(keep_head, keep_tail),
           "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1", tmp]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60)
        if r.returncode == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 1024:
            os.replace(tmp, out)
            if os.path.isfile(path):
                os.remove(path)
            return out
        if os.path.isfile(tmp):
            os.remove(tmp)
    except Exception as e:
        log(f"  warn: 静音裁剪失败 {os.path.basename(path)}: {e}")
    return None


@dataclass
class Clip:
    index: int
    text: str
    path: str
    duration_us: int


async def _synth_one(text: str, voice: str, rate: str, path: str,
                     sem: asyncio.Semaphore, retries: int = 3) -> None:
    import edge_tts
    async with sem:
        last: Optional[Exception] = None
        for attempt in range(retries):
            try:
                comm = edge_tts.Communicate(text, voice, rate=rate)
                await comm.save(path)
                if os.path.isfile(path) and os.path.getsize(path) > 1024:
                    return
                raise RuntimeError("合成结果为空")
            except Exception as e:  # network hiccups are common
                last = e
                await asyncio.sleep(1.2 * (attempt + 1))
        raise RuntimeError(f"语音合成失败: {text[:20]}… ({last})")


def _cache_key(text: str, voice: str, rate: str, keep_head: float, keep_tail: float) -> str:
    import hashlib
    raw = f"{text}|{voice}|{rate}|{keep_head:.2f}|{keep_tail:.2f}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


async def _synth_all(items: list[tuple[str, str]], voice: str, rate: str,
                     concurrency: int) -> None:
    """items = [(text, dst_path_mp3), ...] — only missing files are produced."""
    sem = asyncio.Semaphore(concurrency)
    tasks = [_synth_one(t, voice, rate, p, sem) for t, p in items]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception)]
    if errors:
        raise RuntimeError(f"{len(errors)} 条语音合成失败，第一条：{errors[0]}")


def synthesize(lines: Iterable[str], out_dir: str, voice: str = DEFAULT_VOICE,
               rate: str = DEFAULT_RATE, concurrency: int = 4,
               trim: bool = True, keep_head: float = DEFAULT_KEEP_HEAD,
               keep_tail: float = DEFAULT_KEEP_TAIL,
               use_cache: bool = True) -> list[Clip]:
    """Synthesise one clip per line; returns clips with exact durations.

    Clips are cached by a hash of (text, voice, rate, trim settings), so editing
    one line of the article only re-synthesises that line.
    """
    lines = [l.strip() for l in lines if l.strip()]
    if not lines:
        return []
    ensure_dir(out_dir)

    todo: list[tuple[str, str]] = []
    final: list[Optional[str]] = []
    for text in lines:
        key = _cache_key(text, voice, rate, keep_head, keep_tail)
        wav = os.path.join(out_dir, f"{key}.wav")
        mp3 = os.path.join(out_dir, f"{key}.mp3")
        if use_cache and os.path.isfile(wav) and os.path.getsize(wav) > 1024:
            final.append(wav)
            continue
        if use_cache and os.path.isfile(mp3) and os.path.getsize(mp3) > 1024:
            final.append(mp3)          # already synthesised, trim may still apply
            continue
        final.append(None)
        if all(t[1] != mp3 for t in todo):
            todo.append((text, mp3))

    cached = sum(1 for p in final if p is not None)
    log(f"  语音：{len(lines)} 句，缓存命中 {cached}，需合成 {len(todo)}"
        f"（{voice} {rate}）")
    if todo:
        asyncio.run(_synth_all(todo, voice, rate, concurrency))

    paths: list[str] = []
    to_trim = 0
    before = 0.0
    for text, path in zip(lines, final):
        key = _cache_key(text, voice, rate, keep_head, keep_tail)
        wav = os.path.join(out_dir, f"{key}.wav")
        mp3 = os.path.join(out_dir, f"{key}.mp3")
        if path is None:
            path = mp3 if os.path.isfile(mp3) else wav
        if trim and not os.path.isfile(wav):
            before += _audio_duration_us(path)
            trimmed = trim_silence(path, keep_head, keep_tail)
            if trimmed:
                path = trimmed
                to_trim += 1
            else:
                wav = path
        paths.append(path)

    if trim and to_trim:
        after = sum(_audio_duration_us(p) for p in paths) / 1_000_000
        log(f"  已裁剪首尾静音：{to_trim} 句")

    clips: list[Clip] = []
    for i, (text, path) in enumerate(zip(lines, paths)):
        dur = _audio_duration_us(path)
        if dur <= 0:
            raise RuntimeError(f"读不出音频时长: {path}")
        clips.append(Clip(i, text, path, dur))
    total = sum(c.duration_us for c in clips) / 1_000_000
    log(f"  完成，语音总长 {total:.1f}s")
    return clips


def load_existing(lines: Iterable[str], out_dir: str) -> Optional[list["Clip"]]:
    """Rebuild clips from already-synthesised files, or None if incomplete."""
    lines = [l.strip() for l in lines if l.strip()]
    if not lines:
        return None
    clips: list[Clip] = []
    for i, text in enumerate(lines):
        stem = os.path.join(out_dir, f"line_{i + 1:03d}")
        path = None
        for ext in (".wav", ".mp3"):
            if os.path.isfile(stem + ext) and os.path.getsize(stem + ext) > 1024:
                path = stem + ext
                break
        if path is None:
            return None
        clips.append(Clip(i, text, path, _audio_duration_us(path)))
    return clips


VOICE_PRESETS = {
    "云健": "zh-CN-YunjianNeural",
    "云希": "zh-CN-YunxiNeural",
    "晓晓": "zh-CN-XiaoxiaoNeural",
    "云扬": "zh-CN-YunyangNeural",
    "云野": "zh-CN-YunyeNeural",
}

VOICE_BY_ID = {v: k for k, v in VOICE_PRESETS.items()}


def resolve_voice(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return DEFAULT_VOICE
    if name in VOICE_PRESETS:
        return VOICE_PRESETS[name]
    if name.startswith("zh-CN-"):
        return name
    # substring match: "yunxi" / "云希"
    for alias, vid in VOICE_PRESETS.items():
        if alias in name:
            return vid
    return DEFAULT_VOICE


def list_voices() -> list[dict]:
    try:
        import edge_tts
        voices = asyncio.run(edge_tts.list_voices())
        return [v for v in voices if v.get("Locale", "").startswith("zh-CN")]
    except Exception as e:
        log(f"  warn: 拉取音色列表失败: {e}")
        return []
