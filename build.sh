#!/usr/bin/env bash
# 驾鹤集 · 一键重建（库 → 笔记 → 站点）
set -e
cd "$(dirname "$0")"
echo "[1/3] 建库"
python3 src/jiaheji/build_db.py
echo "[2/3] 渲染笔记"
python3 src/jiaheji/render_notes.py
echo "[3/3] 渲染站点"
python3 src/jiaheji/render_site.py
echo "完成。入口：out/site/index.html"
