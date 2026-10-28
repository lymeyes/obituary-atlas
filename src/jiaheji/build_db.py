#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""驾鹤集 · 数据入库

三阶段：
  Stage A (main)        : 全量元数据入库
                         - tpl_people.jsonl (49,042 人, 来自 dump 生卒模板) → wiki_only + tier
                         - seed385.json (386 人, 手工核校) → 权威覆盖 born/died/cause/cat/region/bio
                         - excluded.txt → 打 excluded 标记 (不删数据)
  Stage B (merge_full)  : NUC 取回的正文(full_49k.jsonl) 补全 text/raw/cause/achievements/bio/cat
  Stage C (render_*)    : 渲染站点 + 笔记 (见 render_site.py / render_notes.py)
"""
import json, os, re, sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))          # .../src/jiaheji
ROOT = os.path.dirname(os.path.dirname(HERE))              # 项目根
sys.path.insert(0, HERE)
import db as D
import excl as X

DATA = os.path.join(ROOT, "data")
SEED = os.path.join(DATA, "seed385.json")
TPL = os.path.join(DATA, "tpl_people.jsonl")
FULL = os.path.join(DATA, "full_49k.jsonl")               # NUC 取回的正文


def slug(name: str) -> str:
    s = name.replace("/", "／").replace(":", "：").replace("\\", "＼")
    s = re.sub(r'[<>"|?*]', "", s)
    return s.strip() or "未命名"


def ymd(y, m, d):
    """生卒日期容错：年必有，月/日缺失则降级"""
    if not y:
        return None
    try:
        y = int(y)
    except (TypeError, ValueError):
        return None
    if m and d:
        try:
            return "%04d-%02d-%02d" % (y, int(m), int(d))
        except (TypeError, ValueError):
            pass
    if m:
        try:
            return "%04d-%02d" % (y, int(m))
        except (TypeError, ValueError):
            pass
    return str(y)


def classify_cause(text: str) -> str:
    if not text:
        return "未知"
    t = text
    if re.search(r"自杀|自縊|自缢|轻生|輕生|跳楼|跳樓|烧炭|燒炭|自尽|自盡|割腕|服药|服藥", t):
        return "自杀"
    if re.search(r"遇刺|被刺|暗杀|暗殺|枪杀|槍殺|谋殺|谋杀|被害|遇害|处决|處決", t):
        return "遇害"
    if re.search(r"车祸|車禍|空难|空難|坠机|墜機|溺水|火灾|火災|事故|意外|地震|海难|爆炸", t):
        return "事故"
    if re.search(r"癌|肿瘤|腫瘤|白血病|淋巴|肉瘤", t):
        return "癌症"
    if re.search(r"心|脑|腦|梗|溢血|溢血|中风|中風|衰竭", t):
        return "心脑血管"
    if re.search(r"感染|肺炎|肺|呼吸|结核|結核|疫|病毒|艾滋|愛滋", t):
        return "呼吸/感染"
    if re.search(r"病|疾病|并发症|併發症|糖尿病|肝|肾|腎|器管|器官", t):
        return "疾病"
    if re.search(r"老|高龄|高齡|寿终|壽終|自然", t):
        return "自然衰老"
    return "其他"


VAGUE_CAUSE = re.compile(
    r"^(病逝|逝世|去世|病故|自然死亡|因病|因病去世|因病逝世|不详|未知|老死|病亡|离世)")


def main():
    D.init()
    seed = {p["name"]: p for p in json.load(open(SEED, encoding="utf-8"))}
    tpl = [json.loads(l) for l in open(TPL, encoding="utf-8")] if os.path.exists(TPL) else []

    report = {"tpl_total": len(tpl), "seed_total": len(seed),
              "meta_ok": 0, "seed_ok": 0, "excluded": 0, "excl_unmatched": []}

    with D.connect() as con:
        # ── Stage A.1 : 全量 tpl 元数据 ──
        for r in tpl:
            name = r.get("t")
            if not name:
                continue
            dy = r.get("dy")
            if not dy or not (1976 <= int(dy) <= 2025):
                continue
            n = r.get("n") or 0
            tier = 1 if n >= 12000 else (2 if n >= 4000 else 3)
            born = ymd(r.get("by"), r.get("bm"), r.get("bd"))
            died = ymd(r.get("dy"), r.get("dm"), r.get("dd"))
            D.upsert_person(con, {
                "key": slug(name),
                "name_zh": name,
                "born_date": born,
                "died_date": died,
                "cause_raw": "未详",
                "cause_cat": "未知",
                "cat": None,
                "region": None,
                "status": "wiki_only",
                "tier": tier,
                "wiki_zh_title": name,
                "wiki_zh_url": "https://zh.wikipedia.org/wiki/" + name.replace(" ", "_"),
                "notes": "tpl:n=%d" % n,
            })
            report["meta_ok"] += 1

        # ── Stage A.2 : seed 权威覆盖 ──
        for name, s in seed.items():
            key = slug(name)
            D.upsert_person(con, {
                "key": key,
                "name_zh": name,
                "name_en": (s.get("en") or "").strip() or None,
                "born_date": s.get("born") or None,
                "died_date": s.get("died") or None,
                "cause_raw": s.get("cause") or None,
                "cause_cat": classify_cause(s.get("cause") or ""),
                "cat": s.get("cat") or None,
                "region": s.get("region") or None,
                "bio_short": (s.get("bio") or "")[:600] or None,
                "wiki_zh_url": s.get("wiki") or None,
                "status": "verified",
                "tier": 1,
            })
            if s.get("wiki"):
                pid = con.execute("SELECT id FROM person WHERE key=?", (key,)).fetchone()
                if pid:
                    D.add_source(con, pid["id"], "bio", "seed", s["wiki"],
                                 (s.get("bio") or "")[:300])
            report["seed_ok"] += 1

        # ── Stage A.3 : 排除名单 (只打标, 不删) ──
        n_ex, miss = X.apply(con)
        report["excluded"] = n_ex
        report["excl_unmatched"] = miss

        D.meta_set(con, "last_build", D.now())
        D.meta_set(con, "source", "zhwiki@NUC/jiaheji-data/zhwiki.db + tpl_people.jsonl")

    report["stats"] = D.stats()
    json.dump(report, open(os.path.join(DATA, "build_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in report.items() if k != "stats"}, ensure_ascii=False, indent=1))


def merge_full():
    """Stage B : 把 NUC 取回的正文补全进 DB (text/raw/cause/achievements/bio/cat)"""
    if not os.path.exists(FULL):
        print("[merge] 未找到 %s, 跳过" % FULL)
        return
    rows = [json.loads(l) for l in open(FULL, encoding="utf-8")]
    with D.connect() as con:
        n = 0
        for r in rows:
            title = r.get("title") or r.get("t")
            if not title:
                continue
            key = slug(title)
            pid = con.execute("SELECT id FROM person WHERE key=?", (key,)).fetchone()
            if not pid:
                continue
            pid = pid["id"]
            text = r.get("text") or ""
            cats = r.get("cats") or []
            D.set_raw(con, pid, title, " ".join(cats), text)
            # 死因: 优先 NUC 已抽, 否则留待 render 时再抽
            cause = r.get("cause")
            if cause and not VAGUE_CAUSE.match(cause):
                con.execute("UPDATE person SET cause_raw=?, cause_cat=? WHERE id=?",
                            (cause, classify_cause(cause), pid))
            # 成就/分类
            for a in (r.get("achievements") or [])[:6]:
                con.execute("INSERT INTO timeline (person_id, year, event) VALUES (?,?,?)",
                            (pid, None, a))
            if cats:
                occ = json.loads(con.execute("SELECT occupation FROM person WHERE id=?", (pid,)).fetchone()["occupation"] or "{}")
                occ["wiki分类"] = cats[:8]
                con.execute("UPDATE person SET occupation=?, cat=? WHERE id=?",
                            (json.dumps(occ, ensure_ascii=False), (cats[0] if cats else None), pid))
            if r.get("bio_short"):
                con.execute("UPDATE person SET bio_short=? WHERE id=? AND (bio_short IS NULL OR bio_short='')",
                            (r["bio_short"][:600], pid))
            con.execute("UPDATE person SET status='partial' WHERE id=? AND status='wiki_only'", (pid,))
            n += 1
        D.meta_set(con, "last_merge", D.now())
    print("[merge] 补全正文 %d 人" % n)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "merge":
        merge_full()
    else:
        main()
