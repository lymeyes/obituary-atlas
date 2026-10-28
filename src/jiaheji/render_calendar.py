#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""驾鹤集 · 日历视图

产出两张视图，全静态、无脚本依赖（Obsidian 沙箱里也能正常显示）：

  calendar.html      年 × 月热力图，1976 年至今，格子深浅=当月逝世人数，点击进年页
  cal/<year>.html    该年逐月真实日历格（周一起），格内直接列姓名，可点进详情页

设计取舍：
- 热力图用表格而非 canvas，禁脚本/无 JS 环境仍完整可读
- 年页只渲染有记录的月份，空月份在页首集中列出，避免 12 张空表把页面拉成几千像素
- 月格按 calendar.monthcalendar 排，周一起（中文习惯）
"""
import calendar as C
import html as H
import os
import time
from collections import defaultdict

WD = ["一", "二", "三", "四", "五", "六", "日"]
BASE_YEAR = 1976

EXTRA_CSS = """
.cal-wrap{overflow-x:auto;padding:4px 0 26px}
nav>.wrap{width:100%}
table.heat{border-collapse:separate;border-spacing:3px;background:none;border:0;margin:0;
  width:100%;table-layout:fixed}
table.heat th{border:0;padding:3px 5px;font-size:12px;color:var(--muted);font-weight:400;text-align:center}
table.heat td{border:0;padding:0}
table.heat td.y{font-size:12.5px;color:var(--muted);padding:0 8px 0 0;text-align:right;
  white-space:nowrap;width:58px}
