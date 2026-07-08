#!/bin/bash
# 快速新建项目（从模板复制）
# 用法: bash tools/new_project.sh 项目名 "类型/题材"

PROJECT_NAME="$1"
if [ -z "$PROJECT_NAME" ]; then
    echo "用法: bash tools/new_project.sh 项目名 [说明]"
    echo "示例: bash tools/new_project.sh daomu \"盗墓笔记·悬疑短剧\""
    exit 1
fi

DIR="projects/$PROJECT_NAME"
if [ -d "$DIR" ]; then
    echo "❌ 项目 $PROJECT_NAME 已存在"
    exit 1
fi

echo "📁 创建项目: $PROJECT_NAME"
cp -r projects/.template "$DIR"
sed -i '' "s/{项目名}/$PROJECT_NAME/g" "$DIR/README.md" "$DIR/项目状态.md"

echo "✅ 完成"
echo ""
echo "项目结构:"
find "$DIR" -type d | sort | sed 's|[^/]*/|  |g'
echo ""
echo "下一步: 编辑 $DIR/README.md 填入项目信息"
