#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看 FTS 命中的正文长什么样，判断为何 no_date"""
import sqlite3
import sys

DB = "/home/liuyimin/jiaheji-data/zhwiki.db"
con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
con.execute("PRAGMA query_only=1")

q = ('text_tok:"逝 世" OR text_tok:"去 世" OR text_tok:"病 逝" OR text_tok:"离 世" '
     'OR text_tok:"遇 害" OR text_tok:"遇 刺"')
n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
for i, (t, text, cats) in enumerate(con.execute(
        "SELECT title, text, categories FROM docs WHERE docs MATCH ? LIMIT ?", (q, n))):
    print("=" * 70)
    print("[%d] %s  len=%d" % (i, t, len(text or "")))
    print("CATS:", (cats or "")[:120])
    print("HEAD:", (text or "")[:420].replace("\n", " ⏎ "))
    j = (text or "").find("逝世")
    if j < 0:
        j = (text or "").find("去世")
    print("命中处:", (text or "")[max(0, j - 120):j + 120].replace("\n", " ⏎ "))
