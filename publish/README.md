# 漫剧制作全流程 Agent 套装

一套用于 AI 辅助创作竖屏漫剧（动态漫画）的 Skill 套装，包含 **1 个全流程串联引擎 + 5 个专业角色 Agent**，覆盖从需求到成片的完整制作链路。

## 套装内容

| Skill | 角色 | 说明 |
|-------|------|------|
| `manju-workflow` | 全流程串联引擎 | 输入需求 → 自动依次调用各 Agent → 输出完整制作包 |
| `manju-director` | 总控导演 | 需求定调 + 分镜质量校验 |
| `manju-writer` | 编剧分镜 | 标准化分镜表编写 |
| `manju-artist` | 美术总监 | AI 绘图 Prompt 生成 + 角色场景资产固化 |
| `manju-animator` | 动态制作 | 图生视频 Prompt + 运镜方案 + 风险评估 |
| `manju-editor` | 剪辑合成 | 配音方案 + 剪辑清单 + BGM/字幕/导出参数 |

## 安装方式

### 方式一：从技能市场安装（推荐）

1. 打开 CodeBuddy → 左侧「技能市场」
2. 分别搜索 `manju-workflow`、`manju-director`、`manju-writer`、`manju-artist`、`manju-animator`、`manju-editor`
3. 点击「添加」一键安装

### 方式二：本地导入

将本目录下的 6 个 Skill 文件夹复制到项目的 `.codebuddy/skills/` 目录下：

```
your-project/
└── .codebuddy/
    └── skills/
        ├── manju-workflow/
        │   └── SKILL.md
        ├── manju-director/
        │   └── SKILL.md
        ├── manju-writer/
        │   └── SKILL.md
        ├── manju-artist/
        │   └── SKILL.md
        ├── manju-animator/
        │   └── SKILL.md
        └── manju-editor/
            └── SKILL.md
```

## 使用方式

### 全流程自动模式（推荐）

直接在对话中输入需求，workflow 会自动串联所有 Agent：

```
帮我做一集90秒竖屏国风修仙搞笑漫剧，主角少年带系统，误入归墟秘境成了秘境霸主。
```

AI 会自动依次输出：
1. 🎬 创作定调（题材/人设/节奏）
2. ✍️ 标准化分镜表（自动校验通过）
3. 🎨 逐镜绘图 Prompt
4. 🎥 逐镜视频 Prompt + 风险评估
5. ✂️ 剪辑合成方案
6. 🛠️ 外部工具执行指引

### 单独使用某个 Agent

也可以单独调用任何一个 Agent：

```
@manju-director 校验这份分镜表质量
@manju-writer 帮我写一个悬疑题材的分镜
@manju-artist 生成国风仙侠角色Prompt
@manju-animator 这个镜头怎么加动态效果
@manju-editor 帮我规划BGM和字幕
```

## 优化 Agent 能力

需要优化某个 Agent 的能力时，**只修改对应的 SKILL.md 文件**即可，workflow 会自动加载最新规则：

- 增强编剧能力 → 修改 `manju-writer/SKILL.md`
- 增加 AI 绘图工具 → 修改 `manju-artist/SKILL.md`
- 调整动态元素分级 → 修改 `manju-animator/SKILL.md`
- 补充 BGM 风格 → 修改 `manju-editor/SKILL.md`
- 优化校验标准 → 修改 `manju-director/SKILL.md`

## 版本

v1.0.0

## 许可

MIT
