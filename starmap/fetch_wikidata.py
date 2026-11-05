#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""驾鹤集星图 · 从 Wikidata 批量补全「无地理线索」记录的国籍/落位

背景
----
jiaheji.db 中 1976—2025 年逝世的 48,980 人里有约 38.8%（19,024 人）
既没有维基正文、也没有分类/摘要，只剩姓名与生卒日期，故离线推断无法定位。
本项目允许**一次性联网**向 Wikidata 的公共 SPARQL 端点按中文标签批量查询
P27 国籍 / P19 出生地所属国 / P20 逝世地所属国 / P570 逝世日期，
把结果落盘成本地真源 `data/wd_regions.json`；之后 build_starmap.py 完全离线重建。
默认走 QLever 镜像（qlever.dev/api/wikidata，可连续查询）；官方 WDQS 在本网络下
同一 IP 连续请求会握手卡死，故只保留 `--endpoint wdqs` 作为备选。

设计要点
--------
1. 只查「离线推断失败」的人，尽量少打扰公共端点；按批 200 个 VALUES，并发 3，
   失败指数退避重试，逐批落盘 `data/wdcache/batch-NNN.json`，可随时断点续跑。
2. 同名歧义用 P570 逝世年校验：优先选逝世年与库内一致的条目；无日期者要求唯一命中。
3. 地区一律输出**规范中文名**：Q865/Q19188 → 中国台湾，Q8646 → 中国香港，
   Q14773 → 中国澳门，Q148/Q15180 等历史政权 → 现地名/落位参考。
   绝不以「国家」口径表述中国台湾/中国香港/中国澳门。
4. 输出的是「落位参考 + 依据 + 置信度」，不是事实结论；无法确认者不写入。

用法
----
    python3 starmap/fetch_wikidata.py --probe           # 只跑 3 批，验证链路
    python3 starmap/fetch_wikidata.py                  # 全量（可断点续跑）
    python3 starmap/fetch_wikidata.py --aggregate       # 仅从缓存汇总出 wd_regions.json
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import json
import os
import random
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DB = ROOT / "data" / "jiaheji.db"
CACHE = HERE / "data" / "wdcache"
OUT = HERE / "data" / "wd_regions.json"
QID_LABELS_FILE = HERE / "data" / "qid_labels.json"
# 官方 WDQS 在本网络下每 IP 只能成功一次、之后连续请求会握手卡死；
# QLever 的 Wikidata 公共镜像可稳定连续查询，故默认改走它（数据同源）。
ENDPOINTS = {
    "qlever": "https://qlever.dev/api/wikidata",
    "wdqs": "https://query.wikidata.org/sparql",
}
ENDPOINT = ENDPOINTS["qlever"]
PREFIXES = ("PREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
            "PREFIX wd: <http://www.wikidata.org/entity/>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n")
UA = "jiaheji-starmap/1.0 (local research; contact: local user)"

sys.path.insert(0, str(HERE))
import build_starmap as B  # noqa: E402  复用离线推断，判定谁需要联网补

# Wikidata QID → 规范中文地区名。
# 这里只放「必须精确处理」的条目：涉中国主权表述 + 少量历史政权。
# 其余国家一律交给 label_to_region 按中文/英文标签词表匹配，避免凭记忆写错 QID。
QID_FIX = {
    "Q148": "中国",                 # 中华人民共和国
    "Q865": "中国台湾",             # 台湾
    "Q19188": "中国台湾",           # 中华民国（本库均为 1976 年后逝世，多为台湾地区）
    "Q8646": "中国香港",            # 香港
    "Q14773": "中国澳门",           # 澳门
    "Q15180": "俄罗斯",             # 苏联 → 现地名落位参考
    "Q159": "俄罗斯",
    "Q133356": "苏联",              # 兼容旧号（若出现会被词表二次归一）
}

