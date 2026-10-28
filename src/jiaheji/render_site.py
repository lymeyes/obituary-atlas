#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""驾鹤集 · 静态站点渲染

结构：
  out/site/index.html      概览（统计 + 搜索/筛选 + 全量列表，静态预渲染）
  out/site/p/<key>.html    每人详情页（深度内容 + 原文证据 + 来源）
  out/site/timeline.html   按年时间轴
  out/site/stats.html      统计分析（年代/死因/领域分布）
  out/site/style.css
无外部依赖、无 CDN；JS 仅做筛选增强，禁脚本时仍可读。
"""
import html as H
import json, os, re, shutil, sys, time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import db as D
import render_calendar as CAL

SITE = os.path.join(ROOT, "out", "site")

NAV_ITEMS = [("index.html", "名录", "index"), ("calendar.html", "日历", "calendar"),
             ("timeline.html", "年表", "timeline"), ("stats.html", "统计", "stats")]


def nav_html(prefix="", active="index"):
    parts = []
    for href, label, key in NAV_ITEMS:
        cls = " class='on'" if key == active else ""
        parts.append("<a href='%s%s'%s>%s</a>" % (prefix, href, cls, label))
    return ('<nav><div class="wrap" style="display:flex;gap:22px;flex-wrap:wrap">%s</div></nav>'
            % "".join(parts))

CAUSE_COLOR = {"自杀": "#8b5cf6", "遇害": "#b91c1c", "事故": "#ea580c", "癌症": "#be123c",
               "心脑血管": "#dc2626", "呼吸/感染": "#0891b2", "疾病": "#0d9488",
               "自然衰老": "#65a30d", "其他": "#6b7280", "未知": "#9ca3af"}

CSS = """
:root{
  --bg:#faf8f4; --card:#fffefb; --ink:#241f1c; --muted:#8a7f76;
  --line:#e7e2d9; --accent:#9c2c1f; --accent2:#b8860b; --soft:#f3efe7;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.75 -apple-system,"PingFang SC","Songti SC",Georgia,serif;
  -webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
header{padding:38px 30px 22px;border-bottom:1px solid var(--line);background:
  linear-gradient(180deg,#fffefb 0%,#faf8f4 100%)}
h1{margin:0 0 6px;font-size:30px;letter-spacing:3px;font-weight:600}
h1 small{font-size:13px;letter-spacing:1px;color:var(--muted);font-weight:400;margin-left:10px}
.sub{color:var(--muted);font-size:13.5px;margin:0}
.wrap{max-width:1180px;margin:0 auto;padding:0 30px}
nav{padding:12px 30px;border-bottom:1px solid var(--line);background:var(--card);
  display:flex;gap:22px;font-size:14px;flex-wrap:wrap}
nav a{color:var(--muted)}
nav a.on{color:var(--accent);font-weight:600}
.chips{display:flex;gap:10px;flex-wrap:wrap;padding:20px 0 6px}
.chip{background:var(--card);border:1px solid var(--line);border-radius:999px;
  padding:7px 15px;font-size:13px}
.chip b{color:var(--accent);font-size:15px;margin-right:4px}
.bar{display:flex;gap:10px;flex-wrap:wrap;padding:16px 0;align-items:center}
input[type=search],select{padding:9px 13px;border:1px solid var(--line);border-radius:8px;
  background:var(--card);font-size:14px;font-family:inherit;color:var(--ink)}
input[type=search]{min-width:280px}
input[type=search]:focus,select:focus{outline:2px solid #e3d9c6;border-color:#d6c9b0}
table{width:100%;border-collapse:collapse;background:var(--card);
  border:1px solid var(--line);border-radius:10px;overflow:hidden;margin:6px 0 40px}
th,td{padding:9px 13px;text-align:left;border-bottom:1px solid var(--line);font-size:14px}
th{background:var(--soft);font-weight:600;font-size:13px;color:#5c534b;
  position:sticky;top:0;cursor:pointer;white-space:nowrap;user-select:none}
th:hover{background:#ece5d8}
tr:last-child td{border-bottom:none}
tbody tr:hover{background:#fdfbf6}
td.c{text-align:center;color:var(--muted);font-variant-numeric:tabular-nums}
.tag{display:inline-block;padding:1px 9px;border-radius:999px;background:var(--soft);
  font-size:12px;color:#6b5f54;white-space:nowrap}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;
  vertical-align:middle}
.empty{padding:40px;text-align:center;color:var(--muted)}
footer{padding:26px 30px 50px;color:var(--muted);font-size:12.5px;
  border-top:1px solid var(--line);text-align:center}
/* 详情页 */
.detail{max-width:820px;margin:0 auto;padding:30px 30px 60px}
.detail h1{font-size:32px;letter-spacing:2px;margin-bottom:4px}
.detail .en{color:var(--muted);font-size:14px;font-style:italic;margin-bottom:18px}
.quote{border-left:3px solid var(--accent2);padding:10px 18px;background:var(--card);
  color:#4a4139;font-size:15px;margin:18px 0;border-radius:0 8px 8px 0}
.detail h2{font-size:17px;letter-spacing:1px;margin:30px 0 12px;padding-bottom:7px;
  border-bottom:1px solid var(--line);color:#3b332c}
.detail h2::before{content:"◆";color:var(--accent2);font-size:11px;margin-right:8px;
  vertical-align:middle}
.kv{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
  border-radius:10px;overflow:hidden}
.kv td{padding:9px 14px;border-bottom:1px solid var(--line);font-size:14px}
.kv tr:last-child td{border-bottom:none}
.kv td:first-child{width:110px;color:var(--muted);background:var(--soft)}
.ev{background:#fbf7ee;border:1px solid #ece0c8;border-radius:8px;padding:11px 15px;
  margin:10px 0;font-size:14px;color:#4a4139}
.ev b{color:var(--accent);font-weight:600;font-size:12.5px;letter-spacing:1px}
ul.plain{list-style:none;padding-left:0;margin:8px 0}
ul.plain li{padding:5px 0 5px 16px;position:relative;font-size:14.5px}
ul.plain li::before{content:"·";position:absolute;left:4px;color:var(--accent2);font-weight:700}
.paras p{margin:0 0 13px}
.footnote{color:var(--muted);font-size:12.5px;margin-top:26px}
.back{display:inline-block;margin-bottom:18px;font-size:13.5px;color:var(--muted)}
/* 统计 */
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px;
  margin:10px 0 40px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px}
.panel h3{margin:0 0 14px;font-size:15px;letter-spacing:1px;color:#3b332c}
.hbar{display:flex;align-items:center;gap:10px;margin:7px 0;font-size:13px}
.hbar .lbl{width:88px;color:#5c534b;flex:none;text-align:right}
.hbar .trk{flex:1;background:var(--soft);height:16px;border-radius:4px;overflow:hidden}
.hbar .fil{height:100%;border-radius:4px}
.hbar .num{width:44px;color:var(--muted);font-variant-numeric:tabular-nums;flex:none}
/* 时间轴 */
.year{display:flex;gap:16px;padding:12px 0;border-bottom:1px dashed var(--line)}
.year .y{flex:none;width:64px;font-size:19px;color:var(--accent);font-weight:600;
  font-variant-numeric:tabular-nums}
.year .items{flex:1;font-size:14px;line-height:2}
.year .items span{white-space:nowrap}
@media(max-width:720px){
  .wrap,.detail{padding:0 16px}
  header{padding:26px 16px 16px}
  input[type=search]{min-width:100%}
  table{font-size:13px}
  th,td{padding:7px 8px}
  td:nth-child(3),th:nth-child(3){display:none}
}
"""


def esc(s):
    return H.escape(str(s or ""))


def fmt_date(d):
    if not d:
        return "—"
    p = d.split("-")
    if len(p) >= 3:
        return "%s-%02d-%02d" % (p[0], int(p[1]), int(p[2]))
    if len(p) == 2:
        return "%s-%02d" % (p[0], int(p[1]))
    return d


def age(b, d):
    try:
        y1, m1, d1 = [int(x) for x in b.split("-")[:3]]
        y2, m2, d2 = [int(x) for x in d.split("-")[:3]]
        a = y2 - y1
        if (m2, d2) < (m1, d1):
            a -= 1
        return a
    except Exception:
        return None


def clean(s):
    if not s:
        return ""
    s = re.sub(r"（\s*[，,]\s*）", "", s)
    s = re.sub(r"（\s*）", "", s)
    return s.strip()


def pick_death_sentence(text, name):
    """从全文里挑一句最能说明死讯的原话"""
    if not text:
        return ""
    cands = []
    kw = [("跳楼自杀", 10), ("自杀", 8), ("遇刺", 8), ("病逝", 6), ("去世", 5),
          ("逝世", 4), ("身亡", 6), ("遇难", 6), ("不治", 5), ("辞世", 5)]
    for sent in re.split(r"(?<=[。；])", text):
        s = re.sub(r"\s+", " ", sent).strip()
        # 去掉目录残留的句首短词（如「逝世 跳楼 2003年…」）
        s = re.sub(r"^(?:[^\d，。]{1,5}\s+)+(?=\d{4}年)", "", s)
        s = re.sub(r"^(?:逝世|去世|生平|早年|晚年)\s*", "", s)
        if not (8 <= len(s) <= 160):
            continue
        if any(x in s for x in ("葬礼", "追悼", "追颁", "周年", "纪念", "诞辰", "纪念馆", "遗体")):
            continue
        if name not in s:
            continue
        sc = sum(w for k, w in kw if k in s)
        if sc:
            cands.append((sc, len(s), s))
    if not cands:
        return ""
    cands.sort(key=lambda x: (-x[0], x[1]))
    return cands[0][2]


def load_all():
    D.init()          # 幂等；顺带补齐老库缺失的新列
    with D.connect() as con:
        rows = con.execute("""
            SELECT p.*, r.zh_text, r.zh_cats FROM person p
            LEFT JOIN raw r ON r.person_id=p.id
            WHERE COALESCE(p.excluded,0)=0
            ORDER BY p.died_date DESC
        """).fetchall()
        data = []
        for r in rows:
            rec = dict(r)
            rec["sources"] = [dict(x) for x in con.execute(
                "SELECT field,kind,ref,snippet FROM source WHERE person_id=? ORDER BY id",
                (r["id"],))]
            rec["tl"] = [x["event"] for x in con.execute(
                "SELECT event FROM timeline WHERE person_id=? LIMIT 8", (r["id"],))]
            data.append(rec)
        return data


def build(people):
    os.makedirs(os.path.join(SITE, "p"), exist_ok=True)
    with open(os.path.join(SITE, "style.css"), "w", encoding="utf-8") as f:
        f.write(CSS + CAL.EXTRA_CSS)

    # ── 统计 ──
    total = len(people)
    decades = Counter((p["died_date"] or "0000")[:3] + "0" for p in people if p["died_date"])
    cats = Counter(p["cat"] or "其他" for p in people)
    causes = Counter(p["cause_cat"] or "未知" for p in people)
    regions = Counter(p["region"] or "—" for p in people)
    stats = {"total": total, "decades": decades, "cats": cats,
             "causes": causes, "regions": regions,
             "chars": sum(len(p.get("zh_text") or "") for p in people),
             "verified": sum(1 for p in people if p["status"] == "verified")}

    chips = "".join(
        '<div class="chip"><b>%s</b>%s</div>' % (v, k) for k, v in [
            ("收录人物", total),
            ("维基正文核实", stats["verified"]),
            ("累计正文字数", "%.0f 万" % (stats["chars"] / 10000)),
            ("覆盖年代", "%s–%s" % (min(decades).replace("0s", "") if decades else "",
                                  max(decades).replace("0s", "") if decades else "")),
        ])
    # 修正年代显示
    yrs = sorted(int((p["died_date"] or "0")[:4]) for p in people if p["died_date"])
    chips = "".join(
        '<div class="chip"><b>%s</b>%s</div>' % (v, k) for k, v in [
            ("收录人物", total),
            ("正文可溯源", stats["verified"]),
            ("正文总量", "%.0f 万字" % (stats["chars"] / 10000)),
            ("时间跨度", "%d–%d" % (yrs[0], yrs[-1]) if yrs else "—"),
        ])

    # ── 列表行（静态预渲染）──
    rows = []
    for p in people:
        a = age(p["born_date"] or "", p["died_date"] or "")
        cc = p["cause_cat"] or "未知"
        color = CAUSE_COLOR.get(cc, "#9ca3af")
        rows.append(
            "<tr>"
            "<td class='c'>%s</td>"
            "<td><a href='p/%s.html'>%s</a></td>"
            "<td class='c'>%s</td>"
            "<td class='c'>%s</td>"
            "<td>%s</td>"
            "<td><span class='tag'>%s</span></td>"
            "<td class='c'>%s</td>"
            "</tr>" % (
                esc((p["died_date"] or "")[:4]),
                esc(p["key"]), esc(p["name_zh"]),
                esc((p["born_date"] or "—")[:4]),
                ("%d" % a) if a else "—",
                "<span class='dot' style='background:%s'></span>%s" % (color, esc(p["cause_raw"] or "—")),
                esc(p["cat"] or "—"),
                esc(p["region"] or ""),
            ))

    cat_opts = "".join("<option value='%s'>%s</option>" % (esc(k), esc(k)) for k in cats)
    dec_opts = "".join("<option value='%s'>%s</option>" % (esc(k), esc(k)) for k in sorted(decades, reverse=True))

    index = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>驾鹤集 · 1976 年以来逝世名人</title>
<link rel="stylesheet" href="style.css"></head><body>
<header><div class="wrap">
<h1>驾鹤集<small>1976 年以来，那些与我们同行过的人</small></h1>
<p class="sub">数据源：本地中文维基百科全文索引（__CHARS__ 万字正文快照）· 每一条死因与日期均可溯源到原文</p>
</div></header>
<nav><div class="wrap" style="display:flex;gap:22px">
<a href="index.html" class="on">名录</a><a href="calendar.html">日历</a><a href="timeline.html">年表</a><a href="stats.html">统计</a>
</div></nav>
<div class="wrap">
<div class="chips">__CHIPS__</div>
<div class="bar">
<input type="search" id="q" placeholder="搜索姓名 / 英文名 / 死因 / 身份标签…">
<select id="cat"><option value="">全部领域</option>__CATS__</select>
<select id="dec"><option value="">全部年代</option>__DECS__</select>
<button id="sort" style="padding:9px 15px;border:1px solid var(--line);border-radius:8px;background:var(--card);cursor:pointer;font-size:14px;font-family:inherit">年份 ↓</button>
</div>
<table id="tbl"><thead><tr>
<th>逝世年</th><th>姓名</th><th>生年</th><th>享年</th><th>死因</th><th>领域</th><th>地区</th>
</tr></thead><tbody id="rows">__ROWS__</tbody></table>
<div class="empty" id="empty" style="display:none">没有匹配的人物</div>
<noscript><div class="empty">当前查看器禁用了脚本：完整名录仍可阅读，可用 Cmd/Ctrl+F 检索。</div></noscript>
</div>
<footer>驾鹤集 · 本地维基索引驱动 · 共 __TOTAL__ 人 · 生成于 __TS__</footer>
<script>
const rows=[...document.querySelectorAll("#rows tr")];
const q=document.getElementById("q"),cat=document.getElementById("cat"),
      dec=document.getElementById("dec"),empty=document.getElementById("empty");
let dir=-1;
function apply(){
  const k=q.value.trim().toLowerCase(),c=cat.value,d=dec.value;
  let n=0;
  rows.forEach(tr=>{
    const t=tr.textContent.toLowerCase();
    const ok=(!k||t.includes(k))&&(!c||tr.children[5].textContent.trim()===c)
             &&(!d||tr.children[0].textContent.trim().slice(0,3)+"0"===d);
    tr.style.display=ok?"":"none"; if(ok)n++;
  });
  empty.style.display=n?"none":"block";
}
q.addEventListener("input",apply);cat.addEventListener("change",apply);dec.addEventListener("change",apply);
document.getElementById("sort").addEventListener("click",e=>{
  const tb=document.getElementById("rows");dir*=-1;
  const arr=rows.slice().sort((a,b)=>dir*a.children[0].textContent.localeCompare(b.children[0].textContent));
  arr.forEach(tr=>tb.appendChild(tr));
  e.target.textContent=dir<0?"年份 ↓":"年份 ↑";
});
document.querySelectorAll("#tbl th").forEach((th,i)=>{
  if(i===0||i===1)th.addEventListener("click",()=>document.getElementById("sort").click());
});
</script></body></html>"""
    index = (index.replace("__CHIPS__", chips).replace("__CATS__", cat_opts)
             .replace("__DECS__", dec_opts).replace("__ROWS__", "".join(rows))
             .replace("__CHARS__", str(stats["chars"] // 10000))
             .replace("__TOTAL__", str(total))
             .replace("__TS__", D.now().replace("T", " ")[:16]))
    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8") as f:
        f.write(index)

    # ── 详情页 ──
    for p in people:
        cc = p["cause_cat"] or "未知"
        a = age(p["born_date"] or "", p["died_date"] or "")
        taglist = []
        occ = {}
        try:
            occ = json.loads(p["occupation"] or "{}")
        except Exception:
            occ = {}
        if not isinstance(occ, dict):
            occ = {}
        for group, items in occ.items():
            for it in items[:3]:
                if len(it) <= 20 and it not in taglist:
                    taglist.append(it)
        taglist = taglist[:14]

        lead = clean(p["bio_short"] or "")
        paras = [x.strip() for x in lead.split("\n") if x.strip()][:4]
        one = re.split(r"[。\n]", paras[0])[0] if paras else ""

        ev_html = ""
        for s in p["sources"]:
            if s["field"] in ("cause", "died") and s["snippet"]:
                ev_html += "<div class='ev'><b>%s</b><br>「%s」<br><span style='color:#8a7f76;font-size:12.5px'>— %s（%s）</span></div>" % (
                    "死因证据" if s["field"] == "cause" else "逝世记述",
                    esc(clean(s["snippet"])[:220]), esc(s["kind"]), esc(s["ref"] or ""))

        death_sent = pick_death_sentence(p.get("zh_text") or "", p["name_zh"])
        if death_sent and death_sent not in ev_html:
            ev_html = "<div class='ev'><b>原文记述</b><br>「%s」<br><span style='color:#8a7f76;font-size:12.5px'>— 中文维基百科正文</span></div>" % esc(death_sent) + ev_html

        def kv(k, v):
            return "<tr><td>%s</td><td>%s</td></tr>" % (k, v)

        kvhtml = "".join([
            kv("出生", fmt_date(p["born_date"])),
            kv("逝世", fmt_date(p["died_date"])),
            kv("享年", ("%d 岁" % a) if a else "—"),
            kv("死因", "<span class='dot' style='background:%s'></span>%s" % (
                CAUSE_COLOR.get(cc, "#999"), esc(p["cause_raw"] or "—"))),
            kv("死因类型", esc(cc)),
            kv("领域", esc(p["cat"] or "—")),
            kv("地区", esc(p["region"] or "—")),
            kv("核实", {"verified": "✔ 维基正文含该逝世年份",
                       "partial": "◐ 部分核实", "seed_only": "○ 仅有手工记录"}.get(
                p["status"], p["status"])),
        ])

        tl_html = "".join("<li>%s</li>" % esc(clean(x)) for x in p["tl"]) or "<li>暂无</li>"
        src_html = "".join(
            "<li><a href='%s' target='_blank'>%s</a>　<span style='color:#8a7f76'>%s</span></li>"
            % (esc(s["ref"]), esc(s["kind"]), esc(s["field"]))
            for s in p["sources"] if s["ref"]) or "<li>暂无外部来源</li>"

        detail = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__NAME__ · 驾鹤集</title><link rel="stylesheet" href="../style.css"></head><body>
<div class="detail">
<a class="back" href="../index.html">← 返回名录</a>
<h1>__NAME__</h1>
<div class="en">__EN____REGION__</div>
__QUOTE__
<h2>基本信息</h2><table class="kv">__KV__</table>
<h2>生平</h2><div class="paras">__PARAS__</div>
<h2>逝世与死因</h2>__EV__
<h2>主要成就与事迹</h2><ul class="plain">__TL__</ul>
__TAGS__
<h2>来源</h2><ul class="plain">__SRC__</ul>
<p class="footnote">本页内容取自本地中文维基百科全文索引快照，正文与证据句均为原文摘录；生卒与死因为项目方核校值。考证时间：__TS__</p>
</div></body></html>"""
        detail = (detail
                  .replace("__NAME__", esc(p["name_zh"]))
                  .replace("__EN__", esc(p["name_en"] or ""))
                  .replace("__REGION__", ("　" + esc(p["region"] or "")) if p["region"] else "")
                  .replace("__QUOTE__", ("<div class='quote'>%s。</div>" % esc(one)) if one else "")
                  .replace("__KV__", kvhtml)
                  .replace("__PARAS__", "".join("<p>%s</p>" % esc(x) for x in paras) or "<p>—</p>")
                  .replace("__EV__", ev_html or "<p>暂无原文证据</p>")
                  .replace("__TL__", tl_html)
                  .replace("__TAGS__", ("<h2>身份标签</h2><p>%s</p>" % "　".join(
                      "<span class='tag'>%s</span>" % esc(t) for t in taglist)) if taglist else "")
                  .replace("__SRC__", src_html)
                  .replace("__TS__", D.now().replace("T", " ")[:16]))
        with open(os.path.join(SITE, "p", p["key"] + ".html"), "w", encoding="utf-8") as f:
            f.write(detail)

    # ── 年表 ──
    by_year = defaultdict(list)
    for p in people:
        if p["died_date"]:
            by_year[p["died_date"][:4]].append(p)
    yhtml = []
    for y in sorted(by_year, reverse=True):
        items = "".join(
            "<span><a href='p/%s.html'>%s</a><span style='color:#8a7f76;font-size:12.5px'>%s</span></span>"
            % (esc(p["key"]), esc(p["name_zh"]), esc((p["died_date"] or "")[5:])) for
            p in sorted(by_year[y], key=lambda x: x["died_date"] or ""))
        yhtml.append("<div class='year'><div class='y'>%s</div><div class='items'>%s</div></div>"
                     % (y, items))
    timeline = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>年表 · 驾鹤集</title><link rel="stylesheet" href="style.css"></head><body>
<header><div class="wrap"><h1>年表<small>按逝世年份排列</small></h1>
<p class="sub">共 %d 年有记录</p></div></header>
%s<div class="wrap" style="padding-top:20px">%s</div>
<footer>驾鹤集 · 生成于 %s</footer></body></html>""" % (
        len(by_year), nav_html("", "timeline"), "".join(yhtml),
        D.now().replace("T", " ")[:16])
    with open(os.path.join(SITE, "timeline.html"), "w", encoding="utf-8") as f:
        f.write(timeline)

    # ── 统计页 ──
    def hbars(counter, total_n, colorfn=None, limit=None):
        items = counter.most_common(limit) if limit else counter.most_common()
        mx = max(v for _, v in items) if items else 1
        out = []
        for k, v in items:
            w = max(2, int(v / mx * 100))
            c = colorfn(k) if colorfn else "#9c2c1f"
            out.append(
                "<div class='hbar'><div class='lbl'>%s</div><div class='trk'>"
                "<div class='fil' style='width:%d%%;background:%s'></div></div>"
                "<div class='num'>%d</div></div>" % (esc(k), w, c, v))
        return "".join(out)

    statshtml = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>统计 · 驾鹤集</title><link rel="stylesheet" href="style.css"></head><body>
<header><div class="wrap"><h1>统计<small>结构观察</small></h1>
<p class="sub">共 %d 人 · 正文 %d 万字</p></div></header>
%s
<div class="wrap"><div class="grid">
<div class="panel"><h3>逝世年代分布</h3>%s</div>
<div class="panel"><h3>死因构成</h3>%s</div>
<div class="panel"><h3>领域分布</h3>%s</div>
<div class="panel"><h3>地区分布（前 12）</h3>%s</div>
</div></div>
<footer>驾鹤集 · 生成于 %s</footer></body></html>""" % (
        total, stats["chars"] // 10000, nav_html("", "stats"),
        hbars(Counter({k: v for k, v in sorted(decades.items())}), total, lambda k: "#9c2c1f"),
        hbars(causes, total, lambda k: CAUSE_COLOR.get(k, "#9ca3af")),
        hbars(cats, total, lambda k: "#b8860b"),
        hbars(regions, total, lambda k: "#0d9488", 12),
        D.now().replace("T", " ")[:16])
    with open(os.path.join(SITE, "stats.html"), "w", encoding="utf-8") as f:
        f.write(statshtml)

    # ── 日历视图 ──
    n_year, n_cal = CAL.build(people, SITE, nav_html)
    stats["cal_years"] = n_year
    stats["cal_people"] = n_cal

    # ── 陈旧详情页：被剔除/改名的人，移到 out/_stale/（不删，可回滚）──
    live = {p["key"] + ".html" for p in people}
    pdir = os.path.join(SITE, "p")
    stale = sorted(f for f in os.listdir(pdir) if f.endswith(".html") and f not in live)
    if stale:
        dest = os.path.join(ROOT, "out", "_stale", time.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(dest, exist_ok=True)
        for f in stale:
            shutil.move(os.path.join(pdir, f), os.path.join(dest, f))
        stats["stale_moved"] = len(stale)
        stats["stale_dir"] = dest

    return stats


if __name__ == "__main__":
    people = load_all()
    st = build(people)
    print("site built:", SITE)
    print("people:", st["total"], "| 正文:", st["chars"], "字")
    print("页数:", len(os.listdir(os.path.join(SITE, "p"))))
