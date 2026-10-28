#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""驾鹤集 · 渲染 Obsidian 笔记（深度版）

每人一份 md：基本信息表 + 生平摘要 + 主要成就 + 逝世与死因（含原文证据）+ 身份标签 + 来源
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import db as D

OUT = os.path.join(ROOT, "out", "notes")

CAUSE_EMOJI = {"自杀": "🕯️", "遇害": "🗡️", "事故": "⚠️", "癌症": "🎗️",
               "心脑血管": "❤️", "呼吸/感染": "🫁", "疾病": "🏥",
               "自然衰老": "🍂", "其他": "•", "未知": "？"}


def fmt_date(d):
    if not d:
        return "—"
    p = d.split("-")
    if len(p) >= 3:
        return "%s年%s月%s日" % (p[0], int(p[1]), int(p[2]))
    if len(p) == 2:
        return "%s年%s月" % (p[0], int(p[1]))
    return "%s年" % d


def clean(s):
    if not s:
        return ""
    s = re.sub(r"（\s*[，,]\s*）", "", s)
    s = re.sub(r"（\s*）", "", s)
    return s.strip()


def pick_paras(lead, n=3, maxc=700):
    """取前 n 段，总长不超过 maxc"""
    if not lead:
        return ""
    out, total = [], 0
    for p in [x.strip() for x in lead.split("\n") if x.strip()]:
        if total + len(p) > maxc and out:
            break
        out.append(p)
        total += len(p)
    return "\n\n".join(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    D.init()
    n = 0
    with D.connect() as con:
        rows = con.execute("""
            SELECT p.*, r.zh_text, r.zh_cats, r.zh_title
            FROM person p LEFT JOIN raw r ON r.person_id = p.id
            WHERE COALESCE(p.excluded,0)=0
            ORDER BY p.died_date
        """).fetchall()
        for r in rows:
            key = r["key"]
            name = r["name_zh"]
            cats = (r["zh_cats"] or "").split()
            occ = {}
            try:
                occ = json.loads(r["occupation"] or "{}")
            except Exception:
                occ = {}
            if not isinstance(occ, dict):
                occ = {}
            # 身份标签：从分类里挑人物属性类（去重、限长）
            tags = []
            for c in cats:
                if len(c) <= 18 and c not in tags and any(k in c for k in (
                        "歌手", "演員", "演员", "作家", "詩人", "诗人", "導演", "导演",
                        "政治", "主席", "總統", "总统", "科學家", "科学家", "院士",
                        "企業家", "企业家", "運動員", "运动员", "畫家", "画家",
                        "教授", "主持人", "作家", "小說家", "小说家")):
                    tags.append(c)
                if len(tags) >= 8:
                    break

            srcs = con.execute(
                "SELECT field, kind, ref, snippet FROM source WHERE person_id=? ORDER BY id",
                (r["id"],)).fetchall()
            cause_src = [s for s in srcs if s["field"] == "cause"]
            died_src = [s for s in srcs if s["field"] == "died"]

            tls = con.execute(
                "SELECT event FROM timeline WHERE person_id=? LIMIT 8", (r["id"],)).fetchall()

            cc = r["cause_cat"] or "未知"
            emoji = CAUSE_EMOJI.get(cc, "•")
            status_txt = {"verified": "✔ 已核（维基正文含该逝世年份）",
                          "partial": "◐ 部分核实",
                          "seed_only": "○ 仅手工数据（维基未匹配）",
                          "pending": "· 待核"}.get(r["status"], r["status"])

            fm = [
                "---",
                "title: %s" % name,
                "aliases: [%s]" % (r["name_en"] or ""),
                "born: %s" % (r["born_date"] or ""),
                "died: %s" % (r["died_date"] or ""),
                "cause: %s" % (r["cause_raw"] or ""),
                "cause_cat: %s" % cc,
                "category: %s" % (r["cat"] or ""),
                "region: %s" % (r["region"] or ""),
                "status: %s" % r["status"],
                "wiki: %s" % (r["wiki_zh_url"] or ""),
                "tags: [驾鹤集, %s, %s]" % (r["cat"] or "其他", cc),
                "---",
                "",
            ]

            body = ["# %s" % name, ""]
            if r["name_en"]:
                body.append("*%s*　" % r["name_en"] + (r["region"] or ""))
                body.append("")

            lead = clean(r["bio_short"] or "")
            first = re.split(r"[。\n]", lead)[0] if lead else ""
            if first:
                body += ["> " + first.strip("。") + "。", ""]

            body += [
                "## 基本信息", "",
                "| 项目 | 内容 |",
                "| --- | --- |",
                "| 出生 | %s |" % fmt_date(r["born_date"]),
                "| 逝世 | %s |" % fmt_date(r["died_date"]),
                "| 享年 | %s |" % (
                    "%d 岁" % D_age(r["born_date"], r["died_date"])
                    if D_age(r["born_date"], r["died_date"]) else "—"),
                "| 死因 | %s %s |" % (emoji, r["cause_raw"] or "—"),
                "| 死因类型 | %s |" % cc,
                "| 领域 | %s |" % (r["cat"] or "—"),
                "| 地区 | %s |" % (r["region"] or "—"),
                "| 核实状态 | %s |" % status_txt,
                "",
            ]

            paras = pick_paras(lead)
            if paras:
                body += ["## 生平", "", paras, ""]

            if tls:
                body += ["## 主要成就与事迹", ""]
                for t in tls:
                    body.append("- " + clean(t["event"]))
                body.append("")

            # 逝世与死因（带原文证据）
            body += ["## 逝世与死因", ""]
            body.append("- **死因**：%s" % (r["cause_raw"] or "—"))
            if cause_src:
                for s in cause_src[:2]:
                    if s["snippet"]:
                        body.append("- **原文证据**：「%s」" % clean(s["snippet"])[:200])
            if died_src:
                for s in died_src[:1]:
                    if s["snippet"]:
                        body.append("- **逝世记述**：「%s」" % clean(s["snippet"])[:200])
            if r["notes"]:
                body.append("- **核校备注**：%s" % r["notes"])
            body.append("")

            if tags:
                body += ["## 身份标签", "",
                         "　".join("`%s`" % t for t in tags), ""]

            body += ["## 来源", ""]
            seen = set()
            for s in srcs:
                if s["ref"] and s["ref"] not in seen:
                    seen.add(s["ref"])
                    body.append("- [%s](%s)（%s）" % (s["kind"], s["ref"], s["field"]))
            if not seen:
                body.append("- 暂无外部来源（仅手工数据）")
            body.append("")

            path = os.path.join(OUT, key + ".md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(fm) + "\n".join(body))
            n += 1
    print("written:", n)


def D_age(b, d):
    try:
        y1, m1, dd1 = [int(x) for x in b.split("-")[:3]]
        y2, m2, dd2 = [int(x) for x in d.split("-")[:3]]
        a = y2 - y1
        if (m2, dd2) < (m1, dd1):
            a -= 1
        return a
    except Exception:
        return None


if __name__ == "__main__":
    main()
