#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检测驾鹤集阅读器数据中的「非人物条目」。

背景：数据源 obituary-atlas 从维基「XXXX年逝世人物列表」采集链接，
但列表中混有事件、列表页、组织、动物、以及重定向错配条目，
被一律当作人物收录。

用法：
  python3 detect_nonperson.py                     # 只输出清单与统计
  python3 detect_nonperson.py --out list.tsv      # 指定清单路径
  python3 detect_nonperson.py --emit-keep         # 同时生成应剔除的姓名集合
"""
import json, os, re, sys, argparse, collections

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DEFAULT = os.path.expanduser("~/Obsidian/Bookshelf/阅读器-驾鹤集/data")

# ---------- 判定规则（高置信度，宁可漏不可误杀） ----------

R_TS = re.compile(r"\s-\s\d{4}-\d{2}-\d{2}T\d{6}\.\d+Z\s*$")          # 文件名带 ISO 时间戳
R_LIST = re.compile(r"(列表|年表|消歧义|消歧義)$")                      # 列表页
R_EVENT = re.compile(
    r"(事件|命案|之死|谋杀案|謀殺案|杀人案|殺人案|枪击案|槍擊案|失踪案|失蹤案"
    r"|事故|爆炸|空难|空難|火災|火灾|車禍|车祸|屠杀|屠殺|惨案|慘案"
    r"|遇刺|刺杀|刺殺|暴動|暴动|騷亂|骚乱|抗议|抗議)$"
)
R_ORG_NAME = re.compile(
    r"(樂團|乐团|乐队|樂隊|女團|女团|男團|男团|合唱團|合唱团|舞團|舞团"
    r"|偶像組合|偶像组合|from EXILE TRIBE)$"
)
R_ORG_CAT = re.compile(r"(樂團|乐团|乐队|樂隊|組合$|组合$|女團|女团|男團|男团|合唱團|合唱团)$")
R_ANIMAL_CAT = re.compile(r"(象隻|犬隻|貓隻|猫只|動物個體|动物个体|個體|松鼠|大熊貓|大熊猫)")
R_CONCEPT_CAT = re.compile(r"(稱謂|称谓|學位|学位|頭銜|头衔|虛構角色|虚构角色|虛構人物|虚构人物|術語|术语)$")
R_EVENT_CAT = re.compile(
    r"(罪案|案件$|谋杀案|謀殺案|殺人案|杀人案|事件$|事故$|空難$|空难$|災難$|灾难$"
    r"|恐怖活動|恐怖活动|暴動$|暴动$|屠殺$|屠杀$)"
)
R_QUOTE = re.compile(r"[「」『』]")

# 已知团体/非人物（纯拉丁名中人工确认项）
KNOWN_NONPERSON = {
    "Ladies' Code", "S.M.THE BALLAD", "SHINee", "MIXNINE", "KARA",
    "FANTASTICS from EXILE TRIBE", "The Birthday", "Surprise U",
    "Kabosu",                              # 柴犬，Doge 原型
    "两岸互赠保育类动物",                    # 列表
}

# 人工核验后确认是真人、规则会误杀的条目（白名单）
FALSE_POSITIVE = {
    "威廉·「胡蒂」·詹森",   # 绰号带引号，本人是美国棒球运动员
    "伊娜·恩德",           # 分类「红色交响乐队」为其所属抵抗组织，本人是德国刑警
}


def load(data_dir):
    idx = json.loads(open(os.path.join(data_dir, "jh.idx.js"), encoding="utf-8")
                     .read().split("=", 1)[1].rstrip().rstrip(";"))
    cat = json.loads(open(os.path.join(data_dir, "catalog.js"), encoding="utf-8")
                     .read().split("=", 1)[1].rstrip().rstrip(";"))
    N, shard = idx["n"], idx["shard"]
    cats = idx["cats"]
    catstr = [cats[c] if c >= 0 else "" for c in idx["cat"]]
    recs = [None] * N
    for k in range(cat["nsh"]):
        t = open(os.path.join(data_dir, "jh.s%03d.js" % k), encoding="utf-8").read()
        arr = json.loads(t.split("]=", 1)[1].rstrip().rstrip(";"))
        for o, r in enumerate(arr):
            i = k * shard + o
            if i < N:
                recs[i] = r
    return idx, catstr, recs


def classify(name, cs, bio, status):
    """返回 (类别, 理由)；非疑似返回 (None, None)"""
    if name in FALSE_POSITIVE:
        return None, None
    if R_TS.search(name):
        return "时间戳残留", "文件名混入 ISO 时间戳，采集写入残留"
    if R_LIST.search(name):
        return "列表/年表", "维基列表页被当人物收录"
    if R_EVENT.search(name):
        if name.endswith("之死"):
            return "事件/案件", "「XX之死」事件条目（被害人非独立人物条目）"
        return "事件/案件", "案件/事件条目，生卒年实为事件日期"
    if name in KNOWN_NONPERSON:
        return "组织/团体", "团体/企划/动物，非个人"
    if R_ORG_NAME.search(name) or R_ORG_CAT.search(cs):
        return "组织/团体", "乐团/组合名"
    if R_ANIMAL_CAT.search(cs):
        return "动物个体", "动物条目（分类：%s）" % cs
    if R_CONCEPT_CAT.search(cs):
        return "非人概念", "概念/称谓/学位条目（分类：%s）" % cs
    if R_EVENT_CAT.search(cs):
        return "事件/案件", "事件类分类（%s）" % cs
    # 引号怪异名：必须同时满足「无分类」「正文为模板套话」，避免误杀绰号带引号的真人
    if R_QUOTE.search(name) and not cs and re.search(r"详见维基百科。?\s*$", (bio or "").strip()):
        return "引号怪异名", "名称含中文引号、无分类、正文仅模板套话"
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DATA_DEFAULT, help="阅读器 data/ 目录")
    ap.add_argument("--out", default=os.path.join(HERE, "nonperson.tsv"))
    ap.add_argument("--emit-keep", action="store_true")
    a = ap.parse_args()

    idx, catstr, recs = load(a.data)
    names = idx["name"]
    N = idx["n"]

    rows = []
    for i in range(N):
        r = recs[i]
        if not r:
            continue
        kind, why = classify(names[i], catstr[i], r.get("bio"), r.get("st"))
        if kind:
            rows.append((kind, names[i], catstr[i], idx["by"][i], idx["dy"][i], why))

    with open(a.out, "w", encoding="utf-8") as f:
        f.write("类别\t姓名\t原始分类\t生年\t卒年\t判定理由\n")
        for x in sorted(rows, key=lambda y: (y[0], y[1])):
            f.write("%s\t%s\t%s\t%d\t%d\t%s\n" % (x[0], x[1], x[2] or "-", x[3], x[4], x[5]))

    cnt = collections.Counter(x[0] for x in rows)
    print("非人物条目 %d / %d = %.2f%%" % (len(rows), N, 100.0 * len(rows) / N))
    for k, v in cnt.most_common():
        print("  %-12s %4d" % (k, v))
    print("清单: %s" % a.out)

    if a.emit_keep:
        p = os.path.join(HERE, "nonperson_names.json")
        json.dump(sorted({x[1] for x in rows}), open(p, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=0)
        print("剔除名单: %s" % p)


if __name__ == "__main__":
    main()
