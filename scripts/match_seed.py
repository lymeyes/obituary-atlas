#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对 385 个种子人物做 zhwiki 命中测试"""
import sqlite3, json, time, re

DB = "/home/liuyimin/jiaheji-data/zhwiki.db"
SEED = "/tmp/seed385.json"
OUT = "/tmp/match385.json"

con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
con.execute("PRAGMA query_only=1")


def tok(name):
    return " ".join(list(name))


def variants(name):
    """生成检索变体：原名 / 去间隔号 / 去括号内容 / 繁简互换留给后续"""
    out = [name]
    s = re.sub(r"[·・\-\s]", "", name)
    if s != name:
        out.append(s)
    s2 = re.sub(r"[（(].*?[）)]", "", name).strip()
    if s2 and s2 != name:
        out.append(s2)
    return out


def find(name):
    for v in variants(name):
        expr = 'title_tok:"%s"' % tok(v)
        try:
            rows = con.execute(
                "SELECT rowid,title,length(text) FROM docs WHERE docs MATCH ? LIMIT 5",
                (expr,)).fetchall()
        except Exception:
            continue
        if not rows:
            continue
        # 优先选标题完全等于变体的
        exact = [r for r in rows if r[1] == v]
        pick = exact[0] if exact else rows[0]
        return {"variant": v, "rowid": pick[0], "title": pick[1], "len": pick[2],
                "exact": bool(exact), "cand": len(rows)}
    return None


seed = json.load(open(SEED, encoding="utf-8"))
res = {"hit": [], "miss": [], "stats": {}}
t0 = time.time()

for p in seed:
    name = p.get("name", "").strip()
    if not name:
        continue
    h = find(name)
    if h:
        res["hit"].append({"name": name, "died": p.get("died"), "cat": p.get("cat"),
                           "region": p.get("region"), **h})
    else:
        res["miss"].append({"name": name, "died": p.get("died"), "cat": p.get("cat"),
                            "en": p.get("en")})

res["stats"] = {
    "total": len(seed),
    "hit": len(res["hit"]),
    "miss": len(res["miss"]),
    "exact": sum(1 for x in res["hit"] if x["exact"]),
    "avg_len": int(sum(x["len"] for x in res["hit"]) / max(1, len(res["hit"]))),
    "sec": round(time.time() - t0, 1),
}
json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(res["stats"], ensure_ascii=False))
