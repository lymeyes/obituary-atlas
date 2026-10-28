#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断：zhwiki 分类字段里到底有没有「YYYY年逝世」"""
import sqlite3, sys, json

DB = "/home/liuyimin/jiaheji-data/zhwiki.db"
con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
con.execute("PRAGMA query_only=1")


def tok(n):
    return " ".join(list(n))


def look(name):
    rows = con.execute(
        "SELECT title, length(text), categories FROM docs WHERE docs MATCH ? LIMIT 3",
        ('title_tok:"%s"' % tok(name),)).fetchall()
    for t, ln, cats in rows:
        if t == name:
            return t, ln, cats or ""
    return None


for name in sys.argv[1:]:
    r = look(name)
    if not r:
        print("%-12s 未命中" % name)
        continue
    t, ln, cats = r
    cl = cats.split()
    yr = [c for c in cl if "年" in c and ("逝世" in c or "去世" in c or "過世" in c)]
    print("%-12s len=%-7d 分类%2d 条 | 年份逝世类: %s" % (t, ln, len(cl), yr or "无"))
    print("             前12类: %s" % " / ".join(cl[:12]))
