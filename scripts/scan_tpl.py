#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""驾鹤集 · 从维基源码模板抽取生卒日期（结构化、可靠、够快）

为什么必须走模板：
    自由文本里「谁在哪年死的」无法可靠判定——实测句级配对把张国荣抽成 1987、
    科比抽成 2002，因为句中日期常属于作品/事件。中文维基人物条目的生卒几乎都写在
    {{bd|1898年|3月5日|1976年|1月8日}} 这类模板参数里，是结构化字段，解析即零歧义。

性能要点：
    用 bytes.find 定位模板起点（C 实现，几乎免费），只解析命中点后 240 字节，
    不对整页跑正则——上一版全页正则是 209 页/秒，这一版贴近 bzip2 的解压上限。

覆盖模板：
    {{bd}} {{BD}} {{Bd}} {{bda}}                  中文人物生卒（最主流）
    {{death date}} {{death date and age}}          西式逝世日期（含出生）
    {{birth date}} {{birth date and age}}          西式出生日期

输出 tpl_people.jsonl：{t, by,bm,bd, dy,dm,dd, n, src}
"""
import argparse
import json
import re
import sys
import time

YMIN, YMAX = 1976, 2025

LIT = [(b"{{bd|", "bd"), (b"{{BD|", "bd"), (b"{{Bd|", "bd"), (b"{{bda|", "bd"),
       (b"{{death date", "death"), (b"{{Death date", "death"),
       (b"{{birth date", "birth"), (b"{{Birth date", "birth")]

TITLE_RE = re.compile(rb"<title>(.*?)</title>", re.S)
NS_SKIP = re.compile(r"^(?:Wikipedia|維基百科|维基百科|Template|模板|Category|分類|分类|"
                     r"File|文件|Help|幫助|Portal|主題|主题|Talk|討論|讨论|User|用戶|用户)[:：]")
INT = re.compile(rb"\d+")


def tokens(b):
    return [(len(m.group(0)), int(m.group(0))) for m in INT.finditer(b)]


def dates_in(arg):
    """按顺序还原日期列表 [(y,m,d), ...]；年=4 位且 1800–2035 才算"""
    tk = tokens(arg)
    out = []
    i = 0
    while i < len(tk):
        ln, v = tk[i]
        if ln == 4 and 1800 <= v <= 2035:
            y, m_, d_ = v, None, None
            j = i + 1
            if j < len(tk) and tk[j][0] <= 2 and 1 <= tk[j][1] <= 12:
                m_ = tk[j][1]
                k = j + 1
                if k < len(tk) and tk[k][0] <= 2 and 1 <= tk[k][1] <= 31:
                    d_ = tk[k][1]
                    j = k
                i = j
            out.append((y, m_, d_))
        i += 1
    return out


def parse_at(p, i, kind):
    """从命中位置解析模板参数，返回 (born, died, name) 或 None"""
    seg = p[i:i + 240]
    j = seg.find(b"}}")
    seg = seg[:j] if j > 0 else seg
    args = seg.split(b"|")[1:]
    ds = dates_in(b"|".join(args))
    if not ds:
        return None
    if kind == "bd":
        if len(ds) >= 2:
            return ds[0], ds[1], "bd"
        return None
    if kind == "death":
        return (ds[1] if len(ds) >= 2 else None), ds[0], "death"
    return ds[0], None, "birth"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/home/liuyimin/jiaheji-data/tpl_people.jsonl")
    ap.add_argument("--progress", type=int, default=200000)
    a = ap.parse_args()

    t0 = time.time()
    pages = hits = 0
    buf = b""
    out = open(a.out, "w", encoding="utf-8")
    src = sys.stdin.buffer

    while True:
        chunk = src.read(16 << 20)
        if not chunk:
            break
        buf += chunk
        idx = buf.rfind(b"</page>")
        if idx == -1:
            if len(buf) > 32 << 20:
                buf = buf[-1 << 20:]
            continue
        work, buf = buf[:idx + 7], buf[idx + 7:]
        parts = work.split(b"</page>")
        parts.pop()
        pages += len(parts)

        for p in parts:
            # 只要条目（ns=0），讨论页/用户页/模板页占八成，先剔掉省时间
            if b"<ns>0</ns>" not in p:
                continue
            hit = None
            for lit, kind in LIT:
                i = p.find(lit)
                if i >= 0:
                    hit = (i, kind)
                    break
            if not hit:
                continue
            r = parse_at(p, hit[0], hit[1])
            if not r:
                continue
            born, died, tname = r
            tm = TITLE_RE.search(p)
            if not tm:
                continue
            try:
                title = tm.group(1).decode("utf-8")
            except UnicodeDecodeError:
                continue
            if NS_SKIP.match(title):
                continue
            hits += 1
            out.write(json.dumps({
                "t": title,
                "by": born[0] if born else None,
                "bm": born[1] if born else None,
                "bd": born[2] if born else None,
                "dy": died[0] if died else None,
                "dm": died[1] if died else None,
                "dd": died[2] if died else None,
                "n": len(p),
                "src": tname,
            }, ensure_ascii=False) + "\n")

        if pages % a.progress < 6000:
            el = time.time() - t0
            print("pages=%d hits=%d %.0fs (%.0f p/s)" % (pages, hits, el, pages / max(el, 1)),
                  file=sys.stderr, flush=True)

    out.close()
    print("[scan_tpl] done pages=%d hits=%d %.0fs" % (pages, hits, time.time() - t0),
          file=sys.stderr)


if __name__ == "__main__":
    main()
