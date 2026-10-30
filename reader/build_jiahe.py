#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
驾鹤集 · 离線人物数据库浏览器 —— 数据生成器

输入：~/Obsidian/Bookshelf/驾鹤集/名人逝世/   （render_notes.py 产出的 md；去除非人物条目后约 48,970 人）
输出：~/Obsidian/Bookshelf/阅读器-驾鹤集/     （index.html + app.js + style.css + data/*.js）
本生成器随 obituary-atlas 仓库发布，位于仓库 reader/ 子目录。

与诗词阅读器同一技术范式
------------------------
小入口 + 分片懒加载，全部走经典 <script> 注入 —— file:// 双击即开，
零服务器、零依赖、无需 python。

只做可靠维度
------------
生卒 / 享年 / 年代 / 领域 / 核实状态 / 全文检索。
**不做死因统计**（源头 89% 为「未详」，统计无意义）；详情页如实展示原文即可。

索引与正文分离
--------------
data/jh.idx.js  姓名 + 生卒年 + 领域 + 状态（~5MB，一次加载）
data/jh.sNNN.js 正文，每片 2000 人（~10MB/片，点谁加载谁）
定位：全局 idx 按「逝世年, 姓名」预排序；分片按 idx 顺序切，
      故任意排序下列表第 k 条的 idx 都能算出 shard = idx // 2000。

用法：
    python3 build_jiahe.py                 # 全量
    python3 build_jiahe.py --limit 3000    # 试跑
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor

FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)
KV_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$')
SEC_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
# 维基条目的收尾段，正文到此为止（否则「参考资料 / 30cm / 外部链接」会混进生平）
STOP_RE = re.compile(
    r"^(参考资料|參考資料|外部連結|外部链接|参考文献|參考文獻|註釋|注释|延伸阅读|延伸閱讀|参见|參見|参考|參考)\s*$",
    re.M)
# 「2025年万达镇命案」这类事件条目不是人物，生卒年是事件日期，会污染享年统计
EVENT_RE = re.compile(r"事件|命案|事故|战争|戰爭|爆炸|屠杀|屠殺|选举|選舉|公投|地震|火灾|火災"
                      r"|空难|空難|车祸|車禍|枪击|槍擊|暴走|恐怖襲擊|恐怖袭击|排名|列表|年表")
YEAR_HEAD = re.compile(r"^\d{4}年")

STATUS_ID = {"verified": 0, "partial": 1, "wiki_only": 2, "seed_only": 3}
STATUS_CN = ["已核实", "部分核实", "仅维基", "仅种子"]

# ── 非人物条目过滤 ──────────────────────────────────────────────
# 数据源 obituary-atlas 从维基「XXXX年逝世人物列表」抓链接，列表中混有事件、列表页、
# 组织、动物、以及重定向错配条目，被一律当人物收录。源头排除名单在 jiaheji/data/excluded.txt
# （excl.py 维护，仅打 excluded 标记，原始数据不删），这里只读不写。
# 审计工具：detect_nonperson.py（规则自动发现 → 输出 TSV → 人工确认 → 写入 excluded.txt）
EXCL_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "excluded.txt")
# 文件名混入 ISO 时间戳的残留副本（同一人在库里已有正常条目，副本必删）
TS_TAIL = re.compile(r"\s-\s\d{4}-\d{2}-\d{2}T\d{6}\.\d+Z\s*$")


def load_excl():
    """读取源头排除名单：一行一个姓名，`#` 开头为注释。"""
    out = set()
    if not os.path.exists(EXCL_FILE):
        return out
    with open(EXCL_FILE, encoding="utf-8") as f:
        for ln in f:
            s = ln.strip()
            if s and not s.startswith("#"):
                out.add(s)
    return out


# 维基原始 category 有 8,678 种，直接给用户筛选等于没有筛选。
# 这里归并到 ~20 个领域桶：先具体（配音/演艺/音乐…）后宽泛（政治/军事），命中即止。
FIELD_RULES = [
    ("配音", r"配音|聲優|声优"),
    ("演艺", r"演員|演员|藝人|艺人|模特|模特兒|主持人|舞臺|舞台|表演"),
    ("音乐", r"歌手|音樂|音乐|作曲家|演奏|吉他|鋼琴|钢琴|鍵盤|键盘|小提琴|樂團|乐团|指揮|指挥|聲樂|声乐|鼓手|貝斯|贝斯"),
    ("影视", r"導演|导演|編劇|编剧|攝影師|摄影师|製片|制片|剪輯|剪辑|電影|电影|電視|电视"),
    ("文学", r"作家|詩人|诗人|小說家|小说家|文學|文学|翻譯家|翻译家|散文|隨筆|随筆|劇作家|剧作家|詞人|词人|新聞工作者"),
    ("美术", r"畫家|画家|書法|书法|雕塑|漫畫|漫画|插畫|插画|藝術家|艺术家|設計師|设计师|建築師|建筑师|陶藝|陶艺|篆刻"),
    ("体育", r"運動員|运动员|球員|球员|選手|选手|教練|教练|棋手|棋士|賽車|赛车|車手|车手|體操|体操|劍道|剑道|柔道|相撲|拳擊|拳击|足球|籃球|篮球|棒球|乒乓球|游泳|田徑|田径|馬拉松|马拉松|高爾夫|高尔夫|網球|网球|排球|羽球|舉重|举重"),
    ("学术", r"學者|学者|教授|科學家|科学家|院士|數學家|数学家|物理學家|物理学家|化學家|化学家|生物學家|生物学家|經濟學家|经济学家|歷史學家|历史学家|哲學家|哲学家|人類學家|人类学家|社會學家|社会学家|心理學家|心理学家|天文學家|天文学家|地質學家|地质学家|語言學家|语言学家|研究員|研究員|博士|教育家|博物學家|博物学家|統計學家|统计学家"),
    ("医学", r"醫生|医生|醫學|医学|藥學|药学|護理|护士|護理師|外科|牙醫|牙医|中醫|中医|病理"),
    ("法律", r"律師|律师|法官|檢察官|检察官|法學|法学|大法官|警務|警务|警察|警官|執法|执法"),
    ("军事", r"軍人|军人|將軍|将军|陸軍|陆军|海軍|海军|空軍|空军|上將|上将|中將|中将|少將|少将|大校|元帥|元帅|士兵|飛行員|飞行员|司令|艦長|舰长|烈士|軍閥|军阀|軍校|军校|間諜|间谍|抗日|抗戰|抗战|兵"),
    ("商界", r"企業家|企业家|商人|實業家|实业家|銀行|银行|金融|投資|投资|經濟人物|董事|總裁|总裁|工商|商業|商业"),
    ("宗教", r"僧|禪師|禅师|法師|法师|道士|主教|神父|牧師|牧师|宗教|活佛|喇嘛|阿訇|和尚|教宗|樞機|枢机|修女|穆斯林|伊斯蘭|伊斯兰|佛教|道教|基督教|天主教|傳教士|传教士"),
    ("王室", r"王室|皇族|貴族|贵族|國王|国王|皇帝|君主|公爵|伯爵|侯爵|王子|公主|蘇丹|苏丹|天皇|皇后|親王|亲王|大公"),
    ("工程", r"工程師|工程师|發明家|发明家|技術|技术|程式|程序員|程序员|軟體|软件|航空|航天"),
    ("传媒", r"記者|记者|編輯|编辑|出版|新聞|新闻|評述|评述|專欄|专栏|主播"),
    ("教育", r"教師|教师|校長|校长|教育"),
    ("政治", r"政治|總統|总统|主席|總理|总理|首相|委員|委员|議員|议员|部長|部长|省長|省长|縣長|县长|市長|市长|書記|书记|外交官|大使|政客|政府|國務|国务|黨|党|蘇維埃|议会|議會|酋長|元首|總督|总督|按察使|知縣|知县|社會運動|社会运动|革命家|建國|建国|開國|开国"),
    ("犯罪", r"罪犯|殺手|杀手|殺人|杀人|毒梟|毒枭|連環|连环"),
]
FIELD_OTHER = "其他"
FIELD_NONE = "分类缺失"
NOISE_TAG = ("未知", "驾鹤集", "", "—")


def js(s):
    return json.dumps(s, ensure_ascii=False, separators=(",", ":"))


FIELD_RE = [(name, re.compile(pat)) for name, pat in FIELD_RULES]


def field_of(cat, tags):
    """原始维基分类 → 粗领域桶。先看 category，未命中再看身份标签。

    category 字段在源头就有 41% 是空的（tags 只剩「未知」），这类不是归并漏掉，
    而是数据本身缺失 —— 单列为「分类缺失」，避免和真正的「其他」混在一起。
    """
    real = [t for t in tags if t not in NOISE_TAG]
    for src in (cat, " ".join(real)):
        if not src:
            continue
        for name, rx in FIELD_RE:
            if rx.search(src):
                return name
    if not cat and not real:
        return FIELD_NONE
    return FIELD_OTHER


def parse_fm(raw):
    """返回 (meta dict, body)"""
    m = FM_RE.match(raw)
    if not m:
        return {}, raw
    meta = {}
    for line in m.group(1).split("\n"):
        mm = KV_RE.match(line)
        if not mm:
            continue
        k, v = mm.group(1), mm.group(2).strip()
        if len(v) >= 2 and v[0] == v[-1] == '"':
            v = v[1:-1]
        meta[k] = v
    return meta, raw[m.end():]


def secs(body):
    """按 ## 切段 → {标题: 内容}"""
    out, pos, cur = {}, 0, None
    for m in SEC_RE.finditer(body):
        if cur is not None:
            out[cur] = body[pos:m.start()].strip()
        cur = m.group(1).strip()
        pos = m.end()
    if cur is not None:
        out[cur] = body[pos:].strip()
    return out


def int_or_zero(s):
    m = re.search(r"\d{3,4}", s or "")
    return int(m.group(0)) if m else 0


def get(d, *names):
    for n in names:
        for k in d:
            if k.replace(" ", "") == n:
                return d[k]
    return ""


def one(path):
    """单文件解析 → 元组 或 None"""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except (OSError, UnicodeDecodeError):
        return None
    meta, body = parse_fm(raw)
    name = meta.get("title") or os.path.basename(path)[:-3]
    name = name.strip()
    if not name:
        return None

    seg = secs(body)
    bio = get(seg, "生平") or ""
    if not bio:                                   # 有的条目没有 ## 生平
        plain = re.sub(r"^#.*$", "", body, flags=re.M)
        plain = re.sub(r"^\|.*$", "", plain, flags=re.M)
        bio = plain.strip()
    bio = STOP_RE.split(bio)[0].strip()           # 砍掉参考资料 / 外部链接等收尾段
    bio = re.sub(r"\n{3,}", "\n\n", bio)
    info = get(seg, "身份标签")
    tags = [t for t in re.split(r"[\s`]+", info) if t] if info else []
    if not tags:
        tg = meta.get("tags", "")
        tags = [t.strip().strip('[]"') for t in tg.strip("[]").split(",") if t.strip().strip('[]"')]
        tags = [t for t in tags if t and t != "驾鹤集"]

    by = int_or_zero(meta.get("born_year") or meta.get("born"))
    dy = int_or_zero(meta.get("died_year") or meta.get("died"))
    age = (dy - by) if (by and dy and dy >= by) else 0
    # 172 条算出来 112–145 岁：多数是真·超级人瑞（112–122 岁），少数是源数据把卒年抓错。
    # 超过人类最长寿纪录（122 岁）的一律按「未知」处理，否则会污染享年分布。
    if age > 122:
        age = 0
    return {
        "n": name,
        "by": by, "dy": dy, "age": age,
        "cat": (meta.get("category") or "").strip(),
        "st": STATUS_ID.get((meta.get("status") or "").strip(), 3),
        "wiki": meta.get("wiki", ""),
        "aliases": meta.get("aliases", ""),
        "region": meta.get("region", ""),
        "bio": bio[:12000],
        "tr": 1 if len(bio) > 12000 else 0,
        "ev": 1 if (YEAR_HEAD.match(name) and EVENT_RE.search(name)) else 0,
        "tags": tags[:12],
    }


def collect(src, limit=0):
    files = []
    for r, ds, fs in os.walk(src):
        ds[:] = sorted(d for d in ds if not d.startswith("."))
        for fn in sorted(fs):
            if fn.endswith(".md") and not fn.startswith("_"):
                files.append(os.path.join(r, fn))
    print("    发现 %d 个 md" % len(files), flush=True)
    excl = load_excl()
    print("    排除名单 %d 项" % len(excl), flush=True)
    if limit:
        files = files[:limit]
    recs, t0, done = [], time.time(), 0
    d_ev = d_ex = d_ts = 0
    step = 8000
    with ThreadPoolExecutor(max_workers=8) as ex:
        for i in range(0, len(files), step):
            batch = files[i:i + step]
            for r in ex.map(one, batch):
                if not r:
                    continue
                if r.get("ev"):            # 事件/列表条目（生卒年实为事件日期），不收
                    d_ev += 1
                    continue
                if TS_TAIL.search(r["n"]):  # 文件名残留时间戳的重复副本
                    d_ts += 1
                    continue
                if r["n"] in excl:          # 源头排除名单（非人物条目）
                    d_ex += 1
                    continue
                recs.append(r)
            done += len(batch)
            print("      解析 %6d/%d  %.1fs" % (done, len(files), time.time() - t0), flush=True)
    if d_ev or d_ts or d_ex:
        print("      剔除：事件/列表 %d 条，时间戳副本 %d 条，非人物名单 %d 条"
              % (d_ev, d_ts, d_ex), flush=True)
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.expanduser("~/Obsidian/Bookshelf/驾鹤集/名人逝世"))
    ap.add_argument("--out", default=os.path.expanduser("~/Obsidian/Bookshelf/阅读器-驾鹤集"))
    ap.add_argument("--shard", type=int, default=2000, help="每片人数")
    ap.add_argument("--assets", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "web"))
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    t0 = time.time()
    data = os.path.join(a.out, "data")
    os.makedirs(data, exist_ok=True)

    print("[1/3] 扫描 %s" % a.src, flush=True)
    recs = collect(a.src, a.limit)
    print("    有效条目 %d" % len(recs), flush=True)

    # 预排序：逝世年 → 姓名。索引顺序即默认列表顺序
    recs.sort(key=lambda r: (r["dy"] or 9999, r["by"] or 9999, r["n"]))

    # ---- 领域分类：category 只有 38% 有值，其余归「未分类」 ----
    cat_count = {}
    for r in recs:
        c = r["cat"] or ""
        if c:
            cat_count[c] = cat_count.get(c, 0) + 1
    cats = [c for c, _ in sorted(cat_count.items(), key=lambda kv: -kv[1])]
    cpos = {c: i for i, c in enumerate(cats)}

    # ---- 领域粗分类：8,678 个原始维基分类归并到 ~20 桶，否则筛选没法用 ----
    fld_count = {}
    rec_fld = []
    for r in recs:
        f = field_of(r["cat"], r["tags"])
        rec_fld.append(f)
        fld_count[f] = fld_count.get(f, 0) + 1
    order = sorted((f for f in fld_count if f not in (FIELD_OTHER, FIELD_NONE)),
                   key=lambda f: -fld_count[f])
    for tail in (FIELD_OTHER, FIELD_NONE):
        if tail in fld_count:
            order.append(tail)
    fpos = {f: i for i, f in enumerate(order)}

    names, bys, dys, ages, catid, sts, wikis, tagstr, flid = [], [], [], [], [], [], [], [], []
    for r in recs:
        names.append(r["n"])
        bys.append(r["by"])
        dys.append(r["dy"])
        ages.append(r["age"])
        catid.append(cpos.get(r["cat"], -1))
        sts.append(r["st"])
        wikis.append(1 if r["wiki"] else 0)
        # 标签串进索引：让「姓名·标签」检索不必加载正文分片
        tagstr.append(" ".join(r["tags"] + ([r["cat"]] if r["cat"] else []))[:300])
        flid.append(fpos[rec_fld[len(flid)]])

    # ---- 写索引 ----
    idx = {"n": len(recs), "shard": a.shard, "cats": cats, "fields": order,
           "name": names, "by": bys, "dy": dys, "age": ages,
           "cat": catid, "fld": flid, "st": sts, "w": wikis, "tg": tagstr}
    p = os.path.join(data, "jh.idx.js")
    with open(p, "w", encoding="utf-8") as f:
        f.write("window.JHIDX=")
        json.dump(idx, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";")
    print("[2/3] 索引 %d 人，原始分类 %d 种 → 归并 %d 领域，%.1f MB"
          % (len(recs), len(cats), len(order), os.path.getsize(p) / 1e6), flush=True)

    # ---- 写正文分片 ----
    nsh = (len(recs) + a.shard - 1) // a.shard
    for k in range(nsh):
        buf = []
        for r in recs[k * a.shard:(k + 1) * a.shard]:
            buf.append({k2: r[k2] for k2 in ("n", "by", "dy", "age", "st", "wiki", "region", "aliases", "bio", "tr", "tags")})
        with open(os.path.join(data, "jh.s%03d.js" % k), "w", encoding="utf-8") as f:
            f.write("(window.JHT=window.JHT||{})[%d]=" % k)
            json.dump(buf, f, ensure_ascii=False, separators=(",", ":"))
            f.write(";")
        del buf

    # ---- catalog ----
    decades = {}
    for r in recs:
        if r["dy"]:
            decades[r["dy"] // 10 * 10] = decades.get(r["dy"] // 10 * 10, 0) + 1
    with_age = [r["age"] for r in recs if r["age"]]
    with_age.sort()
    meta = {
        "build": time.strftime("%Y-%m-%d %H:%M"),
        "n": len(recs), "shard": a.shard, "nsh": nsh,
        "cats": len(cats),
        "decades": sorted(decades.items()),
        "by_span": [min(x for x in bys if x) if any(bys) else 0,
                    max(bys) if any(bys) else 0],
        "dy_span": [min(x for x in dys if x) if any(dys) else 0,
                    max(dys) if any(dys) else 0],
        "age_med": with_age[len(with_age) // 2] if with_age else 0,
        "age_n": len(with_age),
        "st": [sts.count(i) for i in range(4)],
        "st_cn": STATUS_CN,
        "fields": [[f, fld_count[f]] for f in order],
        "raw_cats": len(cats),
        "wiki": sum(wikis),
    }
    with open(os.path.join(data, "catalog.js"), "w", encoding="utf-8") as f:
        f.write("window.JHCA=")
        json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";")

    # ---- 静态资源 ----
    cnt = 0
    for fn in ("index.html", "app.js", "style.css"):
        s = os.path.join(a.assets, fn)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(a.out, fn))
            cnt += 1
    print("[3/3] %d 片正文 + 静态资源 %d 个，用时 %.1f 分钟 → %s"
          % (nsh, cnt, (time.time() - t0) / 60, a.out), flush=True)


if __name__ == "__main__":
    sys.exit(main())
