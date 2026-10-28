#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""驾鹤集 · zhwiki 抽取器 v2

改进点（基于 v1 的 90 例未验证诊断）：
1. 句级配对：先切句，再在同句/邻句内配对日期与死亡词（解决「长距离」漏抽）
2. 词表扩充：与世长辞/谢世/病故/不治/猝逝/殁/卒 等
3. 消歧义页：识别「可以指：」类页面，从条列中按年份挑出正确子条目并重查
4. 三重校验：标题精确 / 逝世年份在文 / 分类含人物特征（避免普林斯顿大学这类误配）
"""
import sqlite3, json, re, time

DB = "/home/liuyimin/jiaheji-data/zhwiki.db"
SEED = "/tmp/seed385.json"
OUT = "/tmp/extracted2.json"

con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
con.execute("PRAGMA query_only=1")

DEATH_WORDS = ["逝世", "去世", "病逝", "辞世", "过世", "离世", "与世长辞", "长辞",
               "谢世", "病故", "故去", "殁", "卒", "身亡", "遇刺", "遇难", "罹难",
               "身亡", "自杀", "轻生", "不治", "牺牲", "死于", "丧生", "暴毙", "猝逝"]
DEATH_RE = re.compile("|".join(DEATH_WORDS))
DATE_RE = re.compile(r"((?:1[89]|20)\d{2})\s*年\s*(?:(\d{1,2})\s*月\s*)?(?:(\d{1,2})\s*日)?")
DAB_RE = re.compile(r"(可以指|可能指|是常见的.{0,8}人名|下列人物|以下人物)")
CAUSE_RE = [
    re.compile(r"(?:因|由于|罹患|患|死于|丧生于)([^，。；\n]{2,30}?)(?:而)?"
               r"(?:病逝|去世|逝世|辞世|过世|离世|不治|身亡|死亡|与世长辞|病故)"),
    re.compile(r"(?:因|由于)([^，。；\n]{2,30}?)(?:离世|辞世)"),
]

CAT_RULES = [
    ("死因:自杀", ["自殺", "自杀", "自缢", "輕生", "轻生", "跳樓", "跳楼", "燒炭", "烧炭"]),
    ("死因:遇害", ["遇刺", "被刺", "暗殺", "暗杀", "遇害", "被害", "谋杀", "謀殺", "槍殺", "枪杀"]),
    ("死因:事故", ["意外死亡", "交通事故", "車禍", "车祸", "空難", "空难", "溺水", "火災", "火灾", "墜"]),
    ("死因:疾病", ["疾病", "癌症", "癌", "病逝", "傳染病", "心臟", "心脏"]),
    ("荣誉:诺贝尔", ["諾貝爾", "诺贝尔"]),
    ("荣誉:奥斯卡", ["奧斯卡", "奥斯卡"]),
    ("荣誉:金马", ["金馬", "金马"]),
    ("荣誉:金像", ["金像"]),
    ("荣誉:院士", ["院士"]),
    ("荣誉:勋章", ["勳章", "勋章", "勛章"]),
    ("地域:香港", ["香港"]),
    ("地域:台湾", ["台灣", "台湾", "中華民國"]),
    ("地域:澳门", ["澳門", "澳门"]),
    ("职业:政治", ["政治", "主席", "總統", "总统", "总理", "總理", "部長", "部长",
                 "革命", "軍事", "军事", "外交", "省委"]),
    ("职业:演艺", ["演員", "演员", "歌手", "藝人", "艺人", "導演", "导演", "編劇", "编剧",
                 "音樂", "音乐", "主持人", "主播"]),
    ("职业:文学", ["作家", "小說家", "小说家", "詩人", "诗人", "散文", "翻譯家", "翻译家", "報人"]),
    ("职业:学术", ["科學家", "科学家", "物理學", "物理学", "數學", "数学", "教授",
                 "學者", "学者", "研究員", "院士", "化學", "化学", "醫學家", "医学家"]),
    ("职业:体育", ["運動員", "运动员", "球員", "球员", "教練", "教练", "奧運", "奥运"]),
    ("职业:商界", ["企業家", "企业家", "商人", "實業家", "实业家", "富豪", "銀行家"]),
    ("职业:艺术", ["畫家", "画家", "書法", "书法", "雕塑", "藝術家", "艺术家", "攝影", "摄影", "建築師"]),
]
FUNERAL = ["葬礼", "葬禮", "追悼", "追思", "遺體", "遗体", "告別", "告别", "公祭", "安葬",
            "下葬", "紀念", "纪念", "忌辰", "週年", "周年", "紀念館", "纪念馆", "銅像", "雕像",
            "誕辰", "诞辰", "冥誕", "墓", "靈堂", "灵堂", "出殯", "出殡", "扶靈"]

PERSON_HINT = ["人物", "男演員", "女演員", "歌手", "作家", "政治", "科學家", "运动员",
               "運動員", "逝世", "出生", "校友", "得主", "獲獎"]


def tok(n):
    return " ".join(list(n))


def variants(name):
    out = [name]
    for pat in (r"[·・\-\s]", r"[（(].*?[）)]"):
        s = re.sub(pat, "", name).strip()
        if s and s not in out:
            out.append(s)
    return out


def fts(query, limit=8):
    try:
        return con.execute(
            "SELECT rowid,title,length(text) FROM docs WHERE docs MATCH ? LIMIT ?",
            (query, limit)).fetchall()
    except Exception:
        return []


def fetch(rowid):
    r = con.execute("SELECT title,text,categories FROM docs WHERE rowid=?", (rowid,)).fetchone()
    return (r[0], r[1] or "", r[2] or "") if r else (None, "", "")


def is_dab(text):
    head = text[:400]
    return bool(DAB_RE.search(head)) and len(text) < 3000


def parse_dab(text, name, want_year):
    """消歧义页：找形如『张震 (1914年)（1914年10月5日—2015年9月3日）』的条目"""
    if not want_year:
        return None
    for line in re.split(r"\n|(?<=）)\s+", text):
        if name not in line:
            continue
        yrs = re.findall(r"(1[89]\d{2}|20\d{2})\s*年", line)
        if str(want_year) in yrs:
            m = re.search(re.escape(name) + r"\s*[（(]([^）)]{1,24})[）)]", line)
            sub = "%s (%s)" % (name, m.group(1)) if m else None
            return {"line": re.sub(r"\s+", " ", line)[:160], "sub_title": sub,
                    "years": yrs}
    return None


def split_sents(text):
    return [s for s in re.split(r"(?<=[。；\n!?！？])", text) if s.strip()]


def find_death(text, want_year):
    """句级配对：含死亡词的句子，取句中（或相邻句）日期"""
    sents = split_sents(text)
    cands = []
    for i, s in enumerate(sents):
        if not DEATH_RE.search(s):
            continue
        if any(f in s for f in FUNERAL):
            continue
        if re.match(r"^\s*(逝世|去世|身后|身後)", s):   # 目录式小节标题
            continue
        for j in (i, i - 1, i + 1):
            if j < 0 or j >= len(sents):
                continue
            if any(f in sents[j] and j != i for f in FUNERAL):
                continue
            for mo in DATE_RE.finditer(sents[j]):
                y = int(mo.group(1))
                m = int(mo.group(2)) if mo.group(2) else None
                d = int(mo.group(3)) if mo.group(3) else None
                cands.append({"y": y, "m": m, "d": d, "sent": re.sub(r"\s+", " ", s)[:150],
                              "dist": abs(j - i)})
    if not cands:
        return None, []
    same = [c for c in cands if want_year and c["y"] == want_year]
    pool = same if same else cands
    pool.sort(key=lambda c: (c["dist"], c["m"] is None, -(c["m"] or 0), -(c["d"] or 0)))
    return pool[0], pool[:6]


def find_cause(text):
    out = []
    for rx in CAUSE_RE:
        for mo in rx.finditer(text):
            s = re.sub(r"\s+", " ", mo.group(1)).strip(" ，,、而")
            s = re.sub(r"(在|於|于)[^，,]{2,10}$", "", s).strip(" ，,、而")
            if 2 <= len(s) <= 30 and not re.search(r"\d{3,}", s):
                out.append({"cause": s, "sent": re.sub(r"\s+", " ", mo.group(0))[:130]})
    # 去重
    seen, uniq = set(), []
    for o in out:
        if o["cause"] not in seen:
            seen.add(o["cause"])
            uniq.append(o)
    return uniq[:5]


def classify(cats):
    out = {}
    for label, kws in CAT_RULES:
        hit = [c for c in cats if any(k in c for k in kws)]
        if hit:
            out.setdefault(label, hit[:5])
    return out


def get_lead(text, maxc=900):
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    out = ""
    for p in paras[:4]:
        if len(out) >= 350:
            break
        out += p + "\n\n"
    return out.strip()[:maxc]


ACH = re.compile(r"[^。；\n]{0,45}(?:榮獲|荣获|獲得|获得|奪得|夺得|被評為|被评为|首位|第一個|"
                 r"第一个|開創|开创|代表作|被譽為|被誉为|當選|当选|創辦|创办|獲頒|獲獎|获奖)"
                 r"[^。；\n]{0,70}")


def achievements(text, limit=8):
    seen, out = set(), []
    for mo in ACH.finditer(text):
        s = re.sub(r"\s+", " ", mo.group(0)).strip(" ，,")
        if 14 <= len(s) <= 120 and s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= limit:
            break
    return out


seed = json.load(open(SEED, encoding="utf-8"))
try:
    OVR = json.load(open("/tmp/title_overrides.json", encoding="utf-8"))
except Exception:
    OVR = {}
res = []
t0 = time.time()

for p in seed:
    name = (p.get("name") or "").strip()
    if not name:
        continue
    sd = p.get("died") or ""
    wy = int(sd[:4]) if len(sd) >= 4 else None
    rec = {"name": name, "seed": {k: p.get(k) for k in
                                  ("born", "died", "cause", "cat", "region", "en")}}
    hit = None
    variant_used = None
    forced = OVR.get(name)
    if forced:
        rows = fts('title_tok:"%s"' % tok(forced))
        tgt = [r for r in rows if r[1] == forced]
        if tgt:
            hit = {"rowid": tgt[0][0], "title": tgt[0][1], "len": tgt[0][2], "exact": True}
            variant_used = forced
    for v in ([] if hit else variants(name)):
        rows = fts('title_tok:"%s"' % tok(v))
        if not rows:
            continue
        exact = [r for r in rows if r[1] == v]
        cand = exact[0] if exact else None
        if not cand:
            suff = [r for r in rows if re.match(r"^%s\s*[（(]" % re.escape(v), r[1])]
            cand = suff[0] if suff else rows[0]
        hit = {"rowid": cand[0], "title": cand[1], "len": cand[2], "exact": bool(exact)}
        variant_used = v
        break

    if not hit:
        rec["status"] = "not_found"
        res.append(rec)
        continue

    title, text, cats_raw = fetch(hit["rowid"])
    cats = cats_raw.split()[:80]

    # 消歧义页处理
    if is_dab(text):
        dab = parse_dab(text, name, wy)
        rec["dab"] = dab
        if dab and dab.get("sub_title"):
            rows = fts('title_tok:"%s"' % tok(dab["sub_title"]))
            tgt = [r for r in rows if r[1] == dab["sub_title"]]
            if tgt:
                hit = {"rowid": tgt[0][0], "title": tgt[0][1], "len": tgt[0][2], "exact": True}
                title, text, cats_raw = fetch(hit["rowid"])
                cats = cats_raw.split()[:80]
                rec["dab_resolved"] = True
        if is_dab(text):
            rec["status"] = "disambiguation"
            rec["wiki"] = {"rowid": hit["rowid"], "title": title, "chars": len(text)}
            rec["dab_candidates"] = re.sub(r"\s+", " ", text[:500])
            res.append(rec)
            continue

    died, cands = find_death(text, wy)
    year_in_text = bool(wy and re.search(r"%d\s*年" % wy, text))
    person_like = any(any(h in c for h in PERSON_HINT) for c in cats)
    confidence = ("high" if (hit["exact"] and year_in_text)
                  else "medium" if (year_in_text or person_like)
                  else "low")

    rec.update({
        "status": "ok",
        "wiki": {"rowid": hit["rowid"], "title": title, "chars": len(text),
                 "exact": hit["exact"], "variant": variant_used},
        "confidence": confidence,
        "year_in_text": year_in_text,
        "died_ext": died,
        "died_cands": cands,
        "cause_ext": find_cause(text),
        "lead": get_lead(text),
        "ach": achievements(text),
        "cats": cats[:60],
        "cats_class": classify(cats),
        "text": text,
    })
    res.append(rec)

json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
from collections import Counter
ok = [r for r in res if r["status"] == "ok"]
print(json.dumps({
    "total": len(res), "ok": len(ok),
    "conf": dict(Counter(r["confidence"] for r in ok)),
    "disambiguation": sum(1 for r in res if r["status"] == "disambiguation"),
    "not_found": sum(1 for r in res if r["status"] == "not_found"),
    "died_extracted": sum(1 for r in ok if r["died_ext"]),
    "cause_extracted": sum(1 for r in ok if r["cause_ext"]),
    "chars": sum(len(r["text"]) for r in ok),
    "sec": round(time.time() - t0, 1),
}, ensure_ascii=False))
