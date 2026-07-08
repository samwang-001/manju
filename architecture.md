# 架构设计（⚠️ 早期设计文档，以 漫剧全流程.md 为准）

> 本文档为项目初期设计记录，部分工具名和调用方式已过时。
> 当前实际架构和工具链请参见 `漫剧全流程.md`。

## 一、整体架构

```
用户一句话需求
     │
     ▼
┌─────────────────────────────────────────────┐
│  Team Lead: workflow（总控调度）              │
│  - 接收需求 → 拆解任务 → 分配 → 汇总 → 输出  │
│  - 管理任务依赖关系                           │
│  - 监控各 Agent 状态                          │
└──────┬──────┬──────┬──────┬──────────────────┘
       │      │      │      │
       ▼      ▼      ▼      ▼
   director writer  artist  animator  editor
   (审核)   (编剧)   (美术)   (动画)   (剪辑)
```

### 数据流向

```
用户需求
  │
  ├─[阶段1]─► director  输入: 需求 → 输出: 定调方案
  │                                        │
  ├─[阶段2]─► writer    输入: 定调方案 → 输出: 分镜表.md
  │                                        │
  ├─[阶段3]─► director  输入: 分镜表 → 输出: 审核报告.md
  │                                        │
  ├─[阶段4]─► artist    输入: 分镜表 → 输出: images/镜头XX.png
  │                                        │
  ├─[阶段5]─► animator  输入: images/ → 输出: videos/镜头XX.mp4
  │                                        │
  └─[阶段6]─► editor    输入: videos/ + 分镜表 → 输出: final.mp4 + subtitles.srt
```

---

## 二、5 个 Agent 定义

### Agent 1: director（总控导演）
| 属性 | 值 |
|------|-----|
| 角色 | 创意定调 + 质量审核 |
| 输入 | 用户需求 / 分镜表 |
| 输出 | 定调方案.md / 审核报告.md |
| 工具 | Read, Write, Edit |
| 能力 | 纯文字工作，无需外部 API |

### Agent 2: writer（编剧分镜）
| 属性 | 值 |
|------|-----|
| 角色 | 将故事拆解为标准分镜表 |
| 输入 | 定调方案 + 原始素材 |
| 输出 | 分镜表.md（含景别/运镜/时长/对白/音效） |
| 工具 | Read, Write, Edit, WebFetch |
| 能力 | 纯文字工作，可联网查资料 |

### Agent 3: artist（美术总监）★ 需要工具
| 属性 | 值 |
|------|-----|
| 角色 | 为每个分镜生成对应画面 |
| 输入 | 分镜表.md |
| 输出 | images/镜头01.png ~ 镜头NN.png |
| 工具 | Read, Write, Bash（调图片生成 API） |
| 免费 API | Puter.js / Pollinations.ai（见第三节） |

### Agent 4: animator（动态制作）★ 需要工具
| 属性 | 值 |
|------|-----|
| 角色 | 将静态图片转为动态视频片段 |
| 输入 | images/镜头XX.png + 分镜表（运镜描述） |
| 输出 | videos/镜头01.mp4 ~ 镜头NN.mp4 |
| 工具 | Read, Write, Bash（调视频生成 API） |
| 免费 API | ZSky.ai / Magic Hour（见第三节） |

### Agent 5: editor（剪辑合成）★ 需要工具
| 属性 | 值 |
|------|-----|
| 角色 | 拼接视频 + 配音 + 字幕 + BGM |
| 输入 | videos/ + 分镜表（对白/音效/BGM） |
| 输出 | final.mp4 + subtitles.srt |
| 工具 | Read, Write, Bash（FFmpeg + Edge-TTS） |
| 免费工具 | FFmpeg + edge-tts（见第三节） |

---

## 三、免费工具链选型

### 3.1 图片生成：Puter.js / Pollinations.ai

**Puter.js**（推荐首选）
- 完全免费，无限调用，无需 API Key
- 支持 GPT Image、Stable Diffusion、Flux 等模型
- 方式：通过 Node.js 脚本调用 `puter.ai.txt2img()`
- 安装：`npm install puter.js`
- 限制：单张生成，分辨率有限，适合原型验证

**Pollinations.ai**（备选）
- 完全免费，无需注册，REST API
- 调用：`GET https://image.pollinations.ai/prompt/{prompt}`
- 优点：最简单，直接 URL 即可
- 限制：不可控参数，质量一般

### 3.2 视频生成：ZSky.ai / Magic Hour

**ZSky.ai**（推荐首选）
- 免费额度，REST API，`X-API-Key` 认证
- 支持 image-to-video
- 注册即送免费额度

**Magic Hour**（备选）
- 免费 credits，支持 image-to-video
- API：`magichour.ai/api`

### 3.3 TTS 配音：Edge-TTS

- 微软 Edge 的 TTS 服务，完全免费，无需 API Key
- Python 库：`pip install edge-tts`
- 支持 20+ 中文声音（xiaoxiao、yunyang 等）
- 命令行直接使用：`edge-tts --text "你好" --voice zh-CN-XiaoxiaoNeural --write-media output.mp3`

### 3.4 视频合成：FFmpeg

- 开源免费，本地安装
- macOS：`brew install ffmpeg`
- 核心能力：视频拼接、添加音频、添加字幕、调整速度、转场效果

---

## 四、目录结构

