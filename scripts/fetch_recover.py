#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NUC 补漏：对首轮 miss 的人，用 繁体标题(t) 优先、简体(t_simp) 兜底 双查 FTS。
复用 fetch_full.py 的 fts/pick_cause/pick_bio。只跑 miss 子集，输出独立文件。
用法：python3 fetch_recover.py <miss_tpl.jsonl> <out.jsonl>
"""
import json, sqlite3, sys, time, importlib.util

DB = "/home/liuyimin/jiaheji-data/zhwiki.db"
spec = importlib.util.spec_from_file_location("ff", "/tmp/fetch_full.py")
ff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ff)


def main():
    tpl = sys.argv[1]
    outp = sys.argv[2]
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    con.row_factory = sqlite3.Row
    rows = [json.loads(l) for l in open(tpl, encoding="utf-8")]
    out = open(outp, "w", encoding="utf-8")
    n = miss = err = 0
    t0 = time.time()
    for r in rows:
        title = r.get("t")
        if not title:
            continue
        dy = r.get("dy")
        if not dy or not (1976 <= int(dy) <= 2025):
            continue
        text, cats = None, None
        try:
            for cand in (title, r.get("t_simp")):   # 繁体优先，简体兜底
                if not cand:
                    continue
                t, c = ff.fts(con, cand)
                if t:
                    text, cats = t, c
                    break
        except Exception as e:
            err += 1
            if err <= 5:
                sys.stderr.write("ERR %s: %s\n" % (title, e))
            continue
        if not text:
            miss += 1
            continue
        out.write(json.dumps({
            "title": title,
            "text": text,
            "cats": (cats or "").split(),
            "cause": ff.pick_cause(text, dy),
            "bio_short": ff.pick_bio(text),
            "dy": dy,
        }, ensure_ascii=False) + "\n")
        n += 1
        if n % 500 == 0:
            el = time.time() - t0
            sys.stderr.write("rec fetched %d / miss %d / err %d (%.1f/s)\n" % (n, miss, err, n / el))
            sys.stderr.flush()
    out.close()
    sys.stderr.write("RECOVER_DONE fetched=%d miss=%d err=%d\n" % (n, miss, err))


if __name__ == "__main__":
    main()
