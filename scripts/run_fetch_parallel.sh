#!/bin/bash
# NUC 上并行抽取 4 片（4 核），各写独立分片文件
TPL=/tmp/tpl_people.jsonl
OUT=/home/liuyimin/jiaheji-data
rm -f "$OUT"/full_sh*.jsonl "$OUT"/fetch_sh*.log
for i in 0 1 2 3; do
  skip=$((i * 21303))
  setsid nohup python3 -u /tmp/fetch_full.py "$TPL" "$OUT/full_sh$i.jsonl" $skip 21303 \
    > "$OUT/fetch_sh$i.log" 2>&1 < /dev/null &
done
sleep 2
echo "launched 4 shards; pids:"; pgrep -af fetch_full | grep -v pgrep