# 无法直接映射的 QID（历史政权/地区）→ 归并到落位参考地区
QID_FALLBACK_LABEL = {
    "南斯拉夫": "塞尔维亚", "蘇聯": "俄罗斯", "苏联": "俄罗斯",
    "中華民國": "中国台湾", "中华民国": "中国台湾",
    "大清": "中国", "清朝": "中国", "滿洲國": "中国", "伪满洲国": "中国",
    "英屬香港": "中国香港", "英属香港": "中国香港",
    "葡屬澳門": "中国澳门", "葡属澳门": "中国澳门",
    "日治臺灣": "中国台湾", "臺灣": "中国台湾", "台灣": "中国台湾",
    "西德": "德国", "東德": "德国", "纳粹德国": "德国",
    "捷克斯洛伐克": "捷克", "南斯拉夫社会主义联邦共和国": "塞尔维亚",
    "奧匈帝國": "奥地利", "奥匈帝国": "奥地利",
    "俄罗斯帝国": "俄罗斯", "美国": "美国", "美國": "美国",
    "奥斯曼帝国": "土耳其", "鄂圖曼帝國": "土耳其",
    "明朝": "中国", "元朝": "中国", "清朝": "中国",
    "唐朝": "中国", "宋朝": "中国", "宋朝 (960年—1279年)": "中国",
    "汪精卫国民政府": "中国", "汪精衛國民政府": "中国",
    "北洋政府": "中国", "北洋政府时期": "中国", "中華民國北洋政府": "中国",
    "满洲国": "中国", "滿洲國": "中国", "伪满洲国": "中国",
    "大英帝国": "英国", "大英帝國": "英国",
    "西班牙帝国": "西班牙", "波希米亚": "捷克", "普鲁士": "德国",
    "内莱塔尼亚": "奥地利", "內萊塔尼亞": "奥地利",
    "大城王国": "泰国", "阿瑜陀耶王国": "泰国",
    "吞武里王朝": "泰国", "拉达那哥欣王国": "泰国", "却克里王朝": "泰国",
    "贡榜王朝": "缅甸", "貢榜王朝": "缅甸",
    "荷属东印度": "印尼", "荷屬東印度": "印尼",
    "英属印度": "印度", "英屬印度": "印度",
    "法属印度支那": "越南", "法屬印度支那": "越南",
    # 2026-11-05 二补：历史政权 / 繁体异名 → 现代落位参考
    "卡扎尔王朝": "伊朗", "卡扎爾王朝": "伊朗",
    "Kingdom of Serbs, Croats and Slovenes": "塞尔维亚",
    "塞尔维亚人、克罗地亚人和斯洛文尼亚人王国": "塞尔维亚",
    "德意志国": "德国", "德意志帝國": "德国", "德意志帝国": "德国",
    "魏瑪共和国": "德国", "魏玛共和国": "德国",
    "普魯士王國": "德国", "普鲁士王国": "德国", "巴伐利亚州": "德国",
    "摩德納和雷焦公國": "意大利", "摩德纳和雷焦公国": "意大利",
    "阿拉伯聯合共和國": "埃及", "阿拉伯联合共和国": "埃及",
    "哈布斯堡君主國": "奥地利", "哈布斯堡君主国": "奥地利",
    "拜占庭帝國": "土耳其", "拜占庭帝国": "土耳其",
    "羅德西亞": "津巴布韦", "罗德西亚": "津巴布韦",
    "科索沃": "塞尔维亚",           # 按中国官方立场，不单列为独立地区
    "無國籍": "", "无国籍": "",     # 无国籍者不落地图
}
REGION_NAMES = {r[0] for r in B.REGIONS}


def label_to_region(label: str) -> str:
    """把 Wikidata 返回的国家标签（中文/英文）映射到 REGIONS 规范名。"""
    if not label:
        return ""
    if label in QID_FALLBACK_LABEL:
        label = QID_FALLBACK_LABEL[label]
    for name, eng, rx, _fb, _cn in B.REGION_RE:
        if rx.search(label):
            return name
        if eng and label.strip().lower() == eng.lower():
            return name
    return ""


def normalize_region(r: str) -> str:
    """最终校验：只返回 REGIONS 表内确有其名的规范地区。"""
    r = QID_FALLBACK_LABEL.get(r, r)
    return r if r in REGION_NAMES else ""


def qid_of(uri: str) -> str:
    return uri.rsplit("/", 1)[-1] if uri else ""


def post_sparql(sparql: str, timeout: int = 90, endpoint: str = ENDPOINT) -> list[dict]:
    """curl POST 提交 SPARQL，返回 results.bindings（零第三方依赖）。"""
    fd, tmp = tempfile.mkstemp(prefix="wdq-", suffix=".rq")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(sparql)
        cmd = ["curl", "-sS", "--noproxy", "*", "-m", str(timeout),
               "-X", "POST",
               "-H", "Accept: application/sparql-results+json",
               "-H", "User-Agent: " + UA,
               "--data-urlencode", "query@" + tmp, endpoint]
        p = subprocess.run(cmd, capture_output=True, timeout=timeout + 20)
        if p.returncode != 0:
            raise RuntimeError("curl %d: %s" % (p.returncode,
                                                p.stderr.decode("utf-8", "replace")[:180]))
        return json.loads(p.stdout)["results"]["bindings"]
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


