#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NUC 上运行：批量从 zhwiki FTS 取 1976-2025 人物正文 + 抽死因/摘要

用法：python3 fetch_full.py <tpl_people.jsonl> <out.jsonl>
- 对每个标题走 title_tok 短语 FTS，取 text + categories
- 死因抽取基于已知逝世年（来自生卒模板），在导语区配对死亡词+死因词，比自由文本配对可靠
- 输出 jsonl: {title, text, cats, cause, bio_short, dy}
"""
import json, sqlite3, re, sys

DB = "/home/liuyimin/jiaheji-data/zhwiki.db"

DEATH = re.compile(
    r"(逝世|去世|過世|辞世|辭世|病故|身故|殉职|殉國|殉国|遇害|遇难|罹难|被害|"
    r"自殺|自杀|亡故|溘然|瞑目|长眠|作古|谢世|與世長辭|与世长辞|心脏骤停|"
    r"心源性猝死|抢救无效|不治身亡|溘逝|逝去|离世|離世|卒|殁|歿|死)")
# 死因关键词（用于从死亡句里截取病因短语）
CAUSE_W = re.compile(
    r"(癌|肿瘤|腫瘤|白血病|淋巴瘤|肉瘤|心|脑|腦|梗|溢血|溢血|中风|中風|衰竭|"
    r"肺|肝|肾|腎|糖尿|感染|肺炎|结核|結核|病毒|艾滋|愛滋|车祸|車禍|空难|空難|"
    r"坠机|墜機|飞机|飛機|撞|溺|火灾|火災|烧|燒|炸|谋杀|謀殺|暗杀|暗殺|枪杀|槍殺|"
    r"刺|自杀|自殺|自缢|自縊|跳楼|跳樓|坠楼|墜樓|服毒|毒|老|高龄|高齡|寿终|壽終|"
    r"自然|病逝|病亡|病故|并发症|併發症|器官|抑郁|憂鬱|過勞|过劳|劳累|伤病|伤重|"
    r"伤势|疾病|症|综合征|綜合徵)")
CAUSE_STOP = re.compile(
    r"(无效|医治|抢救|病情恶化|病重|医院|家中|睡梦中|安详|平静|亲友|家属|公众|"
    r"享年|终年|岁|年|月|日|因|于|在)")


def tok(s: str) -> str:
    return " ".join(list(s))


def fts(con, title: str):
    q = 'title_tok:"%s"' % tok(title)
    for row in con.execute("SELECT title, text, categories FROM docs WHERE docs MATCH ?", (q,)):
        if row[0] == title:
            return row[1], row[2]
    r = con.execute(
        "SELECT title, text, categories FROM docs WHERE docs MATCH ? LIMIT 1", (q,)).fetchone()
    return (r[1], r[2]) if r else (None, None)


def pick_cause(text: str, dy):
    if not text:
        return None
    head = text[:1500]
    best = None
    for m in DEATH.finditer(head):
        s0 = max(0, m.start() - 60)
        s1 = min(len(head), m.end() + 40)
        seg = head[s0:s1]
        for cm in CAUSE_W.finditer(seg):
            c = seg[cm.start():cm.start() + 22]
            c = re.sub(r"[，。；、（）()\s].*$", "", c).strip(" ，。、的地了")
            if 2 <= len(c) <= 16 and not CAUSE_STOP.search(c):
                if best is None or len(c) < len(best):
                    best = c
    return best


def pick_bio(text: str):
    if not text:
        return None
    s = re.sub(r"\s+", " ", text[:200]).strip()
    return s[:180]


def main():
    tpl = sys.argv[1] if len(sys.argv) > 1 else "/tmp/tpl_people.jsonl"
    outp = sys.argv[2] if len(sys.argv) > 2 else "/home/liuyimin/jiaheji-data/full_49k.jsonl"
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [json.loads(l) for l in open(tpl, encoding="utf-8")]
    out = open(outp, "w", encoding="utf-8")
    n = 0
    miss = 0
    for r in rows:
        title = r.get("t")
        if not title:
            continue
        dy = r.get("dy")
        if not dy or not (1976 <= int(dy) <= 2025):
            continue
        text, cats = fts(con, title)
        if not text:
            miss += 1
            continue
        out.write(json.dumps({
            "title": title,
            "text": text,
            "cats": (cats or "").split(),
            "cause": pick_cause(text, dy),
            "bio_short": pick_bio(text),
            "dy": dy,
        }, ensure_ascii=False) + "\n")
        n += 1
        if n % 5000 == 0:
            sys.stderr.write("fetched %d / miss %d\n" % (n, miss))
    out.close()
    sys.stderr.write("DONE fetched=%d miss=%d\n" % (n, miss))


if __name__ == "__main__":
    main()
