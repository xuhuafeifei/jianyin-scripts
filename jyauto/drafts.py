"""Read/write JianYing 11.6 draft folders.

A draft folder (11.6 layout) holds the same timeline in two places:

    <draft>/draft_content.json                     <- legacy mirror
    <draft>/Timelines/<timeline_id>/draft_content.json  <- authoritative

Both are encrypted with the engine's own EncryptUtils, so we go through
`jycrypto.DraftCrypto`. Everything else (draft_meta_info.json) is encrypted
the same way; root_meta_info.json (the draft list) stays plaintext.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from typing import Any, Optional

from .common import DRAFT_ROOT, die, log, new_id, uid4
from .jycrypto import DraftCrypto

SKIP_DIRS = {
    ".backup", "textReading", "Resources", "video", "matting",
    "adjust_mask", "smart_crop", "qr_upload", "subdraft", "deepagent",
}
SKIP_SUFFIX = (".mp4", ".wav", ".mp3", ".m4a", ".aac", ".flac")


class Draft:
    def __init__(self, path: str, crypto: Optional[DraftCrypto] = None):
        self.path = os.path.abspath(path)
        self.name = os.path.basename(self.path)
        self._crypto = crypto

    # ---------------------------------------------------------------- crypto
    @property
    def crypto(self) -> DraftCrypto:
        if self._crypto is None:
            from .common import JIANYING_VERSION_DIR
            self._crypto = DraftCrypto(JIANYING_VERSION_DIR)
        return self._crypto

    # ----------------------------------------------------------------- paths
    @property
    def root_content_path(self) -> str:
        return os.path.join(self.path, "draft_content.json")

    @property
    def meta_path(self) -> str:
        return os.path.join(self.path, "draft_meta_info.json")

    @property
    def timelines_dir(self) -> str:
        return os.path.join(self.path, "Timelines")

    def timeline_ids(self) -> list[str]:
        """Timeline ids are directories under Timelines/, whether or not they
        already contain a content file (a freshly scaffolded draft does not)."""
        d = self.timelines_dir
        if not os.path.isdir(d):
            return []
        ids = []
        for n in os.listdir(d):
            p = os.path.join(d, n)
            if os.path.isdir(p) and not n.startswith("."):
                ids.append(n)
        return ids

    def active_timeline_id(self) -> Optional[str]:
        layout = os.path.join(self.path, "timeline_layout.json")
        if os.path.isfile(layout):
            try:
                info = json.loads(open(layout, encoding="utf-8").read())
                active = info.get("activeTimeline")
                if active and active in self.timeline_ids():
                    return active
            except Exception:
                pass
        ids = self.timeline_ids()
        return ids[0] if ids else None

    def content_paths(self) -> list[str]:
        """Every content file that must stay in sync."""
        paths = []
        for tid in self.timeline_ids():
            paths.append(os.path.join(self.timelines_dir, tid, "draft_content.json"))
        if os.path.isfile(self.root_content_path):
            paths.append(self.root_content_path)
        return paths

    # ------------------------------------------------------------------- i/o
    def read_json(self, path: str) -> Any:
        raw = open(path, "rb").read()
        text = raw.lstrip()
        if text[:1] == b"{":
            return json.loads(raw.decode("utf-8-sig"))
        plain = self.crypto.decrypt(raw)
        return json.loads(plain.decode("utf-8-sig"))

    def write_json(self, path: str, obj: Any) -> None:
        plain = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        enc = self.crypto.encrypt(plain)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(enc)
        os.replace(tmp, path)

    def load_content(self) -> dict:
        tid = self.active_timeline_id()
        if tid:
            p = os.path.join(self.timelines_dir, tid, "draft_content.json")
            if os.path.isfile(p):
                return self.read_json(p)
        if os.path.isfile(self.root_content_path):
            return self.read_json(self.root_content_path)
        die(f"找不到草稿内容文件: {self.path}")

    def save_content(self, content: dict) -> None:
        tid = self.active_timeline_id()
        targets = []
        if tid:
            tdir = os.path.join(self.timelines_dir, tid)
            os.makedirs(tdir, exist_ok=True)
            targets.append(os.path.join(tdir, "draft_content.json"))
        targets.append(self.root_content_path)
        for t in targets:
            self.write_json(t, content)

    def load_meta(self) -> Optional[dict]:
        if os.path.isfile(self.meta_path):
            try:
                return self.read_json(self.meta_path)
            except Exception as e:
                log(f"  warn: 读取 draft_meta_info.json 失败 ({e})")
        return None

    def save_meta(self, meta: dict) -> None:
        self.write_json(self.meta_path, meta)

    # ------------------------------------------------------------------ misc
    def backup(self, tag: str = "") -> str:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = os.path.join(self.path, ".dshbak", f"{stamp}{('-' + tag) if tag else ''}")
        os.makedirs(dest, exist_ok=True)
        for p in self.content_paths() + ([self.meta_path] if os.path.isfile(self.meta_path) else []):
            shutil.copy2(p, os.path.join(dest, os.path.basename(os.path.dirname(p)) + "__" + os.path.basename(p)))
        return dest

    def total_duration_us(self, content: dict) -> int:
        ends = []
        for track in content.get("tracks", []):
            for seg in track.get("segments", []):
                rng = seg.get("target_timerange") or {}
                ends.append(int(rng.get("start", 0)) + int(rng.get("duration", 0)))
        return max(ends) if ends else 0


# ---------------------------------------------------------------- discovery
def list_drafts() -> list[Draft]:
    out = []
    for name in os.listdir(DRAFT_ROOT):
        p = os.path.join(DRAFT_ROOT, name)
        if os.path.isdir(p) and os.path.isfile(os.path.join(p, "draft_meta_info.json")):
            out.append(Draft(p))
    return out


def resolve(name_or_path: str) -> Draft:
    if os.path.isdir(name_or_path):
        return Draft(name_or_path)
    candidate = os.path.join(DRAFT_ROOT, name_or_path)
    if os.path.isdir(candidate):
        return Draft(candidate)
    die(f"草稿不存在: {name_or_path}")


def newest_draft() -> Draft:
    drafts = [d for d in list_drafts() if os.path.isfile(d.root_content_path)]
    if not drafts:
        die("草稿库里没有可用草稿")
    return max(drafts, key=lambda d: os.path.getmtime(d.root_content_path))


# ------------------------------------------------------------- registration
def register_in_root_meta(draft: Draft, draft_id: str, name: str, duration_us: int,
                          cover_rel: str = "draft_cover.jpg") -> None:
    """Insert/refresh an entry in the plaintext root draft list."""
    root_meta_path = os.path.join(DRAFT_ROOT, "root_meta_info.json")
    if not os.path.isfile(root_meta_path):
        log("  warn: 未找到 root_meta_info.json，跳过草稿列表注册")
        return
    raw = open(root_meta_path, encoding="utf-8-sig").read()
    root_meta = json.loads(raw)

    store = root_meta.get("all_draft_store") or []
    template = None
    for entry in store:
        if isinstance(entry, dict) and entry.get("draft_json_file"):
            template = entry
            break
    if template is None:
        log("  warn: root_meta_info.json 中没有可参考条目，跳过注册")
        return

    entry = json.loads(json.dumps(template))
    fold = draft.path.replace("\\", "/")
    entry.update({
        "draft_id": draft_id,
        "draft_fold_path": fold,
        "draft_name": name,
        "draft_json_file": f"{fold}/draft_content.json",
        "draft_cover": f"{fold}/{cover_rel}" if cover_rel else "",
        "draft_timeline_materials_size": 0,
        "draft_new_version": "",
        "draft_type": "",
        "streaming_edit_draft_ready": False,
        "tm_draft_cloud_completed": "",
        "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_modified": 0,
        "tm_draft_removed": 0,
        "tm_draft_create": int(time.time() * 1_000_000),
        "tm_draft_modified": int(time.time() * 1_000_000),
        "tm_duration": int(duration_us),
        "draft_is_invisible": False,
        "draft_root_path": DRAFT_ROOT.replace("/", "\\"),
    })
    store = [e for e in store if not (isinstance(e, dict) and str(e.get("draft_fold_path", "")).replace("\\", "/") == fold)]
    store.append(entry)
    root_meta["all_draft_store"] = store
    backup = root_meta_path + ".dshbak"
    if not os.path.isfile(backup):
        shutil.copy2(root_meta_path, backup)
    open(root_meta_path, "w", encoding="utf-8").write(json.dumps(root_meta, ensure_ascii=False))
