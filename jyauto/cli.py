"""Command line entry point: python -m jyauto <command> ..."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import article, builder, drafts
from .common import DATA_DIR, JIANYING_VERSION_DIR, US, ensure_dir, log, sec_to_us
from .jyvalidate import DraftValidator
from .mdocs import Mdocs, MdocsError


def _fix_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _mdocs(args) -> Mdocs:
    return Mdocs(server=getattr(args, "server", None), token=getattr(args, "token", None))


def _pick_domain(m: Mdocs, wanted: str) -> str:
    for dom in m.domains():
        if wanted in (dom.get("domainId"), dom.get("domainName")):
            return dom["domainId"]
    names = ", ".join(d.get("domainName", "") for d in m.domains())
    raise SystemExit(f"找不到工作空间: {wanted}\n可选: {names}")


def cmd_scan(args) -> int:
    m = _mdocs(args)
    print(f"mdocs: {m.server}")
    print(f"{'工作空间':<16}{'更新日期':<12}{'类型':<8}标题")
    for name, doc in m.latest_by_domain():
        print(f"{name:<16}{(doc.get('updatedAt') or '')[:10]:<12}"
              f"{doc.get('fileType',''):<8}{doc.get('displayName')}")
    return 0


def cmd_fetch(args) -> int:
    m = _mdocs(args)
    if args.doc:
        doc = m.get(args.doc)
    else:
        domain_id = _pick_domain(m, args.domain) if args.domain else None
        meta = m.latest(domain_id)
        doc = m.get(meta["documentId"])
    body = doc.get("content") or ""
    lines = article.to_subtitles(body, max_chars=args.max_chars)
    if args.limit:
        lines = lines[: args.limit]
    out_dir = ensure_dir(os.path.join(DATA_DIR, "articles"))
    base = os.path.splitext(os.path.basename(doc.get("relativePath") or "article"))[0]
    safe = "".join(c for c in base if c not in r'\/:*?"<>|')[:40] or "article"
    json.dump({"document": {k: doc.get(k) for k in
                            ("documentId", "domainId", "displayName", "relativePath", "updatedAt")},
               "lines": lines},
              open(os.path.join(out_dir, f"{safe}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"文章: {doc.get('displayName')}  ({doc.get('updatedAt')})")
    print(f"正文字数: {len(body)}  字幕条数: {len(lines)}")
    for line in lines[: args.show]:
        print("  ", line)
    return 0


def cmd_build(args) -> int:
    lines = None
    if args.lines_file:
        lines = json.load(open(args.lines_file, encoding="utf-8"))["lines"]
    else:
        m = _mdocs(args)
        if args.doc:
            doc = m.get(args.doc)
        else:
            domain_id = _pick_domain(m, args.domain) if args.domain else None
            meta = m.latest(domain_id)
            doc = m.get(meta["documentId"])
        lines = article.to_subtitles(doc.get("content") or "", max_chars=args.max_chars)
        print(f"文章: {doc.get('displayName')}（{doc.get('updatedAt')}）")
    if args.limit:
        lines = lines[: args.limit]
    print(f"字幕条数: {len(lines)}，预计时长 {sum(builder.estimate_duration_us(l) for l in lines)/US:.1f}s")
    draft = builder.create_draft(args.name, lines, width=args.width, height=args.height,
                                overwrite=args.force,
                                chars_per_second=args.chars_per_second,
                                font_size=args.font_size,
                                transform_y=args.text_y)
    print(f"\n草稿路径: {draft.path}")
    print("下一步: 在剪映里打开该草稿 → 全选文本 → 朗读，生成语音后再做对齐。")
    return 0


def cmd_inspect(args) -> int:
    d = drafts.resolve(args.draft)
    c = d.load_content()
    print(f"草稿: {d.name}  {d.path}")
    meta = d.load_meta() or {}
    print(f"  draft_id: {meta.get('draft_id')}  new_version: {c.get('new_version')}")
    print(f"  画布: {c['canvas_config']}  时长: {c['duration']/US:.2f}s")
    for t in c.get("tracks", []):
        print(f"  轨道 {t.get('type'):<6} 片段 {len(t.get('segments', []))}")
    mats = c.get("materials", {})
    for k, v in mats.items():
        if isinstance(v, list) and v:
            print(f"  素材 {k}: {len(v)}")
    return 0


def cmd_validate(args) -> int:
    d = drafts.resolve(args.draft)
    c = d.load_content()
    v = DraftValidator(JIANYING_VERSION_DIR)
    ok, detail = v.validate(json.dumps(c, ensure_ascii=False, separators=(",", ":")))
    print(f"{'OK ' if ok else 'FAIL'} {d.name}: {detail}")
    return 0 if ok else 1


def cmd_run(args) -> int:
    """One-shot: article -> subtitles -> voice -> draft -> pictures -> BGM."""
    from . import images, jyapp, report, tts
    from .common import DATA_DIR

    jyapp.close()

    # 1. article  (line mode: one line == one subtitle)
    m = _mdocs(args)
    if args.doc:
        doc = m.get(args.doc)
    else:
        domain_id = _pick_domain(m, args.domain) if args.domain else None
        doc = m.get(m.latest(domain_id)["documentId"])
    raw = doc.get("content") or ""
    fm, body = article.parse_front_matter(raw)
    if args.sentences:
        lines = article.to_subtitles(body, max_chars=args.max_chars)
        dropped: list[str] = []
    else:
        lines, dropped = article.to_subtitles_by_line(body, split_over=args.split_over)
    if args.limit:
        lines = lines[: args.limit]

    def pick(key: str, current):
        """文章 front-matter 覆盖命令行默认值，但显式传参优先。"""
        if key in fm and key not in args.explicit:
            return fm[key]
        return current

    voice_name = pick("voice", args.voice)
    rate = pick("rate", args.rate)
    per_image = pick("per_image", args.per_image)
    font_size = pick("font_size", args.font_size)
    text_y = pick("text_y", args.text_y)
    pause = pick("pause", args.pause)
    bgm_name = pick("bgm_name", args.bgm_name)
    if "bgm" in fm and "bgm" not in args.explicit:
        args.bgm = fm["bgm"]

    print(f"文章：{doc.get('displayName')}（{doc.get('updatedAt')}）")
    print(f"模式：{'按标点分句' if args.sentences else '按行切'}　"
          f"字幕 {len(lines)} 条" + (f"（丢弃 {len(dropped)} 行）" if dropped else ""))
    if fm:
        print(f"文章参数：{json.dumps(fm, ensure_ascii=False)}")

    # 2. voice
    voice = tts.resolve_voice(voice_name)
    voice_dir = os.path.join(DATA_DIR, "voice", args.name.replace(os.sep, "_"))
    clips = tts.synthesize(lines, voice_dir, voice=voice, rate=rate,
                           concurrency=args.concurrency, trim=not args.keep_silence,
                           keep_head=args.keep_head, keep_tail=args.keep_tail,
                           use_cache=not args.no_cache)

    # 3. draft
    draft = builder.create_draft(args.name, lines, width=args.width, height=args.height,
                                 overwrite=args.force, clips=clips,
                                 font_size=font_size, transform_y=text_y, gap_s=pause)

    # 4. pictures  (strictly sequential, by filename)
    if args.images:
        paths = [os.path.join(args.images, n) for n in sorted(os.listdir(args.images))
                 if n.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp"))]
        if paths and args.split_stack:
            paths = images.split_stack(
                paths, os.path.join(DATA_DIR, "stacked", args.name), args.width, args.height)
            print(f"横图竖拼：{len(paths)} 张已处理")
        if paths:
            images.add_photos(draft, paths, per_image=per_image,
                              fit=args.fit, limit=args.image_limit)

    # 5. BGM
    bgm = args.bgm
    if not bgm:
        bgm = images.find_music(args.bgm_dir, bgm_name)
    if bgm:
        print(f"BGM：{os.path.basename(bgm)}")
        images.add_bgm(draft, bgm, volume=args.bgm_volume, fade_out_s=args.fade_out)
    else:
        print("（未找到 BGM，跳过）")

    # 6. verify
    v = DraftValidator(JIANYING_VERSION_DIR)
    c = draft.load_content()
    ok, detail = v.validate(json.dumps(c, ensure_ascii=False, separators=(",", ":")))
    print(f"\n校验：{'OK' if ok else 'FAIL'}  {detail}")
    print(f"草稿：{draft.path}")
    print(f"时长：{c['duration']/US:.1f}s   轨道：" +
          "、".join(f"{t['type']}×{len(t['segments'])}" for t in c["tracks"]))

    # 7. human-checkable mapping report
    try:
        rp = report.build_report(args.name)
        print(f"对照表：{rp}")
    except Exception as e:
        print(f"（对照表生成失败：{e}）")

    print("\n打开剪映即可剪辑（草稿已在列表里）。")
    return 0 if ok else 1


def cmd_sheet(args) -> int:
    from . import contact
    path = contact.build_sheet(args.draft, cols=args.cols)
    print(f"总览图：{path}")
    return 0


def cmd_report(args) -> int:
    from . import report
    path = report.build_report(args.draft)
    print(f"对照表：{path}")
    return 0


def cmd_list(args) -> int:
    for d in sorted(drafts.list_drafts(), key=lambda x: os.path.getmtime(x.path), reverse=True):
        try:
            meta = d.load_meta() or {}
            dur = int(meta.get("tm_duration") or 0) / US
            print(f"{d.name:<28} {dur:7.1f}s  {meta.get('draft_id','')}")
        except Exception as e:
            print(f"{d.name:<28} <读取失败: {e}>")
    return 0


def cmd_images(args) -> int:
    from . import images
    d = drafts.resolve(args.draft)
    paths = [os.path.join(args.dir, n) for n in sorted(os.listdir(args.dir))
             if n.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp"))]
    d.backup("images")
    n = images.add_photos(d, paths, per_image=args.per_image, fit=args.fit,
                          limit=args.limit)
    print(f"完成：{n} 张图片已铺到轨道")
    return 0


def cmd_bgm(args) -> int:
    from . import images
    d = drafts.resolve(args.draft)
    path = args.file
    if not path:
        path = images.find_music(args.dir or r"C:\Users\发\Downloads", args.name or "")
        if not path:
            print("error: 目录里没找到音乐文件", file=sys.stderr)
            return 1
    print(f"BGM: {path}")
    d.backup("bgm")
    images.add_bgm(d, path, volume=args.volume, fade_out_s=args.fade_out)
    print("完成：BGM 已加入")
    return 0


def main(argv: list[str] | None = None) -> int:
    _fix_console()
    p = argparse.ArgumentParser(prog="jyauto", description="剪映自动剪辑流水线")
    p.add_argument("--token", help="mdocs CLI Token（默认取 MDOCS_TOKEN）")
    p.add_argument("--server", help="mdocs 服务地址（默认取 MDOCS_SERVER）")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="列出各工作空间最新文章")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("fetch", help="抓取文章并分句")
    s.add_argument("--domain", help="工作空间名称或 ID")
    s.add_argument("--doc", help="指定文档 ID")
    s.add_argument("--max-chars", type=int, default=18)
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--show", type=int, default=10)
    s.set_defaults(func=cmd_fetch)

    s = sub.add_parser("build", help="生成（仅字幕的）剪映草稿")
    s.add_argument("--name", required=True, help="草稿名称")
    s.add_argument("--domain")
    s.add_argument("--doc")
    s.add_argument("--lines-file", help="直接用已分句的 json")
    s.add_argument("--max-chars", type=int, default=18)
    s.add_argument("--sentences", action="store_true",
                   help="按标点分句（默认：一行一句）")
    s.add_argument("--split-over", type=int, default=0, dest="split_over",
                   help="超过 N 字的长行才硬切（0=不切）")
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--width", type=int, default=1920)
    s.add_argument("--height", type=int, default=1080)
    s.add_argument("--chars-per-second", type=float, default=4.8)
    s.add_argument("--font-size", type=float, default=5.0)
    s.add_argument("--text-y", type=float, default=-0.73)
    s.add_argument("--force", action="store_true", help="覆盖同名草稿")
    s.set_defaults(func=cmd_build)

    s = sub.add_parser("inspect", help="查看草稿结构")
    s.add_argument("draft")
    s.set_defaults(func=cmd_inspect)

    s = sub.add_parser("validate", help="用剪映引擎校验草稿 JSON")
    s.add_argument("draft")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("run", help="一条命令：拉文章→配音→生成草稿→铺图→加BGM")
    s.add_argument("--name", required=True, help="草稿名称")
    s.add_argument("--doc", help="mdocs 文档 ID（留空取最新）")
    s.add_argument("--domain", help="工作空间名称或 ID")
    s.add_argument("--voice", default="云希", help="音色：云健/云希/晓晓/云扬 或完整 ID")
    s.add_argument("--rate", default="+30%", help="语速，抖音常用 +30%")
    s.add_argument("--concurrency", type=int, default=4)
    s.add_argument("--max-chars", type=int, default=18)
    s.add_argument("--sentences", action="store_true",
                   help="按标点分句（默认：一行一句）")
    s.add_argument("--split-over", type=int, default=0, dest="split_over",
                   help="超过 N 字的长行才硬切（0=不切）")
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--width", type=int, default=1920)
    s.add_argument("--height", type=int, default=1080)
    s.add_argument("--font-size", type=float, default=5.5)
    s.add_argument("--text-y", type=float, default=-0.73)
    s.add_argument("--pause", type=float, default=0.20, help="句间停顿秒数")
    s.add_argument("--keep-tail", type=float, default=0.18, dest="keep_tail",
                   help="每句尾部保留的静音秒数")
    s.add_argument("--keep-head", type=float, default=0.06, dest="keep_head",
                   help="每句头部保留的静音秒数")
    s.add_argument("--no-cache", action="store_true", dest="no_cache",
                   help="忽略语音缓存，全部重新合成")
    s.add_argument("--keep-silence", action="store_true", dest="keep_silence",
                   help="保留每句尾部的静音（默认裁掉）")
    s.add_argument("--images", default=r"C:\Users\发\Desktop\250", help="图片文件夹")
    s.add_argument("--image-limit", type=int, default=0)
    s.add_argument("--per-image", type=int, default=0)
    s.add_argument("--fit", choices=["contain", "cover"], default="contain")
    s.add_argument("--split-stack", action="store_true", dest="split_stack",
                   help="横图切半上下拼，填满竖屏")
    s.add_argument("--bgm", help="BGM 文件（留空自动挑）")
    s.add_argument("--bgm-dir", default=r"C:\Users\发\Downloads", dest="bgm_dir")
    s.add_argument("--bgm-name", dest="bgm_name", help="按关键词挑 BGM")
    s.add_argument("--bgm-volume", type=float, default=0.08, dest="bgm_volume")
    s.add_argument("--fade-out", type=float, default=1.8, dest="fade_out")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("sheet", help="生成全片缩略图总览（人工检查用）")
    s.add_argument("draft")
    s.add_argument("--cols", type=int, default=4)
    s.set_defaults(func=cmd_sheet)

    s = sub.add_parser("report", help="生成逐句对照表")
    s.add_argument("draft")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("list", help="列出草稿库")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("images", help="把图片铺到草稿的视频轨")
    s.add_argument("draft")
    s.add_argument("--dir", required=True, help="图片文件夹")
    s.add_argument("--per-image", type=int, default=0,
                   help="每张图片覆盖几条字幕（0=按图片数量均分）")
    s.add_argument("--fit", choices=["contain", "cover"], default="contain")
    s.add_argument("--limit", type=int, default=0)
    s.set_defaults(func=cmd_images)

    s = sub.add_parser("bgm", help="给草稿加 BGM")
    s.add_argument("draft")
    s.add_argument("--file", help="音频文件路径（留空则从 --dir 里自动挑）")
    s.add_argument("--dir", default=r"C:\Users\发\Downloads", help="音乐文件夹")
    s.add_argument("--name", help="按文件名关键词挑（如 Hollow）")
    s.add_argument("--volume", type=float, default=0.08)
    s.add_argument("--fade-out", type=float, default=1.8, dest="fade_out")
    s.set_defaults(func=cmd_bgm)

    args = p.parse_args(argv)
    # remember which flags the caller passed explicitly, so front-matter
    # defaults in the article never override a deliberate CLI choice
    explicit = set()
    for tok in (argv if argv is not None else sys.argv[1:]):
        if tok.startswith("--"):
            explicit.add(tok[2:].split("=")[0].replace("-", "_"))
    args.explicit = explicit
    try:
        return args.func(args)
    except (MdocsError, FileExistsError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
