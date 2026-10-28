#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""驾鹤集 · 扩量：从 dump 扫描结果构建候选人物池

输入 deaths_all.jsonl（标题/逝世年/出生年）
处理：FTS 精确取正文与分类 → 推断领域/地区/死因 → 分层 → 排除已有
输出 expand_candidates.json
"""
import sqlite3, json, re, sys, time

DB = "/home/liuyimin/jiaheji-data/zhwiki.db"
SCAN = "/home/liuyimin/jiaheji-data/deaths_all.jsonl"
EXIST = "/tmp/seed385.json"
OUT = "/tmp/expand_candidates.json"
YMIN, YMAX = 1976, 2025

con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
con.execute("PRAGMA query_only=1")

# 非人物条目过滤
SKIP_TITLE = re.compile(r"(列表|列表$|年表|时间线|时间轴|大事记|逝世名单|死者名单|"
                        r"^分类:|^Category:|^模板:|^Wikipedia:|^维基百科:)")
PERSON_CAT = ["人物", "男演員", "女演員", "歌手", "作家", "政治", "科學家", "运动员",
              "運動員", "教授", "院士", "企業家", "企業家", "畫家", "導演", "导演",
              "主持人", "詩人", "诗人", "小說家", "小说家", "得主", "獲獎", "校友",
              "出生", "逝世", "去世", "演員", "演员", "音樂", "音乐", "運動", "运动"]

CAT_MAP = [
    ("政治家", ["政治人物", "政治", "主席", "總統", "总统", "总理", "總理", "部長", "部长",
              "革命家", "革命", "外交", "省委", "人大", "政協", "政协", "軍事", "军事"]),
    ("演艺", ["演員", "演员", "歌手", "藝人", "艺人", "導演", "导演", "編劇", "编剧",
            "主持人", "音樂", "音乐", "主播", "舞蹈", "相聲", "相声"]),
    ("文学", ["作家", "小說家", "小说家", "詩人", "诗人", "散文", "翻譯家", "翻译家",
            "劇作家", "剧作家", "報人", "报人", "詞人", "词人"]),
    ("学者", ["科學家", "科学家", "物理學", "物理学", "數學", "数学", "教授", "學者", "学者",
            "研究員", "院士", "化學", "化学", "醫學家", "医学家", "經濟學", "经济学",
            "歷史學", "历史学", "哲學", "哲学", "工程師", "工程师", "教育家"]),
    ("体育", ["運動員", "运动员", "球員", "球员", "教練", "教练", "奧運", "奥运", "選手", "选手"]),
    ("企业家", ["企業家", "企业家", "商人", "實業家", "实业家", "富豪", "銀行家", "银行家"]),
    ("艺术", ["畫家", "画家", "書法", "书法", "雕塑", "藝術家", "艺术家", "攝影", "摄影",
            "建築師", "建筑师", "設計師", "设计师", "戲曲", "戏曲", "琴"]),
    ("媒体", ["記者", "记者", "新聞", "新闻", "編輯", "编辑", "評論員", "评论员", "主播"]),
    ("宗教", ["僧人", "和尚", "道士", "活佛", "牧師", "牧师", "神父", "主教", "宗教"]),
]
REGION_MAP = [
    ("🇭🇰", ["香港"]), ("🇨🇳(台湾)", ["台灣", "台湾", "中華民國"]),
    ("🇨🇳(澳门)", ["澳門", "澳门"]), ("🇨🇳", ["中華人民共和國", "中国", "中國", "大陸"]),
    ("🇺🇸", ["美國", "美国"]), ("🇬🇧", ["英國", "英国"]), ("🇯🇵", ["日本"]),
    ("🇫🇷", ["法國", "法国"]), ("🇩🇪", ["德國", "德国"]), ("🇷🇺", ["蘇聯", "苏联", "俄羅斯", "俄罗斯"]),
    ("🇰🇷", ["韓國", "韩国", "大韓"]), ("🇸🇬", ["新加坡"]), ("🇮🇳", ["印度"]),
    ("🇮🇹", ["義大利", "意大利"]), ("🇨🇦", ["加拿大"]), ("🇦🇺", ["澳大利亞", "澳大利亚"]),
]



DEATH_W = ("逝世", "去世", "病逝", "辞世", "过世", "离世", "与世长辞", "谢世",
           "病故", "身亡", "遇刺", "遇难", "罹难", "不治", "猝逝", "殁")
FUNERAL = ("葬礼", "葬禮", "追悼", "追思", "遗体", "遺體", "告别", "告別", "公祭",
           "安葬", "下葬", "纪念", "紀念", "忌辰", "周年", "誕辰", "诞辰", "灵堂", "靈堂")
DATE_RE = re.compile(r"((?:1[89]|20)\d{2})\s*年\s*(?:(\d{1,2})\s*月\s*)?(?:(\d{1,2})\s*日)?")
BIRTH_CTX = ("出生", "生于", "生於", "诞生", "誕生")


def sentences(text):
    return [x for x in re.split(r"(?<=[。；\n])", text) if x.strip()]


def pick_date(text, year, mode):
    """mode='death' 找含死亡词的句子；'birth' 找含出生词的句子"""
    sents = sentences(text)
    best = None
    for i, s in enumerate(sents):
        if any(f in s for f in FUNERAL):
            continue
        ctx = any(w in s for w in (DEATH_W if mode == "death" else BIRTH_CTX))
        if not ctx:
            continue
        for j in (i, i - 1, i + 1):
            if j < 0 or j >= len(sents) or (j != i and any(f in sents[j] for f in FUNERAL)):
                continue
            for mo in DATE_RE.finditer(sents[j]):
                y = int(mo.group(1))
                if year and y != year:
                    continue
                m = int(mo.group(2)) if mo.group(2) else None
                d = int(mo.group(3)) if mo.group(3) else None
                cand = (0 if m and d else 1, j - i if j >= i else i - j, -(m or 0), -(d or 0))
                if best is None or cand < best[0]:
                    best = (cand, (y, m, d), re.sub(r"\s+", " ", s)[:140])
    return best[1] if best else None


def pick_cause(text):
    for rx in (re.compile(r"(?:因|由于|罹患|患)([^，。；\n]{2,26}?)(?:而|终因)?"
                          r"(?:病逝|去世|逝世|辞世|过世|离世|不治|身亡|病故|与世长辞)"),
               re.compile(r"(?:死于|丧生于)([^，。；\n]{2,22})")):
        for mo in rx.finditer(text):
            v = re.sub(r"\s+", "", mo.group(1)).strip(" ，,、而")
            v = re.sub(r"(于|在)[^，。；]{2,10}$", "", v).strip(" ，,、而")
            if 2 <= len(v) <= 22 and not re.search(r"\d{3,}", v) and not re.search(r"无效|医治", v):
                return v
    return None


def tok(n):
    return " ".join(list(n))


def fts_exact(title):
    rows = con.execute(
        "SELECT rowid,title,length(text) FROM docs WHERE docs MATCH ? LIMIT 3",
        ('title_tok:"%s"' % tok(title),)).fetchall()
    for r in rows:
        if r[1] == title:
            return r
    return None


def infer(cats, mapping):
    for label, kws in mapping:
        if any(any(k in c for k in kws) for c in cats):
            return label
    return None


def main():
    exist = set(p["name"] for p in json.load(open(EXIST, encoding="utf-8")))
    try:
        ovr = json.load(open("/tmp/title_overrides.json", encoding="utf-8"))
        exist |= set(v for k, v in ovr.items() if not k.startswith("_"))
    except Exception:
        pass
    cands = []
    seen = set()
    n_in = 0
    for line in open(SCAN, encoding="utf-8"):
        try:
            o = json.loads(line)
        except Exception:
            continue
        n_in += 1
        t, dy = o.get("t"), o.get("dy")
        if not t or not dy or not (YMIN <= dy <= YMAX):
            continue
        if t in exist or t in seen:
            continue
        if SKIP_TITLE.search(t):
            continue
        seen.add(t)
        cands.append(o)
    print("扫描总数 %d，区间内候选 %d" % (n_in, len(cands)), file=sys.stderr)

    out = []
    t0 = time.time()
    for i, o in enumerate(cands):
        t = o["t"]
        hit = fts_exact(t)
        if not hit:
            continue
        r = con.execute("SELECT text,categories FROM docs WHERE rowid=?", (hit[0],)).fetchone()
        if not r or not r[0]:
            continue
        text, cats_raw = r[0], (r[1] or "")
        cats = cats_raw.split()
        if not any(any(h in c for h in PERSON_CAT) for c in cats):
            continue
        cat = infer(cats, CAT_MAP)
        region = infer(cats, REGION_MAP)
        dd = pick_date(text, o["dy"], "death")
        bd = pick_date(text, o.get("by"), "birth")
        out.append({
            "title": t, "died_year": o["dy"], "born_year": o.get("by"),
            "died_date": ("%04d-%02d-%02d" % (dd[0], dd[1], dd[2]))
                         if dd and dd[1] and dd[2] else ("%04d" % o["dy"]),
            "born_date": ("%04d-%02d-%02d" % (bd[0], bd[1], bd[2]))
                         if bd and bd[1] and bd[2] else (("%04d" % o["by"]) if o.get("by") else None),
            "cause": pick_cause(text),
            "chars": len(text), "cat": cat or "其他", "region": region or "",
            "cats": cats[:40],
            "honor": [c for c in cats if any(k in c for k in (
                "諾貝爾", "诺贝尔", "奧斯卡", "奥斯卡", "金馬", "金马", "金像",
                "院士", "勳章", "勋章", "獎", "奖", "得主", "冠軍", "冠军"))][:8],
        })
        if i % 2000 == 0:
            print("  处理 %d/%d 命中 %d %.0fs" % (i, len(cands), len(out), time.time() - t0),
                  file=sys.stderr, flush=True)

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    from collections import Counter
    print(json.dumps({
        "candidates": len(cands), "persons": len(out),
        "by_year": dict(sorted(Counter(o["died_year"] for o in out).items())),
        "by_cat": dict(Counter(o["cat"] for o in out).most_common()),
        "sec": round(time.time() - t0, 1),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