table.heat td.y a{color:var(--muted)}
.hc{display:block;height:27px;line-height:27px;text-align:center;border-radius:5px;
  font-size:11.5px;color:#fff;text-decoration:none;font-variant-numeric:tabular-nums}
.hc:hover{outline:2px solid #d6c9b0;text-decoration:none}
.hc.z{background:#f1ece3;color:#cdc4b7}
.hc.z:hover{outline:0}
.legend{display:flex;gap:7px;align-items:center;font-size:12.5px;color:var(--muted);
  padding:2px 0 20px;flex-wrap:wrap}
.legend i{width:24px;height:15px;border-radius:4px;display:inline-block}
.yrbar{display:flex;gap:12px;align-items:center;padding:16px 0 4px;font-size:13.5px;color:var(--muted)}
.yrbar a{padding:5px 13px;border:1px solid var(--line);border-radius:8px;background:var(--card)}
.yrbar .mid{margin-left:auto}
.mon{margin:0 0 24px;scroll-margin-top:20px}
.mon h3{margin:16px 0 8px;font-size:16px;font-weight:600}
.mon h3 span{font-size:12.5px;color:var(--muted);font-weight:400;margin-left:8px}
table.mgrid{border-collapse:collapse;background:var(--card);border:1px solid var(--line);
  border-radius:10px;overflow:hidden;margin:0;table-layout:fixed;width:100%}
table.mgrid th{border-bottom:1px solid var(--line);font-size:12px;color:var(--muted);
  text-align:center;padding:7px 0;font-weight:400;background:var(--soft)}
table.mgrid td{border-right:1px solid var(--line);border-bottom:1px solid var(--line);
  vertical-align:top;height:54px;padding:4px 6px;width:14.28%}
table.mgrid td:last-child{border-right:0}
table.mgrid tbody tr:last-child td{border-bottom:0}
table.mgrid td.e{background:#fbf9f5}
.dn{font-size:11.5px;color:#bdb2a4;display:block;margin-bottom:2px;font-variant-numeric:tabular-nums}
.dn.hit{color:var(--accent);font-weight:700}
.nm{display:block;font-size:12.5px;line-height:1.4;margin-bottom:1px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.emptymon{font-size:13px;color:var(--muted);padding:2px 0 10px;line-height:1.9}
"""


def esc(s):
    return H.escape(str(s or ""))


def _shade(n, mx):
    if not n:
        return None
    t = 0.20 + 0.80 * (n / float(max(mx, 1))) ** 0.55
    return "rgba(156,44,31,%.2f)" % t


def month_grid(y, m, by_day):
    """一张真实月历，格内直接列姓名"""
    head = "".join("<th>%s</th>" % w for w in WD)
    body = []
    for wk in C.monthcalendar(y, m):
        cells = []
        for d in wk:
            if d == 0:
                cells.append("<td class='e'></td>")
                continue
            names = by_day.get(d) or []
            cls = "dn hit" if names else "dn"
            inner = "".join(
                "<a class='nm' href='../p/%s.html' title='%s'>%s</a>"
                % (esc(k), esc(n), esc(n)) for k, n in names)
            cells.append("<td><span class='%s'>%d</span>%s</td>" % (cls, d, inner))
        body.append("<tr>%s</tr>" % "".join(cells))
    return ("<table class='mgrid'><thead><tr>%s</tr></thead><tbody>%s</tbody></table>"
            % (head, "".join(body)))


def build(people, site, nav_html):
    """people: load_all() 的记录列表；site: 站点根目录；nav_html: 生成导航的函数"""
    ts = time.strftime("%Y-%m-%d %H:%M")

    # 年 → 月 → 日 → [(key, name)]
    tree = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for p in people:
        dd = p.get("died_date") or ""
        if len(dd) < 7:
            continue
        try:
            y, m = int(dd[:4]), int(dd[5:7])
        except ValueError:
            continue
        if not (1 <= m <= 12) or y < BASE_YEAR:
            continue
        day = 0
        if len(dd) >= 10:
            try:
                day = int(dd[8:10])
            except ValueError:
                day = 0
        tree[y][m][day].append((p["key"], p["name_zh"]))
    # 同日按姓名排序，保证稳定
    for y in tree:
        for m in tree[y]:
            for d in tree[y][m]:
                tree[y][m][d].sort(key=lambda x: x[1])

    years = sorted(tree)
    if not years:
        return 0, 0
    y0, y1 = min(min(years), BASE_YEAR), max(years)
    all_years = list(range(y1, y0 - 1, -1))          # 倒序
    mcount = {y: {m: sum(len(v) for v in tree[y][m].values()) for m in tree[y]}
              for y in tree}
    mx = max(max(mm.values()) for mm in mcount.values())
    total = sum(sum(mm.values()) for mm in mcount.values())

    # ── 热力图 ──
    head = "<tr><th></th>%s</tr>" % "".join("<th>%d</th>" % m for m in range(1, 13))
    body = []
    for y in all_years:
        cells = []
        for m in range(1, 13):
            n = mcount.get(y, {}).get(m, 0)
            if not n:
                cells.append("<td><span class='hc z'>·</span></td>")
            else:
                cells.append("<td><a class='hc' style='background:%s' href='cal/%d.html#m%02d' "
                             "title='%d 年 %d 月：%d 人'>%d</a></td>"
                             % (_shade(n, mx), y, m, y, m, n, n))
        row = "<tr><td class='y'><a href='cal/%d.html'>%d</a></td>%s</tr>" % (y, y, "".join(cells))
        body.append(row)

    legend = ("<div class='legend'><span>人少</span>"
              + "".join("<i style='background:%s'></i>" % _shade(k, mx)
                        for k in (1, max(2, mx // 3), max(3, mx // 2), mx))
              + "<span>人多（最多 %d 人/月）</span>"
              "<span style='margin-left:14px'>· 表示该月无记录</span></div>" % mx)

    page = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>日历 · 驾鹤集</title><link rel="stylesheet" href="style.css"></head><body>
<header><div class="wrap"><h1>日历<small>他们离开的日子</small></h1>
<p class="sub">%d 人 · %d–%d 年 · 按月份铺开，看哪个月最沉</p></div></header>
%s
<div class="wrap">
%s
<div class="cal-wrap"><table class="heat">
<thead>%s</thead><tbody>%s</tbody></table></div>
</div>
<footer>驾鹤集 · 生成于 %s</footer></body></html>""" % (
        total, y0, y1, nav_html("", "calendar"), legend, head, "".join(body), ts)
    with open(os.path.join(site, "calendar.html"), "w", encoding="utf-8") as f:
        f.write(page)

    # ── 年页 ──
    caldir = os.path.join(site, "cal")
    os.makedirs(caldir, exist_ok=True)
    for y in all_years:
        months = sorted(tree.get(y, {}))
        n_all = sum(len(x) for m in months for x in tree[y][m].values())
        empty = [m for m in range(1, 13) if m not in months]

        blocks = []
        for m in months:
            by_day = tree[y][m]
            n_m = sum(len(x) for x in by_day.values())
            blocks.append(
                "<div class='mon' id='m%02d'><h3>%d 年 %d 月<span>%d 人</span></h3>%s</div>"
                % (m, y, m, n_m, month_grid(y, m, by_day)))
        if empty:
            blocks.insert(0, "<p class='emptymon'>本年无记录的月份：%s</p>"
                          % "、".join("%d 月" % m for m in empty))

        i = all_years.index(y)                       # all_years 倒序：i-1 更晚、i+1 更早
        left = ("<a href='%d.html'>← %d 年</a>" % (all_years[i + 1], all_years[i + 1])
                if i + 1 < len(all_years) else "<span></span>")
        right = ("<a href='%d.html'>%d 年 →</a>" % (all_years[i - 1], all_years[i - 1])
                 if i > 0 else "<span></span>")

        ypage = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%d 年 · 驾鹤集</title><link rel="stylesheet" href="../style.css"></head><body>
<header><div class="wrap"><h1>%d 年<small>共 %d 人</small></h1>
<p class="sub"><a href="../calendar.html">← 回到日历总览</a></p></div></header>
%s
<div class="wrap">
<div class="yrbar">%s<span class="mid">%d 年 · %d 个月有记录</span>%s</div>%s
</div>
<footer>驾鹤集 · 生成于 %s</footer></body></html>""" % (
            y, y, n_all, nav_html("../", "calendar"), left, y, len(months), right,
            "".join(blocks), ts)
        with open(os.path.join(caldir, "%d.html" % y), "w", encoding="utf-8") as f:
            f.write(ypage)

    return len(all_years), total
