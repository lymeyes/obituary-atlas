#!/usr/bin/env bash
# 驾鹤集 · 模板扫描后台跑批（带单实例锁，防止重复启动写乱同一文件）
set -u
D=/home/liuyimin/jiaheji-data
export LC_ALL=C.UTF-8

exec 9>"$D/.tpl_scan.lock"
if ! flock -n 9; then
  echo "[run_tpl] 已有实例在跑，退出" >&2
  exit 0
fi

bzip2 -dc "$D/zhwiki.xml.bz2" \
  | python3 -u /tmp/scan_tpl.py --out "$D/tpl_people.jsonl" --progress 200000
rc=$?
echo "[run_tpl] exit=$rc"