LANG_PRI = {"zh": 0, "zh-hans": 1, "zh-cn": 1, "zh-hant": 2, "zh-tw": 2, "en": 3}


def ensure_qid_labels(endpoint: str = ENDPOINT, verbose: bool = True) -> dict:
    """缓存里出现的国家 QID → 中文（优先）/英文标签，落盘供离线重建使用。"""
    qids = set()
    for f in CACHE.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for b in d.get("bindings", []):
            for k in ("c", "bc", "dc"):
                q = qid_of(b.get(k, {}).get("value", ""))
                if re.fullmatch(r"Q\d+", q):
                    qids.add(q)
    labels = {}
    if QID_LABELS_FILE.exists():
        try:
            labels = json.loads(QID_LABELS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    missing = sorted(qids - set(labels))
    if not missing:
        return labels
    if verbose:
        print("补查国家标签：%d 个新 QID（已有 %d）" % (len(missing), len(labels)), flush=True)
    for i in range(0, len(missing), 300):
        chunk = missing[i:i + 300]
        vals = " ".join("wd:" + q for q in chunk)
        sparql = PREFIXES + """SELECT ?q ?lab ?lang WHERE {
  VALUES ?q { %s }
  ?q rdfs:label ?lab .
  BIND(LANG(?lab) AS ?lang)
  FILTER(?lang IN ("zh","zh-hans","zh-cn","zh-hant","zh-tw","en"))
}""" % vals
        rows = None
        for attempt in range(4):
            try:
                rows = post_sparql(sparql, 90, endpoint)
                break
            except Exception as e:
                err = "%s: %s" % (type(e).__name__, e)
                time.sleep(2 + attempt * 3)
        if rows is None:
            print("  标签批 %d 失败（稍后可用 --aggregate 重试）: %s"
                  % (i // 300, err), flush=True)
            continue
        best = {}
        for b in rows:
            q = qid_of(b.get("q", {}).get("value", ""))
            lab = b.get("lab", {}).get("value", "")
            pri = LANG_PRI.get(b.get("lang", {}).get("value", ""), 9)
            if q and lab and (q not in best or pri < best[q][0]):
                best[q] = (pri, lab)
        for q, v in best.items():
            labels[q] = v[1]
        if verbose:
            print("  标签批 %d: 查 %d / 命中 %d" % (i // 300, len(chunk), len(best)), flush=True)
    QID_LABELS_FILE.write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
    return labels


def candidates_for(name_zh: str, name_trad: str | None, aliases: str) -> list[str]:
    """生成可能出现在 Wikidata rdfs:label@zh 的姓名形态。"""
    out: list[str] = []
    for s in (name_zh, name_trad):
        if s and s not in out:
            out.append(s)
    try:
        for a in json.loads(aliases or "[]"):
            if isinstance(a, str) and a and a not in out:
                out.append(a)
    except Exception:
        pass
    # 去掉消歧义括号后缀，如「馬力 (1952年)」→「馬力」
    for s in list(out):
        t = re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", s).strip()
        if t and t not in out:
            out.append(t)
    return out[:6]


class Fetcher:
    def __init__(self, workers: int, batch: int, timeout: int, delay: float = 0.4,
                 endpoint: str = ENDPOINT, tag: str = "b"):
        self.workers = workers
        self.batch = batch
        self.timeout = timeout
        self.delay = delay
        self.endpoint = endpoint
        self.tag = tag

    def query(self, labels: list[str]) -> list[dict]:
        """用 curl POST 提交查询：长 VALUES 走 GET 会握手超时；QLever 需显式 PREFIX。
        只返回 QID（不走 label service，快且稳定），国家中文名由 qid_labels 后处理。"""
        vals = " ".join(json.dumps(s, ensure_ascii=False) + "@zh" for s in labels)
        sparql = PREFIXES + """SELECT ?label ?item ?dod ?c ?bc ?dc WHERE {
  VALUES ?label { %s }
  ?item rdfs:label ?label .
  OPTIONAL { ?item wdt:P570 ?dod . }
  OPTIONAL { ?item wdt:P27 ?c . }
  OPTIONAL { ?item wdt:P19 ?b . OPTIONAL { ?b wdt:P17 ?bc . } }
  OPTIONAL { ?item wdt:P20 ?d . OPTIONAL { ?d wdt:P17 ?dc . } }
}""" % vals
        return post_sparql(sparql, self.timeout, self.endpoint)

    def run_batch(self, bi: int, labels: list[str]) -> tuple[int, int, str]:
        # 文件名带批大小，避免不同 --batch 参数的缓存互相污染；
        # tag 区分主批次与补漏批次，避免覆盖旧缓存
        path = CACHE / ("%s%d-%03d.json" % (self.tag, self.batch, bi))
        if path.exists():
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
                return bi, len(d.get("bindings", [])), "cached"
            except Exception:
                pass
        err = ""
        for attempt in range(6):
            try:
                rows = self.query(labels)
                path.write_text(json.dumps({"labels": labels, "bindings": rows},
                                           ensure_ascii=False), encoding="utf-8")
                if self.delay:
                    time.sleep(self.delay)
                return bi, len(rows), "ok"
            except Exception as e:
                err = "%s: %s" % (type(e).__name__, e)
                time.sleep(min(40, 2 ** attempt) + random.random())
        return bi, 0, "FAIL " + err


def load_unlocated(limit: int | None = None):
    """复用 build_starmap 的离线推断，找出真正需要联网补的人。"""
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    q = """SELECT p.id, p.name_zh, p.name_trad, p.name_en, p.aliases, p.cat, p.region,
                  p.bio_short, p.died_date, p.excluded, p.cause_cat,
                  substr(r.zh_text,1,500) AS head, r.zh_cats AS cats
           FROM person p LEFT JOIN raw r ON r.person_id = p.id"""
    out = []
    for x in con.execute(q):
        if x["excluded"]:
            continue
        d = (x["died_date"] or "")
        if not d[:4].isdigit() or not 1900 <= int(d[:4]) <= 2100:
            continue
        reg = B.guess_region((x["region"] or "").strip(), x["cat"] or "",
                             x["bio_short"] or "", x["head"] or "", x["name_en"] or "")
        if reg:
            continue
        names = candidates_for(x["name_zh"], x["name_trad"], x["aliases"])
        if not names:
            continue
        out.append({"id": x["id"], "name": x["name_zh"], "dy": int(d[:4]),
                    "labels": names})
    con.close()
    out.sort(key=lambda r: r["id"])
    return out[:limit] if limit else out


def aggregate(verbose: bool = True) -> dict:
    """把逐批缓存汇总成 person_id → 落位参考。"""
    qlabels = {}
    if QID_LABELS_FILE.exists():
        try:
            qlabels = json.loads(QID_LABELS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    people = load_unlocated()
    by_label: dict[str, list[dict]] = collections.defaultdict(list)
    for p in people:
        for lb in p["labels"]:
            by_label[lb].append(p)

    # label → [(itemQID, dodYear, [(qid,label,来源) ...])]
    hits: dict[str, dict[str, dict]] = collections.defaultdict(dict)
    files = sorted(CACHE.glob("*.json"))
    queried = 0
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        queried += len(d.get("labels", []))
        for b in d.get("bindings", []):
            lb = b.get("label", {}).get("value", "")
            item = qid_of(b.get("item", {}).get("value", ""))
            if not lb or not item:
                continue
            dod = b.get("dod", {}).get("value", "")[:4]
            rec = hits[lb].setdefault(item, {"dod": set(), "geo": []})
            if dod.isdigit():
                rec["dod"].add(int(dod))
            for key, src in (("c", "国籍"), ("bc", "出生地"), ("dc", "逝世地")):
                q = qid_of(b.get(key, {}).get("value", ""))
                lab = b.get(key + "Label", {}).get("value", "") or qlabels.get(q, "")
                if q and (q, lab, src) not in rec["geo"]:
                    rec["geo"].append((q, lab, src))

    unmatched: collections.Counter[tuple[str, str]] = collections.Counter()

    def region_of(q: str, lab: str) -> str:
        r = normalize_region(QID_FIX.get(q, "")) or label_to_region(lab)
        if not r:
            unmatched[(q, lab)] += 1
        return normalize_region(r)

    result = {}
    for lb, plist in by_label.items():
        items = hits.get(lb) or {}
        if not items:
            continue
        for p in plist:
            # 同名歧义：优先逝世年一致的条目
            same = [v for v in items.values() if p["dy"] in v["dod"]]
            chosen = same or (list(items.values()) if len(items) == 1 else [])
            for v in chosen:
                cands = []
                for q, lab, src in v["geo"]:
                    r = region_of(q, lab)
                    if r:
                        cands.append(({"国籍": 0, "出生地": 1, "逝世地": 2}[src], r, q, src))
                if not cands:
                    continue
                cands.sort()
                _pri, reg, q, src = cands[0]
                # 逝世年可校验 = 高置信；否则中等
                conf = 1 if v["dod"] and p["dy"] in v["dod"] else 2
                prev = result.get(p["id"])
                if not prev or conf < prev["conf"]:
                    result[p["id"]] = {"region": reg, "qid": q, "src": src,
                                       "conf": conf, "via": lb, "dod": sorted(v["dod"])}
    out = {"source": "Wikidata (P27/P19→P17/P20→P17/P570)，经 WDQS 或 QLever 公共 SPARQL 端点查询",
           "endpoint": "https://qlever.dev/api/wikidata (主要) / https://query.wikidata.org/sparql (早期批次)",
           "count": len(result),
           "note": "落位参考值，非事实结论；中国台湾/中国香港/中国澳门为规范地区表述。",
           "items": {str(k): v for k, v in sorted(result.items())}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=None), encoding="utf-8")
    if verbose:
        dist = collections.Counter(v["region"] for v in result.values())
        print("缓存批次:", len(files), " 已查询标签:", queried,
              " 命中并落位:", len(result),
              " 占离线未定位人数: %.1f%%" % (100 * len(result) / max(1, len(people))))
        print("地区 top15:", dist.most_common(15))
        if unmatched:
            print("未能映射的国家标签 top25（可据此补充词表）:",
                  unmatched.most_common(25))
        print("已写出:", OUT, "%.2f MB" % (OUT.stat().st_size / 1e6))
    return out


def do_fill(args, endpoint: str):
    """补漏：只查缓存里确实没出现过的中文标签（词表变化导致批次错位时用）。"""
    people = load_unlocated(args.limit or None)
    labels, seen = [], set()
    for p in people:
        for lb in p["labels"]:
            if lb not in seen:
                seen.add(lb)
                labels.append(lb)
    cached = set()
    for f in CACHE.glob("*.json"):
        try:
            cached.update(json.loads(f.read_text(encoding="utf-8")).get("labels", []))
        except Exception:
            pass
    missing = [l for l in labels if l not in cached]
    print("标签总数:", len(labels), " 已缓存:", len(labels) - len(missing),
          " 需补查:", len(missing), flush=True)
    if not missing:
        ensure_qid_labels(endpoint)
        aggregate()
        return
    batches = [missing[i:i + args.batch] for i in range(0, len(missing), args.batch)]
    f = Fetcher(args.workers, args.batch, args.timeout, args.delay, endpoint, tag="fill-")
    t0 = time.time()
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(f.run_batch, i, b): i for i, b in enumerate(batches)}
        for fu in concurrent.futures.as_completed(futs):
            bi, n, status = fu.result()
            done += 1
            if status.startswith("FAIL") or done % 10 == 0 or done == len(batches):
                print("[%3d/%3d] fill %3d: %5d bindings  %s  (%.0fs)"
                      % (done, len(batches), bi, n, status, time.time() - t0), flush=True)
    ensure_qid_labels(endpoint)
    aggregate()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="只跑前 3 批验证链路")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 人（调试）")
    ap.add_argument("--batch", type=int, default=200)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--delay", type=float, default=0.4, help="每批成功后的礼貌间隔秒数")
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--endpoint", choices=list(ENDPOINTS), default="qlever")
    ap.add_argument("--aggregate", action="store_true", help="仅汇总缓存，不联网")
    ap.add_argument("--fill", action="store_true", help="只补查缓存中缺失的中文标签")
    args = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    endpoint = ENDPOINTS[args.endpoint]
    if args.fill:
        do_fill(args, endpoint)
        return
    if args.aggregate:
        ensure_qid_labels(endpoint)
        aggregate()
        return

    people = load_unlocated(args.limit or None)
    labels = []
    seen = set()
    for p in people:
        for lb in p["labels"]:
            if lb not in seen:
                seen.add(lb)
                labels.append(lb)
    batches = [labels[i:i + args.batch] for i in range(0, len(labels), args.batch)]
    if args.probe:
        batches = batches[:3]
    print("待补人数:", len(people), " 唯一中文标签:", len(labels),
          " 批数:", len(batches), " 并发:", args.workers, flush=True)

    f = Fetcher(args.workers, args.batch, args.timeout, args.delay, endpoint)
    t0 = time.time()
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(f.run_batch, i, b): i for i, b in enumerate(batches)}
        for fu in concurrent.futures.as_completed(futs):
            bi, n, status = fu.result()
            done += 1
            if status.startswith("FAIL") or done % 10 == 0 or done == len(batches):
                print("[%3d/%3d] batch %3d: %5d bindings  %s  (%.0fs)"
                      % (done, len(batches), bi, n, status, time.time() - t0), flush=True)
    ensure_qid_labels(endpoint)
    aggregate()


if __name__ == "__main__":
    main()
