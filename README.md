# jyauto — 剪映自动剪辑流水线

从 mdocs 拉文章 → 生成竖屏剪映草稿（字幕轨）→ 剪映「文本朗读」配音 → JYAlignTool 对齐 → 铺图片/BGM。

面向 **剪映专业版 11.6.0.14552**（`F:\JianyingPro`）。

---

## 1. 为什么能直接写草稿

剪映 11.6 的 `draft_content.json` / `draft_meta_info.json` 是**加密**的（base64 文本）。
本项目不逆向算法，而是通过 `ctypes` 调用剪映自带的 `videoeditor.dll` 里的导出函数：

| 符号 | 用途 |
|------|------|
| `EncryptUtils::decrypt` | 密文 → 明文 JSON |
| `EncryptUtils::enable` + `EncryptUtils::encrypt` | 明文 → 剪映能读的密文 |
| `lvve::GetDraftFromJson` / `GetJsonFromDraft` | 用剪映引擎自己的解析器校验草稿结构 |

调用约定（MSVC x64，`this = nullptr`，`std::string` 经隐藏返回指针）已在
`jyauto/jycrypto.py` 里手工铺好 32 字节的 `std::string` 布局，加解密回环校验通过。
好处是：剪映升级后只要导出符号还在就继续可用，且不依赖任何第三方二进制。

## 2. 目录

```
F:\JYAutoEdit\
  jyauto\
    jycrypto.py    草稿加解密（调 videoeditor.dll）
    jyvalidate.py  用引擎解析器校验草稿
    drafts.py      草稿目录读写、备份、注册到剪映草稿列表
    builder.py     从字幕列表生成草稿（竖屏画布 + 文本轨）
    images.py      图片轨（按字幕分组铺图）、BGM 轨
    article.py     markdown → 口播字幕分句
    mdocs.py       mdocs HTTP 客户端（x-cli-token）
    jyapp.py       剪映进程：优雅关闭 / 启动
    cli.py         命令行入口
    fragments\     从真实草稿提取的节点模板（skeleton/fragments）
  jyauto\*.ps1     截图、点击、拖拽、聚焦（用于剪映界面自动化）
  data\            截图与中间产物
```

## 3. 用法

环境变量（已写入用户级）：

```
MDOCS_TOKEN=<mdocs 设置页创建的 CLI Token>
MDOCS_SERVER=http://<mdocs-host>:4000
```

```powershell
$py = "C:\Users\发\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
cd F:\JYAutoEdit

# 看各工作空间最新文章
& $py -m jyauto scan

# 抓文章并分句（先看质量）
& $py -m jyauto fetch --doc <文档ID> --show 20

# 生成字幕草稿（横屏 1920x1080）
& $py -m jyauto build --name "我的视频" --doc <文档ID> --limit 40

# 校验（剪映引擎解析）
& $py -m jyauto validate "我的视频"

# 铺图片（每张覆盖 N 条字幕；给 0 则按图片数均分）
& $py -m jyauto images "我的视频" --dir "C:\Users\发\Desktop\250" --per-image 0 --fit cover

# 加 BGM（不写 --file 时从 Downloads 自动挑，默认取最新的一首）
& $py -m jyauto bgm "我的视频" --name "Hollow" --volume 0.08 --fade-out 1.8
& $py -m jyauto bgm "我的视频" --file "C:\Users\发\Downloads\Sustained Silence.mp3"
```

本机 `C:\Users\发\Downloads` 里的现成曲库（已探测为真实时长）：

| 文件 | 时长 |
|---|---|
| Sustained Silence.mp3 | 203.6s |
| Hollow Piano.mp3 | 239.9s（你 10月27日 那版用的就是它） |
| Untitled.mp3 | 239.9s |

音乐比成片短时会自动重复铺满整轨（多段），最后一段带淡出。

**注意：写草稿前必须先完全退出剪映**（剪映只在启动时读草稿列表，退出时会把
`root_meta_info.json` 写回去）。`build` 前请自行确认，或调用：

```powershell
& $py -c "import sys;sys.path.insert(0,'F:\JYAutoEdit');from jyauto import jyapp;jyapp.close()"
```

## 4. 一条命令出成片

```powershell
$py = "C:\Users\发\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
cd F:\JYAutoEdit

& $py -m jyauto run --name "口播成品-01" `
    --doc 7a3b6f29-56cc-402e-9f8f-90ca35c2adb1 `
    --voice 云希 --rate "+30%" `
    --images "C:\Users\发\Desktop\250" --split-stack `
    --bgm-name Sustained
```

`run` 会依次完成：退出剪映 → 拉文章 → 分句 → **逐句合成语音** → 生成草稿
（字幕轨 + 语音轨，时长严丝合缝）→ 铺图片 → 加 BGM → 引擎校验 → 打印草稿路径。

Edge 合成每句尾部自带约 0.7s 静音，默认用剪映自带的 ffmpeg 裁掉首尾静音
（保留 0.06s 换气），实测 8 句能省 6.8s；句与句之间再补 `--pause`（默认 0.12s）。

关键设计：语音是**逐句合成**的，每句音频的真实时长就是字幕片段的时长，
所以「语音与字幕对齐」天生成立，不需要事后对齐，也**不依赖 JYAlignTool**。

