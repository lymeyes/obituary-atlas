#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""驾鹤集 · 从 zhwiki dump 全量发现逝世人物

原理：中文维基人物条目底部几乎都有 [[Category:YYYY年逝世]]（繁简不一），
这是比 FTS 索引 categories 字段更原始的入口（索引构建时年份分类被过滤了）。

输出 JSONL：{"t": 标题, "dy": 逝世年, "by": 出生年, "n": 正文长度}

用法：
  python3 scan_dump.py --dump <xml.bz2> --out out.jsonl [--limit N] [--workers N]
"""
import argparse, bz2, json, re, sys, time

PAGE_RE = re.compile(rb"<page>(.*?)</page>", re.S)
TITLE_RE = re.compile(rb"<title>(.*?)</title>", re.S)
# 年份分类：繁简、有无空格都要兼容
DEATH_CAT = re.compile(r"\[\[\s*(?:Category|分類|分类)\s*:\s*(\d{4})\s*年(?:逝世|去世|过世|過世|辭世|辞世)".encode("utf-8"))
BIRTH_CAT = re.compile(r"\[\[\s*(?:Category|分類|分类)\s*:\s*(\d{4})\s*年(?:出生|生)".encode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0, help="最多处理多少页（0=不限）")
    ap.add_argument("--progress", type=int, default=200000)
    a = ap.parse_args()

    t0 = time.time()
    pages = hits = 0
    buf = b""
    out = open(a.out, "w", encoding="utf-8")

    with bz2.open(a.dump, "rb") as f:
        while True:
            chunk = f.read(8 << 20)          # 8MB
            if not chunk:
                break
            buf += chunk
            # 只处理已闭合的 <page>
            last = buf.rfind(b"</page>")
            if last == -1:
                continue
            work, buf = buf[:last + 7], buf[last + 7:]
            for m in PAGE_RE.finditer(work):
                body = m.group(1)
                pages += 1
                tm = TITLE_RE.search(body)
                if not tm:
                    continue
                dm = DEATH_CAT.search(body)
                if not dm:
                    continue
                hits += 1
                try:
                    title = tm.group(1).decode("utf-8")
                except UnicodeDecodeError:
                    continue
                bm = BIRTH_CAT.search(body)
                # 正文长度：粗略用 text 段长度
                out.write(json.dumps({
                    "t": title,
                    "dy": int(dm.group(1).decode()),
                    "by": int(bm.group(1).decode()) if bm else None,
                    "n": len(body),
                }, ensure_ascii=False) + "\n")
                if a.limit and pages >= a.limit:
                    break
            if a.progress and pages % a.progress < 1000:
                print("pages=%d hits=%d %.1fs" % (pages, hits, time.time() - t0),
                      file=sys.stderr, flush=True)
            if a.limit and pages >= a.limit:
                break
    out.close()
    print(json.dumps({"pages": pages, "hits": hits,
                      "sec": round(time.time() - t0, 1)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
