#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""驾鹤集 · 正文级人物逝世抽取（替代失效的分类扫描）

为什么重写：
    中文维基绝大多数人物条目的「YYYY年逝世」分类由 {{bd}} 之类的模板自动生成，
    wikitext 里**没有** [[Category:YYYY年逝世]] 字面串。按分类字面扫描的召回接近零
    （实测姚贝娜/周恩来/张国荣/袁隆平全部漏掉）。因此改为**读正文**抽取逝世日期。

策略：
    1. FTS 索引筛出正文含死亡词的条目（约 7.2 万，读正文量约 350MB，可接受）
    2. 只在前 1800 字（导语+首段）里找逝世叙述——这是精度最高的区域
    3. 句级配对：死亡词与日期必须在同句或相邻句；含葬礼/追悼/周年等词的句子排除
    4. 年份限定 1976–2025；标题过滤列表/分类/模板等非人物条目
    5. 分类里的身份词判是否人物，并推断领域与地区

输出 candidates.jsonl（每行一个人），供 build_db.py 入库。
"""
import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter

DB = "/home/liuyimin/jiaheji-data/zhwiki.db"
YMIN, YMAX = 1976, 2025

DEATH = re.compile(r"(逝世|去世|過世|辞世|辭世|病逝|离世|離世|与世长辞|與世長辭|"
                   r"谢世|謝世|病故|身亡|遇害|遇刺|遇難|遇难|罹難|罹难|不治|猝逝|牺牲|犧牲)")
FUNERAL = re.compile(r"(葬礼|葬禮|追悼|追思|遗体|遺體|告别式|告別式|公祭|安葬|下葬|"
                     r"骨灰|灵堂|靈堂|忌辰|周年|诞辰|誕辰|纪念日|紀念日|纪念馆|紀念館|"
                     r"祭日|逝世周年|冥诞|冥誕)")
DATE = re.compile(r"((?:1[89]|20)\d{2})\s*年(?:\s*(\d{1,2})\s*月)?(?:\s*(\d{1,2})\s*日)?")
# 导语生卒区间：「张三（1898年3月5日—1976年1月8日）」
RANGE = re.compile(r"((?:1[89]|20)\d{2})\s*年(?:\s*(\d{1,2})\s*月)?(?:\s*(\d{1,2})\s*日)?"
                   r"\s*[—–\-－~～至]+\s*"
                   r"((?:1[89]|20)\d{2})\s*年(?:\s*(\d{1,2})\s*月)?(?:\s*(\d{1,2})\s*日)?")
SKIP_TITLE = re.compile(r"(列表|年表|时间线|時間線|时间轴|時間軸|大事记|大事記|"
                        r"^分类:|^分類:|^Category:|^模板:|^Template:|^Wikipedia:|^维基百科:|"
                        r"^Help:|^Portal:|^File:|^文件:|^主題:|^主题:|逝世人物|死者名单|死者名單)")

PERSON_CAT = ("人物", "演員", "演员", "歌手", "作家", "政治", "科學家", "科学家", "运动员",
              "運動員", "教練", "教练", "教授", "院士", "企業家", "企业家", "畫家", "画家",
              "導演", "导演", "主持人", "詩人", "诗人", "小說家", "小说家", "得主", "獲獎",
              "获奖", "校友", "出生", "逝世", "去世", "醫生", "医生", "工程師", "工程师",
              "軍人", "军人", "將領", "将领", "革命", "外交", "記者", "记者", "編輯", "编辑",
              "僧人", "牧師", "牧师", "主教", "活佛", "道士", "律師", "律师", "法官",
              "經濟學家", "经济学家", "哲學家", "哲学家", "歷史學家", "历史学家", "數學家",
              "数学家", "物理學家", "物理学家", "化學家", "化学家", "建築師", "建筑师",
              "作曲家", "音樂家", "音乐家", "舞蹈", "棋", "球員", "球员", "賽車", "赛车",
              "飛行員", "飞行员", "太空人", "宇航", "企業", "企业", "銀行家", "银行家",
              "皇室", "貴族", "贵族", "國王", "国王", "總統", "总统", "總理", "总理",
              "主席", "部長", "部长", "議員", "议员", "大使", "省委", "人大", "政協", "政协",
              "族", "氏", "姓")

CAT_MAP = [
    ("政治家", ["政治人物", "政治", "主席", "總統", "总统", "总理", "總理", "部長", "部长",
              "革命家", "革命", "外交", "省委", "人大", "政協", "政协", "軍事", "军事",
              "軍人", "军人", "將領", "将领", "議員", "议员", "大使", "國王", "国王",
              "總統", "总统", "皇室", "貴族", "贵族"]),
    ("演艺", ["演員", "演员", "歌手", "藝人", "艺人", "導演", "导演", "編劇", "编剧",
            "主持人", "音樂", "音乐", "主播", "舞蹈", "相聲", "相声", "作曲家", "演奏"]),
    ("文学", ["作家", "小說家", "小说家", "詩人", "诗人", "散文", "翻譯家", "翻译家",
            "劇作家", "剧作家", "報人", "报人", "詞人", "词人", "編輯", "编辑"]),
    ("学者", ["科學家", "科学家", "物理學", "物理学", "數學", "数学", "教授", "學者", "学者",
            "研究員", "院士", "化學", "化学", "醫學家", "医学家", "經濟學", "经济学",
            "歷史學", "历史学", "哲學", "哲学", "工程師", "工程师", "教育家", "醫生", "医生"]),
    ("体育", ["運動員", "运动员", "球員", "球员", "教練", "教练", "奧運", "奥运", "選手", "选手",
            "棋", "賽車", "赛车"]),
    ("企业家", ["企業家", "企业家", "商人", "實業家", "实业家", "富豪", "銀行家", "银行家"]),
    ("艺术", ["畫家", "画家", "書法", "书法", "雕塑", "藝術家", "艺术家", "攝影", "摄影",
            "建築師", "建筑师", "設計師", "设计师", "戲曲", "戏曲"]),
    ("媒体", ["記者", "记者", "新聞", "新闻", "評論員", "评论员", "主播"]),
    ("宗教", ["僧人", "和尚", "道士", "活佛", "牧師", "牧师", "神父", "主教", "宗教"]),
]
REGION_MAP = [
    ("中国香港", ["香港"]), ("中国台湾", ["台灣", "台湾", "中華民國"]),
    ("中国澳门", ["澳門", "澳门"]), ("中国大陆", ["中華人民共和國", "中国", "中國", "大陸"]),
    ("美国", ["美國", "美国"]), ("英国", ["英國", "英国"]), ("日本", ["日本"]),
    ("法国", ["法國", "法国"]), ("德国", ["德國", "德国"]), ("俄罗斯", ["蘇聯", "苏联", "俄羅斯", "俄罗斯"]),
    ("韩国", ["韓國", "韩国", "大韓"]), ("新加坡", ["新加坡"]), ("印度", ["印度"]),
    ("意大利", ["義大利", "意大利"]), ("加拿大", ["加拿大"]), ("澳大利亚", ["澳大利亞", "澳大利亚"]),
]


def sentences(text):
    return [x for x in re.split(r"(?<=[。；！？\n])", text) if x.strip()]


def pick_range(head):
    """导语首段的生卒区间。这是维基人物条目最稳的特征，且同时给出两个日期"""
    mo = RANGE.search(head[:600])
    if not mo:
        return None
    by, bm, bd, dy, dm, dd = (int(mo.group(1)),
                              int(mo.group(2)) if mo.group(2) else None,
                              int(mo.group(3)) if mo.group(3) else None,
                              int(mo.group(4)),
                              int(mo.group(5)) if mo.group(5) else None,
                              int(mo.group(6)) if mo.group(6) else None)
    if bm and not (1 <= bm <= 12):
        bm = None
    if dm and not (1 <= dm <= 12):
        dm = None
    return (by, bm, bd), (dy, dm, dd), re.sub(r"\s+", " ", mo.group(0))


def pick_death(head, name=""):
    """句级配对。要求句中含条目标题（或标题前两字），否则视为提及他人，丢弃。"""
    sents = sentences(head)[:36]
    key = name[:2] if len(name) >= 2 else name
    best = None
    for i, s in enumerate(sents):
        if not DEATH.search(s) or FUNERAL.search(s):
            continue
        if key and key not in s:
            continue                                   # 句中未提本人 → 大概率是他人
        for j in (i, i - 1, i + 1):
            if j < 0 or j >= len(sents):
                continue
            if j != i and (FUNERAL.search(sents[j]) or not DATE.search(sents[j])):
                continue
            death_pos = DEATH.search(sents[j])
            for mo in DATE.finditer(sents[j]):
                y = int(mo.group(1))
                if not (YMIN <= y <= YMAX):
                    continue
                m = int(mo.group(2)) if mo.group(2) else None
                d = int(mo.group(3)) if mo.group(3) else None
                if m and not (1 <= m <= 12):
                    m = None
                if d and not (1 <= d <= 31):
                    d = None
                # 距离死亡词越近越可信
                dist = abs(mo.start() - death_pos.start()) if death_pos else 999
                score = (0 if j == i else 1,             # 同句优先
                         0 if (m and d) else 1,          # 完整日期优先
                         dist, i)
                if best is None or score < best[0]:
                    best = (score, (y, m, d), re.sub(r"\s+", " ", s)[:150])
    return best[1] + (best[2],) if best else None


def pick_birth(text):
    """导语常见「1898年3月5日—1976年1月8日」或「（1898年3月5日－）」"""
    head = text[:600]
    mo = re.search(r"((?:1[89]|20)\d{2})\s*年(?:\s*(\d{1,2})\s*月)?(?:\s*(\d{1,2})\s*日)?"
                   r"\s*[—–\-－~～至]\s*(?:(?:1[89]|20)\d{2})", head)
    if mo:
        y = int(mo.group(1))
        m = int(mo.group(2)) if mo.group(2) else None
        d = int(mo.group(3)) if mo.group(3) else None
        if 1800 <= y <= 2025:
            return y, m, d
    for mo in re.finditer(r"(?:出生|生于|生於|誕生|诞生)[^。\n]{0,20}?((?:1[89]|20)\d{2})\s*年"
                          r"(?:\s*(\d{1,2})\s*月)?(?:\s*(\d{1,2})\s*日)?", head):
        y = int(mo.group(1))
        if 1800 <= y <= 2025:
            return y, (int(mo.group(2)) if mo.group(2) else None), (int(mo.group(3)) if mo.group(3) else None)
    return None


CAUSE_RX = [
    re.compile(r"(?:因|由于|由於|罹患|患)([^，。；、\n]{2,26}?)(?:而|终因|終因|医治无效|醫治無效)?"
               r"(?:病逝|去世|逝世|辞世|辭世|过世|過世|离世|離世|不治|身亡|病故|与世长辞|與世長辭)"),
    re.compile(r"(?:死于|死於|丧生於|喪生於|遇难于|遇難於)([^，。；、\n]{2,22})"),
    re.compile(r"([^，。；、\n]{2,20}?)(?:导致|導致|引致|造成)?(?:不治|抢救无效|搶救無效)"),
]


def pick_cause(head):
    for rx in CAUSE_RX:
        for mo in rx.finditer(head):
            v = re.sub(r"\s+", "", mo.group(1)).strip(" ，,、而的")
            v = re.sub(r"[（(].*$", "", v)
            if 2 <= len(v) <= 22 and not re.search(r"\d{3,}", v) \
                    and not re.search(r"无效|無效|医治|醫治|抢救|搶救|病重|病情", v):
                return v
    return None


def infer(cats, mapping):
    for label, kws in mapping:
        if any(any(k in c for k in kws) for c in cats):
            return label
    return None


def is_person(cats, text):
    if cats and any(any(h in c for h in PERSON_CAT) for c in cats):
        return True
    head = text[:120]
    return bool(re.search(r"(是|為|为)(一位|一名|中国|中國|美国|美國|日本|英国|英國)", head)) and \
        bool(pick_birth(text))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--out", default="/home/liuyimin/jiaheji-data/candidates.jsonl")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--progress", type=int, default=5000)
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % a.db, uri=True)
    con.execute("PRAGMA query_only=1")

    q = ('text_tok:"逝 世" OR text_tok:"去 世" OR text_tok:"病 逝" OR text_tok:"离 世" '
         'OR text_tok:"遇 害" OR text_tok:"遇 刺"')
    rows = con.execute("SELECT rowid, title, text, categories FROM docs WHERE docs MATCH ?", (q,))

    t0 = time.time()
    n = kept = 0
    stat = Counter()
    out = open(a.out, "w", encoding="utf-8")

    for rowid, title, text, cats_raw in rows:
        n += 1
        if a.limit and n > a.limit:
            break
        if n % a.progress == 0:
            print("  扫描 %d 保留 %d  %.0fs" % (n, kept, time.time() - t0),
                  file=sys.stderr, flush=True)
        if not title or not text:
            continue
        if SKIP_TITLE.search(title):
            stat["skip_title"] += 1
            continue
        cats = (cats_raw or "").split()
        head = text[:1800]
        rng = pick_range(text)
        if rng:
            (by, bm, bd), (y, m, dd), sent = rng
            if not (YMIN <= y <= YMAX):
                stat["out_of_range"] += 1
                continue
            born = (by, bm, bd)
            stat["by_range"] += 1
        else:
            d = pick_death(text[:4000], title)
            if not d:
                stat["no_date"] += 1
                continue
            y, m, dd, sent = d
            born = pick_birth(text)
            stat["by_sentence"] += 1
        if not is_person(cats, text):
            stat["not_person"] += 1
            continue
        b = born
        out.write(json.dumps({
            "title": title,
            "died_year": y,
            "died_date": "%04d-%02d-%02d" % (y, m or 0, dd or 0) if (m and dd) else "%04d" % y,
            "born_year": b[0] if b else None,
            "born_date": "%04d-%02d-%02d" % (b[0], b[1] or 0, b[2] or 0)
                          if (b and b[1] and b[2]) else (("%04d" % b[0]) if b else None),
            "cause": pick_cause(text[:3000]),
            "chars": len(text),
            "cat": infer(cats, CAT_MAP) or "其他",
            "region": infer(cats, REGION_MAP) or "",
            "cats": cats[:40],
            "honor": [c for c in cats if any(k in c for k in (
                "諾貝爾", "诺贝尔", "奧斯卡", "奥斯卡", "金馬", "金马", "金像",
                "院士", "勳章", "勋章", "獎", "奖", "得主", "冠軍", "冠军"))][:8],
            "sent": sent,
        }, ensure_ascii=False) + "\n")
        kept += 1

    out.close()
    print(json.dumps({
        "scanned": n, "kept": kept, "skip": dict(stat),
        "sec": round(time.time() - t0, 1),
    }, ensure_ascii=False), file=sys.stderr)
    print("→", a.out, file=sys.stderr)


if __name__ == "__main__":
    main()
