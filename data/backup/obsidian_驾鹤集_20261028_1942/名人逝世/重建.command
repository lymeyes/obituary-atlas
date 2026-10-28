#!/bin/bash
# 双击运行：重建全部笔记 + HTML 仪表盘
cd "$(dirname "$0")" || exit 1
echo "工作目录：$(pwd)"
echo "------------------------------"
python3 _generate.py
echo "------------------------------"
echo "完成。可关闭本窗口。"