| 参数 | 默认 | 说明 |
|---|---|---|
| `--voice` | 云希 | 云健 / 云希 / 晓晓 / 云扬 / 云野，或完整 `zh-CN-*` ID |
| `--rate` | +30% | 抖音常用 1.3 倍速，合成时就加速，不在剪映里变速 |
| `--images` | 桌面\250 | 图片文件夹，按语音段铺满 |
| `--per-image` | 0 | 每张图覆盖几句；0 = 按图片数均分 |
| `--fit` | contain | contain 整图完整显示（上下补黑）/ cover 放大裁切填满 |
| `--split-stack` | 关 | 横图在空白分栏处切两半、上下摞，填满竖屏（漫画推荐） |
| `--bgm-name` | — | 按关键词从 Downloads 挑 BGM；不给则取最新的 |
| `--bgm-volume` | 0.08 | 0～1 |
| `--keep-silence` | 关 | 保留 Edge 每句尾部的静音（默认会裁掉，实测每句约 0.7s） |
| `--keep-tail` / `--keep-head` | 0.18 / 0.06 | 裁剪时每句尾/头保留的静音秒数 |
| `--reuse-voice` | 关 | 复用已合成语音，只重排队时间线（改图片/BGM 时用） |
| `--limit` | 0 | 只取前 N 句（调试用） |

## 4.1 文本与图片的匹配规则

**文本：一行 = 一个字幕段。** 不做标点切分，作者怎么分行就怎么念。

```
上回说到，貘因攻击艾米而被唐柯敌视，在众人劝说下默许医生为她治疗。
病房里，艾咪忽然从床上坐起来
头缠绷带的貘愣住
```

↑ 这就是 3 条字幕。想恢复按标点分句用 `--sentences`；
单行太长想硬切用 `--split-over 24`。

**图片：严格按文件名顺序，一张图覆盖 N 句。** 不猜语义、不做匹配算法。

```
127 句 / 34 图 → 每张 4 句
第 1~4 句 → 第 1 张（按文件名排序后的第一张）
第 5~8 句 → 第 2 张
…
```

图片不够时会从头环绕复用，不会留空。

**对照表**：每次运行都会生成 `data/reports/<草稿名>.md`，
逐句列出「时间码 / 用第几张图 / 图片文件名 / 字数 / 文本」，
可以直接对着它核对顺序对不对、哪句太长。

## 4.2 文章里的参数（front-matter）

```markdown
---
voice: 云希
rate: "+30%"
bgm_name: Sustained
per_image: 3
font_size: 5.0
text_y: -0.73
pause: 0.20
---

正文，一行一句……
```

文章里写了就用文章的；命令行显式传的参数优先级更高。

## 4.3 语音缓存

语音按 `sha1(文本 + 音色 + 语速 + 裁剪参数)` 缓存到 `data/voice/<草稿名>/`。
改一句话只会重新合成那一句。实测第二次跑同一篇：`缓存命中 114，需合成 0`。
强制全部重来用 `--no-cache`。
## 4.4 人工检查

```powershell
& $py -m jyauto sheet "part250-完整"    # 全片缩略图总览（每张图一帧 + 时间码）
& $py -m jyauto report "part250-完整"   # 逐句对照表（时间码 / 图号 / 字数 / 文本）
```

`sheet` 输出的是一张长图，38 个画面排成网格，每个格子带
「图号 + 起止时间」，字幕已经烧在画面上——一眼能看出图序对不对、
哪张图配错了、哪段画面重复了。比在剪映里拖时间轴快得多。

## 4.5 边界

本工具**只生成草稿，不导出、不发布**。
导出请在剪映里按 Ctrl+E；成片检查和发布由人处理。
（无头导出需要复刻剪映的 Lyra 引擎，工程量以天计，当前不做。）
## 5. 分步命令（调试用）

| 阶段 | 状态 |
|---|---|
| 1. mdocs 拉文章 | ✅ |
| 2. 分句成字幕 | ✅ |
| 3. 逐句合成语音（Edge，1.3x） | ✅ |
| 4. 生成草稿（字幕轨 + 语音轨） | ✅ |
| 5. 铺图片 | ✅ 按语音段精确对齐 |
| 6. BGM | ✅ 自动循环铺满 + 淡出 |
| 7. 剪映内「文本朗读」 | ⬜ 可选，需要界面操作；用 Edge 音色则不需要 |
| 8. JYAlignTool 对齐 | ⬜ 已不需要（4. 已保证对齐） |

## 6. 已知限制

- 本机屏幕 1707×960，剪映的时间线面板被压到窗口最底部，**轨道条几乎看不见**
  （剪映自带的「10月27日」草稿同样如此）。这不是草稿的问题，最大化或换大屏即可。
- 竖屏 1080×1920 下字号默认 `--font-size 8.0`，觉得小可调大。
- `images` 的 `cover` 缩放按「cover/contain 比值」估算，极端长图需要手动微调。
- 图片、BGM 路径必须在本机存在；剪映按绝对路径引用素材，移动草稿会断链。
- 语音合成需要联网（Edge TTS）。断网时会重试 3 次后报错。

## 6. 安全

- 改草稿前都会在 `<草稿>\.dshbak\` 留一份原件（`images`/`bgm` 已接入）。
- `root_meta_info.json` 首次改写会留 `.dshbak` 备份。
- 加解密只读写本地草稿文件，不联网。