```
项目根目录/
├── .codebuddy/
│   └── agents/                    ← Agent 定义文件
│       ├── director.md            ← 总控导演
│       ├── writer.md              ← 编剧分镜
│       ├── artist.md              ← 美术总监
│       ├── animator.md            ← 动态制作
│       └── editor.md              ← 剪辑合成
│
├── skills/                        ← Skill 能力定义（可替换）
│   └── manju/                     ← 漫剧 Skill 包
│       ├── director-skill.md      ← 漫剧定调/审核规则
│       ├── writer-skill.md        ← 漫剧分镜规则
│       ├── artist-skill.md        ← 漫剧美术风格
│       ├── animator-skill.md      ← 漫剧动态规则
│       └── editor-skill.md        ← 漫剧剪辑方案
│
├── projects/                      ← 每个漫剧项目的产物
│   └── {项目名}/
│       ├── 定调方案.md
│       ├── 分镜表.md
│       ├── 审核报告.md
│       ├── images/                ← artist 输出
│       │   ├── 镜头01.png
│       │   └── ...
│       ├── videos/                ← animator 输出
│       │   ├── 镜头01.mp4
│       │   └── ...
│       ├── audio/                 ← editor TTS 输出
│       │   ├── 镜头01.mp3
│       │   └── ...
│       ├── bgm/                   ← 背景音乐
│       ├── final.mp4              ← 最终成品
│       └── subtitles.srt         ← 字幕文件
│
└── tools/                         ← 工具脚本（Agent 调用）
    ├── generate_image.js          ← 调 Puter.js 生成图片
    ├── generate_video.sh          ← 调 ZSky.ai 生成视频
    ├── generate_tts.py            ← 调 Edge-TTS 生成配音
    └── compose_video.sh           ← FFmpeg 合成最终视频
```

---

## 五、任务依赖关系（Workflow 编排）

```
┌──────────┐
│ 阶段1     │ director 定调（无依赖，立即开始）
│ 定调      │
└────┬─────┘
     │ 定调方案.md
     ▼
┌──────────┐
│ 阶段2     │ writer 写分镜（依赖：定调方案）
│ 分镜      │
└────┬─────┘
     │ 分镜表.md
     ▼
┌──────────┐
│ 阶段3     │ director 审核（依赖：分镜表）
│ 审核      │
└────┬─────┘
     │ 审核报告.md（通过后进入并行阶段）
     │
     ├──────────────────────────┐
     ▼                          ▼
┌──────────┐             ┌──────────┐
│ 阶段4     │ artist 生成   │ 阶段5     │ animator 可并行开始
│ 图片      │ 图片         │ 视频      │ （但建议等图片出来）
└────┬─────┘               └────┬─────┘
     │ images/                   │ videos/
     └──────────┬────────────────┘
                ▼
          ┌──────────┐
          │ 阶段6     │ editor 剪辑合成（依赖：videos/ + 分镜表）
          │ 合成      │
          └────┬─────┘
               ▼
          final.mp4 ✅
```

### 并行优化机会
- 阶段4 和阶段5 可以流水线：artist 产出第一张图后，animator 就可以开始处理
- 阶段4 内部：多个镜头的图片可以并行生成
- 阶段5 内部：多个镜头的视频可以并行生成

---

## 六、关键设计原则

### 6.1 Agent 与 Skill 分离

```
Agent（固定员工）         Skill（可替换能力包）
─────────────────        ──────────────────
director.md              manju/director-skill.md   ← 漫剧定调规则
                         ad/director-skill.md      ← 广告定调规则
                         
writer.md                manju/writer-skill.md     ← 漫剧分镜模板
                         ad/writer-skill.md        ← 广告脚本模板

artist.md                manju/artist-skill.md     ← 漫剧画风
                         ad/artist-skill.md        ← 广告视觉风格
```

Agent 的 System Prompt 中动态加载 Skill 文件内容，换项目时只需换 Skill 引用路径。

### 6.2 工具脚本化

每个需要"动手"的操作封装为独立脚本，Agent 通过 Bash 调用：

```bash
# artist 调用
node tools/generate_image.js --prompt "古风少年，月光下..." --output projects/demo/images/镜头01.png

# animator 调用
bash tools/generate_video.sh --image projects/demo/images/镜头01.png --motion "缓慢推镜" --output projects/demo/videos/镜头01.mp4

# editor 调用
python3 tools/generate_tts.py --text "今日，我便要踏破这苍穹！" --voice zh-CN-YunyangNeural --output projects/demo/audio/镜头01.mp3

# 最终合成
bash tools/compose_video.sh --project projects/demo
```

### 6.3 产物文件协议

各 Agent 通过约定的文件路径交换数据，无需直接通信：
- writer 输出 → `projects/{项目}/分镜表.md`
- artist 读取分镜表 → 输出 `projects/{项目}/images/镜头XX.png`
- animator 读取 images/ → 输出 `projects/{项目}/videos/镜头XX.mp4`
- editor 读取 videos/ + 分镜表 → 输出 `projects/{项目}/final.mp4`

---

## 七、下一步实施计划

1. ✅ 架构设计（本文档）
2. ⬜ 安装依赖工具（FFmpeg, edge-tts, puter.js）
3. ⬜ 编写 4 个工具脚本（generate_image / generate_video / generate_tts / compose_video）
4. ⬜ 编写 5 个 Agent 配置（.codebuddy/agents/*.md）
5. ⬜ 端到端测试：用一个简单故事跑通全流程
6. ⬜ 完成后替换为更强的付费 API（SD API、Kling API 等）
