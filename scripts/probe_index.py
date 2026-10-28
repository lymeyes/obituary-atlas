#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""title_tok 是按单字空格切分的，需用短语查询"""
import sqlite3, json, time

DB = "/home/liuyimin/jiaheji-data/zhwiki.db"
OUT = "/tmp/probe5.json"
con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
con.execute("PRAGMA query_only=1")

def tok(name):
    """把中文名切成 FTS 短语：'毛 泽 东'"""
    return " ".join(list(name))

def find(name, limit=3):
    t = time.time()
    expr = 'title_tok:"%s"' % tok(name)
    try:
        rows = con.execute("SELECT rowid,title FROM docs WHERE docs MATCH ? LIMIT ?",
                           (expr, limit)).fetchall()
        return {"q": expr, "sec": round(time.time()-t,3), "rows": [list(r) for r in rows]}
    except Exception as e:
        return {"q": expr, "error": str(e)[:150]}

res = {}
names = ["毛泽东","鲁迅","张国荣","梅艳芳","钱学森","李玟","蔡澜","邓小平","袁隆平","习近平","张爱玲","巴金"]
for n in names:
    res[n] = find(n)

# 命中的取详情
for n in ["毛泽东","张国荣"]:
    h = res[n].get("rows")
    if h:
        rid = h[0][0]
        t=time.time()
        r = con.execute("SELECT length(text),categories FROM docs WHERE rowid=?", (rid,)).fetchone()
        res["_detail_"+n] = {"sec":round(time.time()-t,3),"text_len":r[0],"cats":(r[1] or "")[:350]}
        t=time.time()
        r2 = con.execute("SELECT substr(text,1,800) FROM docs WHERE rowid=?", (rid,)).fetchone()
        res["_text_"+n] = {"sec":round(time.time()-t,3),"body":(r2[0] if r2 else "")[:800]}

with open(OUT,"w",encoding="utf-8") as f:
    json.dump(res,f,ensure_ascii=False,indent=1)
print("ok")
