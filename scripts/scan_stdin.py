#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 stdin 读取已解压的 XML 流，提取「YYYY年逝世」条目。

配合：bzip2 -dc zhwiki.xml.bz2 | python3 scan_stdin.py --out deaths.jsonl
比 Python 内建 bz2 快数倍（解压交给 C 实现）。
"""
import argparse, json, re, sys, time

PAGE_RE = re.compile(rb"<page>(.*?)</page>", re.S)
TITLE_RE = re.compile(rb"<title>(.*?)</title>", re.S)
DEATH_CAT = re.compile(
    r"\[\[\s*(?:Category|分類|分类)\s*:\s*(\d{4})\s*年(?:逝世|去世|过世|過世|辭世|辞世)".encode())
BIRTH_CAT = re.compile(
    r"\[\[\s*(?:Category|分類|分类)\s*:\s*(\d{4})\s*年(?:出生|生)".encode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--progress", type=int, default=100000)
    a = ap.parse_args()

    t0 = time.time()
    pages = hits = 0
    buf = b""
    out = open(a.out, "w", encoding="utf-8")
    src = sys.stdin.buffer

    while True:
        chunk = src.read(32 << 20)      # 32MB
        if not chunk:
            break
        buf += chunk
        last = buf.rfind(b"</page>")
        if last == -1:
            if len(buf) > 64 << 20:      # 防御：单页异常巨大
                buf = buf[-1 << 20:]
            continue
        work, buf = buf[:last + 7], buf[last + 7:]
        for m in PAGE_RE.finditer(work):
            body = m.group(1)
            pages += 1
            dm = DEATH_CAT.search(body)
            if not dm:
                continue
            tm = TITLE_RE.search(body)
            if not tm:
                continue
            hits += 1
            try:
                title = tm.group(1).decode("utf-8")
            except UnicodeDecodeError:
                continue
            bm = BIRTH_CAT.search(body)
            out.write(json.dumps({
                "t": title,
                "dy": int(dm.group(1).decode()),
                "by": int(bm.group(1).decode()) if bm else None,
                "n": len(body),
            }, ensure_ascii=False) + "\n")
        if a.progress and pages // a.progress != (pages - 0) // a.progress:
            pass
        if pages % a.progress < 3000:
            print("pages=%d hits=%d %.1fs" % (pages, hits, time.time() - t0),
                  file=sys.stderr, flush=True)
    out.close()
    print(json.dumps({"pages": pages, "hits": hits,
                      "sec": round(time.time() - t0, 1)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
