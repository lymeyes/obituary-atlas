#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断 2：@某人的 text 里有没有 [[Category:YYYY年逝世]]，以及 7403 命中者长什么样"""
import json
import sqlite3
import sys

DB = "/home/liuyimin/jiaheji-data/zhwiki.db"
con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
con.execute("PRAGMA query_only=1")


def tok(n):
    return " ".join(list(n))


def one(name):
    for t, text, cats in con.execute(
            "SELECT title, text, categories FROM docs WHERE docs MATCH ? LIMIT 3",
            ('title_tok:"%s"' % tok(name),)).fetchall():
        if t == name:
            return t, text or "", cats or ""
    return None


# 1) 姚贝娜：text 是维基源码还是纯文本？
r = one("姚贝娜")
if r:
    t, text, cats = r
    print("【%s】长度 %d" % (t, len(text)))
    print("  含 '[[' :", text.count("[["), " 含 '{{' :", text.count("{{"))
    print("  含 'Category':", text.count("Category"))
    i = text.find("2015")
    print("  2015 附近:", repr(text[max(0, i - 60):i + 80]) if i >= 0 else "无 2015")
    print("  分类:", cats[:200])

# 2) 从扫描命中里抽 3 个，看分类里年份逝世类的样子
hits = []
for ln in open("/home/liuyimin/jiaheji-data/deaths_all.jsonl", encoding="utf-8"):
    hits.append(json.loads(ln)["t"])
print("\n扫描命中样例:", hits[:8])

for name in hits[:3]:
    r = one(name)
    if not r:
        print("  %s 未命中" % name)
        continue
    t, text, cats = r
    yr = [c for c in cats.split() if "年" in c and ("逝世" in c or "去世" in c)]
    print("  %-14s len=%-6d 年份类=%s | 源码[[]]=%d Category=%d"
          % (t, len(text), yr or "无", text.count("[["), text.count("Category")))
