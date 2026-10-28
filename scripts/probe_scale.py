#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量级探测：正文含死亡词的条目有多少，年份分布如何（用 FTS 索引计数，不读正文）"""
import sqlite3

DB = "/home/liuyimin/jiaheji-data/zhwiki.db"
con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
con.execute("PRAGMA query_only=1")

total = con.execute("SELECT count(*) FROM docs").fetchone()[0]
print("全库条目:", total)

for w in ["逝 世", "去 世", "過 世", "辭 世", "病 逝", "离 世", "遇 害"]:
    n = con.execute("SELECT count(*) FROM docs WHERE docs MATCH ?",
                    ('text_tok:"%s"' % w,)).fetchone()[0]
    print("  含 %-6s : %7d" % (w.replace(" ", ""), n))

n = con.execute("SELECT count(*) FROM docs WHERE docs MATCH ?",
                ('text_tok:"逝 世" OR text_tok:"去 世" OR text_tok:"過 世" OR text_tok:"辭 世"',)).fetchone()[0]
print("去重（任一死亡词）:", n)
