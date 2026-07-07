# 漫剧 AI 制作系统 — 5 Agent 自动串联

> 输入一句需求，自动完成从定调到剪辑方案的完整创作流程。
> 基于 CodeBuddy Skills，所有 Agent 以 Skill 形式运行，无需手动复制 Prompt。

---

## 📐 架构

```
用户：帮我做一集90秒国风修仙漫剧
         │
         ▼
┌──────────────────────────────────────┐
│  manhua-workflow  全流程自动串联引擎   │
│                                      │
│  阶段一：需求定调 → manhua-director    │
│  阶段二：编剧分镜 → manhua-writer      │
│  阶段三：质量校验 → manhua-director    │
│  阶段四：美术绘图 → manhua-artist      │
│  阶段五：动态动画 → manhua-animator    │
│  阶段六：剪辑合成 → manhua-editor      │
│  阶段七：外部工具指引                  │
└──────────────────────────────────────┘
```

---

## 🚀 使用方式

### 全流程自动模式（推荐）

直接在对话中说：

> "帮我做一集90秒竖屏国风修仙漫剧，主角少年误入归墟秘境"

`manhua-workflow` 自动激活，一次性输出全部方案。

### 单环节独立模式

单独调用某个Agent：

> "帮我校验这个分镜表" → `manhua-director`
> "帮我写个分镜表" → `manhua-writer`
> "帮我生成绘图Prompt" → `manhua-artist`
> "帮我做动态视频指令" → `manhua-animator`
> "帮我出剪辑方案" → `manhua-editor`

---

## 📁 文件结构

```
├── README.md
└── .codebuddy/skills/
    ├── manhua-workflow/SKILL.md    ← 全流程自动串联引擎
    ├── manhua-director/SKILL.md    ← 总控导演（定调 + 校验）
    ├── manhua-writer/SKILL.md      ← 编剧分镜（分镜表）
    ├── manhua-artist/SKILL.md      ← 美术总监（绘图Prompt）
    ├── manhua-animator/SKILL.md    ← 动态制作（视频Prompt）
    └── manhua-editor/SKILL.md      ← 剪辑合成（剪辑方案）
```

---

## 🔧 维护规则

每个独立 Skill 文件是各自能力的**唯一权威来源**，`manhua-workflow` 执行时会自动加载。

**优化Agent能力时，只需修改对应的 Skill 文件：**

| 想改什么 | 改哪个文件 |
|---------|-----------|
| 导演校验标准 | `manhua-director/SKILL.md` |
| 编剧分镜规则 | `manhua-writer/SKILL.md` |
| 美术绘图规则 | `manhua-artist/SKILL.md` |
| 动态动画规则 | `manhua-animator/SKILL.md` |
| 剪辑合成规则 | `manhua-editor/SKILL.md` |

**不需要修改 workflow 文件，修改会自动生效。**

---

## ⚙️ 技术规格

| 参数 | 默认值 |
|------|--------|
| 画幅 | 9:16 竖屏 |
| 单镜头时长 | 3-6秒（打斗2-3秒，抒情5-6秒） |
| 转场 | 淡入淡出 0.2秒 |
| 导出分辨率 | 1080×1920, 30fps |
| 时长误差容忍 | ±10% |
