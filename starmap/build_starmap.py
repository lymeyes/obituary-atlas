#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""驾鹤集星图 · 数据生成器

从 jiaheji.db 生成纯前端可直接 <script src> 加载的 window.JHSTAR。

设计要点
--------
1. 完全离线：所有数据（含世界陆地轮廓）内嵌进一个 JS 文件，页面不 fetch、
   不访问任何地图服务、不含任何 API key，file:// 直开即可。
2. 地图合规：底图只用 Natural Earth 110m **land**（仅海岸线，无国界、无行政
   边界、无争议地区标注）；177 国几何仅用于计算国家中心点，不参与绘制。
   所有地区名称使用规范中文表述（中国台湾 / 中国香港 / 中国澳门）。
3. 地区为**文本推断**值：库里 region 字段 49,157 条中仅 386 条有值，故从
   维基分类、摘要、正文首段按词表推断，仅供星点落位参考，不作事实结论。
   无地理线索的记录不落地图，但完整保留在名单中。
4. 只增不删：不修改数据库、不删除任何既有文件；输出覆盖由 --out 指定的
   生成物（生成物可随时由本脚本重建）。

用法
----
    python3 starmap/build_starmap.py                       # 默认输出到 Bookshelf/驾鹤集星图/data/
    python3 starmap/build_starmap.py --out /tmp/star      # 指定输出目录
    python3 starmap/build_starmap.py --check              # 只打印统计，不写文件
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GEO = HERE / "geo"
DB = ROOT / "data" / "jiaheji.db"
DEFAULT_OUT = Path.home() / "Obsidian" / "Bookshelf" / "驾鹤集星图" / "data"

LAND_JSON = GEO / "land-110m.json"          # 无国界陆地（绘制用）
COUNTRIES_JSON = GEO / "countries-110m.json"  # 国家几何（仅算中心点，不绘制）

# ---------------------------------------------------------------- TopoJSON --
def _arcs(topo: dict) -> list[list[tuple[float, float]]]:
    """解码 TopoJSON 的 delta 编码 arcs，返回经纬度点列。"""
    tr = topo.get("transform")
    arcs = []
    for raw in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in raw:
            x += dx
            y += dy
            if tr:
                lon = x * tr["scale"][0] + tr["translate"][0]
                lat = y * tr["scale"][1] + tr["translate"][1]
            else:
                lon, lat = x, y
            pts.append((lon, lat))
        arcs.append(pts)
    return arcs


def _ring(arc_idxs: list[int], arcs: list) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for i in arc_idxs:
        if i >= 0:
            seg = arcs[i]
        else:
            seg = list(reversed(arcs[~i]))
        if out:
            seg = seg[1:]          # 去重复端点
        out.extend(seg)
    return out


def _polygons(geom: dict, arcs: list) -> list[list[list[tuple[float, float]]]]:
    """统一返回 [polygon][ring][point]。"""
    if geom["type"] == "Polygon":
        return [[_ring(r, arcs) for r in geom["arcs"]]]
    out = []
    for poly in geom["arcs"]:
        out.append([_ring(r, arcs) for r in poly])
    return out


def _project(lon: float, lat: float, w=1000.0, h=500.0):
    """等距圆柱投影（Equirectangular）：经度 -180..180 → x 0..w，纬度 90..-90 → y 0..h。"""
    return (lon + 180.0) / 360.0 * w, (90.0 - lat) / 180.0 * h


def land_svg_path(topo: dict, w=1000.0, h=500.0) -> str:
    """把 land TopoJSON 转成一条 SVG path（只有海岸线，无任何国界）。"""
    arcs = _arcs(topo)
    parts = []
    for geom in topo["objects"]["land"]["geometries"]:
        for poly in _polygons(geom, arcs):
            for ring in poly:
                if len(ring) < 3:
                    continue
                seg = []
                for lon, lat in ring:
                    x, y = _project(lon, lat, w, h)
                    seg.append("%.1f,%.1f" % (x, y))
                parts.append("M" + "L".join(seg) + "Z")
    return "".join(parts)


def _ring_area_centroid(ring):
    """平面 shoelace，返回 (面积绝对值, 质心)。坐标系经纬度，够作落位参考。"""
    a = cx = cy = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-12:
        return 0.0, (ring[0][0], ring[0][1])
    return abs(a) / 2.0, (cx / (3 * a), cy / (3 * a))


def country_centroids(topo: dict) -> dict[str, list[float]]:
    """英文名 → [lon, lat]，取该国面积最大的多边形之质心（避开飞地/海外领地）。"""
    arcs = _arcs(topo)
    out = {}
    for geom in topo["objects"]["countries"]["geometries"]:
        name = (geom.get("properties") or {}).get("name")
        if not name:
            continue
        best_a, best_c = -1.0, None
        for poly in _polygons(geom, arcs):
            if not poly:
                continue
            a, c = _ring_area_centroid(poly[0])   # 外环
            if a > best_a:
                best_a, best_c = a, c
        if best_c:
            out[name] = [round(best_c[0], 2), round(best_c[1], 2)]
    return out


# ------------------------------------------------------------------- 地区表 --
# (规范中文名, TopoJSON 英文名, 关键词正则, 备用中心点, 是否中国地区)
# 顺序 = 匹配优先级：越具体越靠前（先「中国香港」再「中国」）。
REGIONS: list[tuple[str, str | None, str, list[float], bool]] = [
    ("中国香港", None, r"香港|Hong\s?Kong|港裔|港籍", [114.17, 22.32], True),
    ("中国澳门", None, r"澳門|澳门|Macau|Macao|澳籍", [113.54, 22.19], True),
    ("中国台湾", "Taiwan", r"台灣|台湾|臺北|台北|高雄|臺南|台南|中華民國|中华民国|立法院|金馬獎|金马奖", [121.0, 23.7], True),
    ("中国", "China", r"中国|中國|中華人民共和國|中华人民共和国|大陆|大陸|北京|上海|南京|廣東|广东|江蘇|江苏|浙江|四川|山東|山东|河南|河北|湖南|湖北|福建|安徽|江西|陝西|陕西|遼寧|辽宁|吉林|黑龍江|黑龙江|雲南|云南|貴州|贵州|廣西|广西|甘肅|甘肃|青海|寧夏|宁夏|新疆|西藏|內蒙|内蒙|天津|重慶|重庆|山西|海南|中国人民|中國人民|解放軍|解放军|中共|國務院|国务院", [104.0, 35.0], True),
    ("美国", "United States of America", r"美国|美國|美籍|美裔|紐約|纽约|加州|華盛頓|华盛顿|USA|U\.S\.|American", [-98.0, 39.0], False),
    ("日本", "Japan", r"日本|日裔|日籍|東京|东京|大阪|京都|JPN|Japanese", [138.0, 36.5], False),
    ("英国", "United Kingdom", r"英国|英國|英籍|倫敦|伦敦|London|British|英格蘭|英格兰|蘇格蘭|苏格兰|威爾斯|威尔士", [-2.0, 54.0], False),
    ("俄罗斯", "Russia", r"俄羅斯|俄罗斯|俄裔|蘇聯|苏联|莫斯科|俄共|Russian|Soviet", [60.0, 60.0], False),
    ("法国", "France", r"法國|法国|法籍|巴黎|French", [2.5, 47.0], False),
    ("德国", "Germany", r"德國|德国|德籍|柏林|German|納粹|纳粹", [10.5, 51.0], False),
    ("韩国", "South Korea", r"韓國|韩国|南韓|首爾|首尔|大韓民國|大韩民国|Korean", [127.8, 36.4], False),
    ("朝鲜", "North Korea", r"北韓|北韩|朝鲜|朝鮮|平壤|朝鮮民主主義|朝鲜民主主义", [127.0, 40.0], False),
    ("意大利", "Italy", r"義大利|意大利|羅馬|罗马|Italian", [12.5, 42.8], False),
    ("西班牙", "Spain", r"西班牙|馬德里|马德里|Spanish", [-3.7, 40.2], False),
    ("印度", "India", r"印度|India|Indian", [79.0, 22.0], False),
    ("加拿大", "Canada", r"加拿大|Canada|Canadian", [-106.0, 56.0], False),
    ("澳大利亚", "Australia", r"澳大利亞|澳大利亚|澳洲|Australian", [134.0, -25.0], False),
    ("新加坡", None, r"新加坡|Singapore", [103.8, 1.35], False),
    ("马来西亚", "Malaysia", r"馬來西亞|马来西亚|Malaysia", [102.0, 4.0], False),
    ("越南", "Vietnam", r"越南|Vietnam|Vietnamese", [106.0, 16.0], False),
    ("泰国", "Thailand", r"泰國|泰国|Thailand", [101.0, 15.0], False),
    ("菲律宾", "Philippines", r"菲律賓|菲律宾|Philippines", [122.0, 12.0], False),
    ("印尼", "Indonesia", r"印尼|印度尼西亞|印度尼西亚|Indonesia", [118.0, -2.0], False),
    ("荷兰", "Netherlands", r"荷蘭|荷兰|Netherlands|Dutch", [5.5, 52.2], False),
    ("瑞士", "Switzerland", r"瑞士|Switzerland|Swiss", [8.2, 46.8], False),
    ("瑞典", "Sweden", r"瑞典|Sweden|Swedish", [15.0, 62.0], False),
    ("挪威", "Norway", r"挪威|Norway|Norwegian|奧斯陸|奥斯陆", [9.0, 62.0], False),
    ("丹麦", "Denmark", r"丹麥|丹麦|Denmark|Danish", [10.0, 56.0], False),
    ("芬兰", "Finland", r"芬蘭|芬兰|Finland|Finnish", [26.0, 64.0], False),
    ("波兰", "Poland", r"波蘭|波兰|Poland|Polish|華沙|华沙", [19.0, 52.0], False),
    ("奥地利", "Austria", r"奧地利|奥地利|Austria|維也納|维也纳", [14.5, 47.5], False),
    ("比利时", "Belgium", r"比利時|比利时|Belgium", [4.5, 50.7], False),
    ("希腊", "Greece", r"希臘|希腊|Greece|Greek|雅典", [22.0, 39.0], False),
    ("葡萄牙", "Portugal", r"葡萄牙|Portugal|里斯本", [-8.0, 39.5], False),
    ("爱尔兰", "Ireland", r"愛爾蘭|爱尔兰|Ireland|Irish", [-8.0, 53.2], False),
    ("捷克", "Czechia", r"捷克|Czech|布拉格", [15.3, 49.8], False),
    ("匈牙利", "Hungary", r"匈牙利|Hungary|布達佩斯|布达佩斯", [19.5, 47.2], False),
    ("罗马尼亚", "Romania", r"羅馬尼亞|罗马尼亚|Romania", [25.0, 46.0], False),
    ("保加利亚", "Bulgaria", r"保加利亞|保加利亚|Bulgaria", [25.0, 42.8], False),
    ("塞尔维亚", "Serbia", r"塞爾維亞|塞尔维亚|南斯拉夫|Yugoslav", [21.0, 44.0], False),
    ("克罗地亚", "Croatia", r"克羅地亞|克罗地亚|Croatia", [16.4, 45.3], False),
    ("乌克兰", "Ukraine", r"烏克蘭|乌克兰|Ukraine|基輔|基辅", [31.5, 49.0], False),
    ("白俄罗斯", "Belarus", r"白俄羅斯|白俄罗斯|Belarus", [28.0, 53.7], False),
    ("土耳其", "Turkey", r"土耳其|Turkey|土耳其人|伊斯坦堡|伊斯坦布尔", [35.0, 39.0], False),
    ("以色列", "Israel", r"以色列|Israel|Israeli", [35.0, 31.5], False),
    ("伊朗", "Iran", r"伊朗|Iran|Persian|波斯", [53.7, 32.4], False),
    ("伊拉克", "Iraq", r"伊拉克|Iraq|巴格達|巴格达", [43.7, 33.2], False),
    ("叙利亚", "Syria", r"敘利亞|叙利亚|Syria", [38.5, 35.0], False),
    ("黎巴嫩", None, r"黎巴嫩|Lebanon", [35.9, 33.9], False),
    ("约旦", "Jordan", r"約旦|约旦|Jordan", [36.2, 30.6], False),
    ("沙特", "Saudi Arabia", r"沙特|沙烏地|Saudi", [45.0, 24.0], False),
    ("阿联酋", "United Arab Emirates", r"阿聯酋|阿联酋|阿拉伯聯合大公國|阿拉伯联合酋长国|UAE|杜拜|迪拜", [54.0, 24.0], False),
    ("卡塔尔", None, r"卡塔爾|卡塔尔|Qatar", [51.2, 25.3], False),
    ("埃及", "Egypt", r"埃及|Egypt|開羅|开罗", [30.0, 26.8], False),
    ("南非", "South Africa", r"南非|South\s?Africa", [25.0, -29.0], False),
    ("尼日利亚", "Nigeria", r"尼日利亞|奈及利亞|尼日利亚|Nigeria", [8.0, 9.5], False),
    ("肯尼亚", "Kenya", r"肯尼亞|肯尼亚|Kenya", [37.8, 0.5], False),
    ("埃塞俄比亚", "Ethiopia", r"衣索比亞|埃塞俄比亞|埃塞俄比亚|Ethiopia", [39.0, 9.0], False),
    ("摩洛哥", "Morocco", r"摩洛哥|Morocco", [-6.5, 32.0], False),
    ("阿尔及利亚", "Algeria", r"阿爾及利亞|阿尔及利亚|Algeria", [3.0, 28.0], False),
    ("突尼斯", "Tunisia", r"突尼西亞|突尼斯|Tunisia", [9.5, 34.0], False),
    ("利比亚", "Libya", r"利比亞|利比亚|Libya", [17.5, 27.0], False),
    ("苏丹", "Sudan", r"蘇丹|苏丹|Sudan", [30.0, 15.5], False),
    ("刚果（金）", "Dem. Rep. Congo", r"剛果|刚果|Congo", [23.5, -2.8], False),
    ("津巴布韦", "Zimbabwe", r"津巴布韋|津巴布韦|Zimbabwe", [29.8, -19.0], False),
    ("加纳", "Ghana", r"加納|迦納|加纳|Ghana", [-1.0, 7.9], False),
    ("坦桑尼亚", "Tanzania", r"坦桑尼亞|坦桑尼亚|Tanzania", [34.9, -6.4], False),
    ("墨西哥", "Mexico", r"墨西哥|Mexico", [-102.0, 23.5], False),
    ("巴西", "Brazil", r"巴西|Brazil", [-52.0, -12.0], False),
    ("阿根廷", "Argentina", r"阿根廷|Argentina", [-63.0, -35.0], False),
    ("智利", "Chile", r"智利|Chile", [-71.0, -35.0], False),
    ("哥伦比亚", "Colombia", r"哥倫比亞|哥伦比亚|Colombia", [-73.0, 4.0], False),
    ("秘鲁", "Peru", r"秘魯|秘鲁|Peru", [-75.0, -9.0], False),
    ("委内瑞拉", "Venezuela", r"委內瑞拉|委内瑞拉|Venezuela", [-66.0, 7.0], False),
    ("古巴", "Cuba", r"古巴|Cuba", [-79.5, 21.8], False),
    ("乌拉圭", "Uruguay", r"烏拉圭|乌拉圭|Uruguay", [-56.0, -33.0], False),
    ("玻利维亚", "Bolivia", r"玻利維亞|玻利维亚|Bolivia", [-64.5, -17.0], False),
    ("巴拉圭", "Paraguay", r"巴拉圭|Paraguay", [-58.0, -23.0], False),
    ("厄瓜多尔", "Ecuador", r"厄瓜多爾|厄瓜多尔|Ecuador", [-78.0, -1.5], False),
    ("新西兰", "New Zealand", r"新西蘭|新西兰|紐西蘭|New\s?Zealand", [172.5, -41.0], False),
    ("巴基斯坦", "Pakistan", r"巴基斯坦|Pakistan", [69.3, 30.0], False),
    ("孟加拉国", "Bangladesh", r"孟加拉|Bangladesh", [90.3, 23.7], False),
    ("缅甸", "Myanmar", r"緬甸|缅甸|Myanmar|Burma", [96.0, 21.0], False),
    ("柬埔寨", "Cambodia", r"柬埔寨|Cambodia|高棉", [104.9, 12.6], False),
    ("老挝", "Laos", r"寮國|老撾|老挝|Laos", [103.0, 18.0], False),
    ("蒙古", "Mongolia", r"蒙古|Mongolia", [103.8, 46.8], False),
    ("尼泊尔", "Nepal", r"尼泊爾|尼泊尔|Nepal", [84.0, 28.2], False),
    ("斯里兰卡", "Sri Lanka", r"斯里蘭卡|斯里兰卡|Sri\s?Lanka", [80.8, 7.8], False),
    ("阿富汗", "Afghanistan", r"阿富汗|Afghanistan", [66.0, 33.8], False),
    ("哈萨克斯坦", "Kazakhstan", r"哈薩克|哈萨克|Kazakh", [67.0, 48.0], False),
    ("乌兹别克斯坦", "Uzbekistan", r"烏茲別克|乌兹别克|Uzbek", [63.0, 41.5], False),
    ("格鲁吉亚", "Georgia", r"喬治亞|格鲁吉亚|Georgia", [43.5, 42.0], False),
    ("亚美尼亚", "Armenia", r"亞美尼亞|亚美尼亚|Armenia", [45.0, 40.2], False),
    ("阿塞拜疆", "Azerbaijan", r"亞塞拜然|阿塞拜疆|Azerbaijan", [47.5, 40.3], False),
    ("冰岛", "Iceland", r"冰島|冰岛|Iceland", [-19.0, 64.8], False),
    ("塞浦路斯", None, r"塞浦路斯|Cyprus", [33.2, 35.1], False),
    ("阿尔巴尼亚", "Albania", r"阿爾巴尼亞|阿尔巴尼亚|Albania", [20.0, 41.1], False),
    ("斯洛文尼亚", "Slovenia", r"斯洛維尼亞|斯洛文尼亞|斯洛文尼亚|Slovenia", [14.8, 46.1], False),
    ("斯洛伐克", "Slovakia", r"斯洛伐克|Slovakia", [19.7, 48.7], False),
    ("立陶宛", "Lithuania", r"立陶宛|Lithuania", [23.9, 55.2], False),
    ("拉脱维亚", "Latvia", r"拉脫維亞|拉脱维亚|Latvia", [24.9, 56.9], False),
    ("爱沙尼亚", "Estonia", r"愛沙尼亞|爱沙尼亚|Estonia", [25.7, 58.7], False),
    ("波黑", "Bosnia and Herz.", r"波士尼亞|波斯尼亚|波黑|Bosnia", [18.0, 44.0], False),
    ("巴勒斯坦", "Palestine", r"巴勒斯坦|Palestine", [35.2, 31.9], False),
    ("也门", "Yemen", r"也門|也门|Yemen", [47.5, 15.5], False),
    ("阿曼", "Oman", r"阿曼|Oman", [56.0, 21.0], False),
    ("科威特", None, r"科威特|Kuwait", [47.5, 29.3], False),
    ("文莱", None, r"汶萊|文莱|Brunei", [114.7, 4.5], False),
    ("巴拿马", "Panama", r"巴拿馬|巴拿马|Panama", [-80.0, 8.5], False),
    ("哥斯达黎加", "Costa Rica", r"哥斯大黎加|哥斯达黎加|Costa\s?Rica", [-84.0, 10.0], False),
    ("危地马拉", "Guatemala", r"瓜地馬拉|危地马拉|Guatemala", [-90.3, 15.7], False),
    ("海地", "Haiti", r"海地|Haiti", [-72.3, 19.0], False),
    ("多米尼加", "Dominican Rep.", r"多明尼加|多米尼加|Dominican", [-70.5, 19.0], False),
    ("波多黎各", None, r"波多黎各|Puerto\s?Rico", [-66.3, 18.2], False),
    ("巴布亚新几内亚", "Papua New Guinea", r"巴布亞|巴布亚|Papua", [145.0, -6.0], False),
    ("斐济", "Fiji", r"斐濟|斐济|Fiji", [178.0, -17.5], False),
    ("马达加斯加", "Madagascar", r"馬達加斯加|马达加斯加|Madagascar", [46.8, -19.0], False),
    ("索马里", "Somalia", r"索馬利亞|索马里|Somalia", [46.0, 5.0], False),
    ("安哥拉", "Angola", r"安哥拉|Angola", [17.5, -12.3], False),
    ("莫桑比克", "Mozambique", r"莫桑比克|Mozambique", [35.5, -18.0], False),
    ("赞比亚", "Zambia", r"贊比亞|赞比亚|Zambia", [27.8, -13.5], False),
    ("乌干达", "Uganda", r"烏干達|乌干达|Uganda", [32.3, 1.2], False),
    ("喀麦隆", "Cameroon", r"喀麥隆|喀麦隆|Cameroon", [12.3, 5.5], False),
    ("塞内加尔", "Senegal", r"塞內加爾|塞内加尔|Senegal", [-14.5, 14.5], False),
    ("尼日尔", "Niger", r"尼日爾|尼日尔|Niger", [9.0, 17.5], False),
    ("马里", "Mali", r"馬里|马里|Mali", [-3.5, 17.0], False),
    ("乍得", "Chad", r"乍得|Chad", [18.7, 15.3], False),
    ("卢森堡", None, r"盧森堡|卢森堡|Luxembourg", [6.1, 49.7], False),
    ("马耳他", None, r"馬爾他|馬耳他|马耳他|Malta", [14.4, 35.9], False),
    # ---- 2026-11-05 为 Wikidata 补全新增（只作落位参考，eng=None 用备用中心点）----
    ("北马其顿", "Macedonia", r"北馬其頓|北马其顿|馬其頓|马其顿|North\s?Macedonia|Macedonia", [21.7, 41.6], False),
    ("摩尔多瓦", "Moldova", r"摩爾多瓦|摩尔多瓦|Moldova", [28.4, 47.4], False),
    ("吉尔吉斯斯坦", "Kyrgyzstan", r"吉爾吉斯|吉尔吉斯|Kyrgyz", [74.6, 41.5], False),
    ("塔吉克斯坦", "Tajikistan", r"塔吉克|Tajik", [71.0, 38.5], False),
    ("土库曼斯坦", "Turkmenistan", r"土庫曼|土库曼|Turkmen", [59.4, 39.1], False),
    ("塞拉利昂", "Sierra Leone", r"塞拉利昂|Sierra\s?Leone", [-11.8, 8.6], False),
    ("利比里亚", "Liberia", r"利比里亞|利比里亚|Liberia", [-9.4, 6.4], False),
    ("几内亚", "Guinea", r"幾內亞|几内亚|Guinea", [-10.9, 10.0], False),
    ("科特迪瓦", "Côte d'Ivoire", r"象牙海岸|科特迪瓦|Ivory\s?Coast|Côte", [-5.5, 7.6], False),
    ("布基纳法索", "Burkina Faso", r"布吉納法索|布基纳法索|Burkina", [-1.6, 12.3], False),
    ("多哥", "Togo", r"多哥|Togo", [1.0, 8.5], False),
    ("贝宁", "Benin", r"貝南|贝宁|Benin", [2.3, 9.6], False),
    ("毛里塔尼亚", "Mauritania", r"茅利塔尼亞|毛里塔尼亞|毛里塔尼亚|Mauritania", [-10.3, 20.3], False),
    ("厄立特里亚", "Eritrea", r"厄利垂亞|厄立特里亚|Eritrea", [39.0, 15.4], False),
    ("吉布提", "Djibouti", r"吉布地|吉布提|Djibouti", [42.6, 11.8], False),
    ("加蓬", "Gabon", r"加彭|加蓬|Gabon", [11.6, -0.6], False),
    ("赤道几内亚", "Eq. Guinea", r"赤道幾內亞|赤道几内亚|Equatorial\s?Guinea", [10.3, 1.7], False),
    ("纳米比亚", "Namibia", r"納米比亞|纳米比亚|Namibia", [17.2, -22.1], False),
    ("博茨瓦纳", "Botswana", r"波札那|博茨瓦纳|Botswana", [24.0, -22.2], False),
    ("卢旺达", "Rwanda", r"盧安達|卢旺达|Rwanda", [29.9, -1.9], False),
    ("布隆迪", "Burundi", r"蒲隆地|布隆迪|Burundi", [29.9, -3.4], False),
    ("莱索托", "Lesotho", r"賴索托|莱索托|Lesotho", [28.2, -29.6], False),
    ("斯威士兰", "eSwatini", r"史瓦帝尼|斯威士兰|Swaziland|Eswatini", [31.5, -26.5], False),
    ("毛里求斯", None, r"模里西斯|毛里求斯|Mauritius", [57.6, -20.2], False),
    ("科摩罗", None, r"葛摩|科摩罗|Comoros", [43.3, -11.9], False),
    ("塞舌尔", None, r"塞席爾|塞舌尔|Seychelles", [55.5, -4.7], False),
    ("不丹", "Bhutan", r"不丹|Bhutan", [90.4, 27.5], False),
    ("马尔代夫", None, r"馬爾地夫|馬爾代夫|马尔代夫|Maldives", [73.5, 3.2], False),
    ("东帝汶", "Timor-Leste", r"東帝汶|东帝汶|Timor", [125.6, -8.9], False),
    ("牙买加", "Jamaica", r"牙買加|牙买加|Jamaica", [-77.3, 18.1], False),
    ("特立尼达和多巴哥", "Trinidad and Tobago", r"千里達|特立尼达|Trinidad", [-61.2, 10.5], False),
    ("巴哈马", "Bahamas", r"巴哈馬|巴哈马|Bahamas", [-77.4, 25.0], False),
    ("巴巴多斯", None, r"巴貝多|巴巴多斯|Barbados", [-59.5, 13.2], False),
    ("洪都拉斯", "Honduras", r"宏都拉斯|洪都拉斯|Honduras", [-86.6, 14.8], False),
    ("萨尔瓦多", "El Salvador", r"薩爾瓦多|萨尔瓦多|El\s?Salvador", [-88.9, 13.8], False),
    ("尼加拉瓜", "Nicaragua", r"尼加拉瓜|Nicaragua", [-85.0, 12.9], False),
    ("苏里南", "Suriname", r"蘇利南|苏里南|Suriname", [-55.2, 4.1], False),
    ("圭亚那", "Guyana", r"蓋亞那|圭亚那|Guyana", [-58.7, 5.0], False),
    # ---- 2026-11-05 二补：Wikidata 返回的太平洋/加勒比/非洲小国与地区 ----
    ("几内亚比绍", "Guinea-Bissau", r"畿內亞比紹|几内亚比绍|Guinea.?Bissau", [-15.2, 12.1], False),
    ("中非", "Central African Rep.", r"中非共和國|中非共和国|Central\s?African", [20.5, 7.0], False),
    ("萨摩亚", "Samoa", r"薩摩亞|萨摩亚|Samoa", [-172.5, -13.7], False),
    ("瓦努阿图", "Vanuatu", r"萬那杜|瓦努阿图|Vanuatu", [167.0, -16.2], False),
    ("马绍尔群岛", None, r"馬紹爾群島|马绍尔群岛|Marshall", [171.2, 7.1], False),
    ("密克罗尼西亚", None, r"密克羅尼西亞|密克罗尼西亚|Micronesia", [158.2, 6.9], False),
    ("帕劳", None, r"帛琉|帕劳|Palau", [134.6, 7.3], False),
    ("瑙鲁", None, r"諾魯|瑙鲁|Nauru", [166.9, -0.5], False),
    ("图瓦卢", None, r"吐瓦魯|图瓦卢|Tuvalu", [179.2, -8.5], False),
    ("基里巴斯", None, r"吉里巴斯|基里巴斯|Kiribati", [173.0, 0.0], False),
    ("汤加", None, r"東加|汤加|Tonga", [-175.2, -21.1], False),
    ("佛得角", None, r"維德角|佛得角|Cape\s?Verde|Cabo\s?Verde", [-23.6, 15.1], False),
    ("圣多美和普林西比", None, r"聖多美|圣多美|São\s?Tomé", [6.6, 0.3], False),
    ("冈比亚", "Gambia", r"甘比亞|冈比亚|Gambia", [-15.4, 13.4], False),
    ("马拉维", "Malawi", r"馬拉威|马拉维|Malawi", [34.3, -13.2], False),
    ("圣卢西亚", None, r"聖露西亞|圣卢西亚|Saint\s?Lucia", [-61.0, 13.9], False),
    ("圣文森特和格林纳丁斯", None, r"聖文森|圣文森|Vincent", [-61.2, 13.2], False),
    ("格林纳达", None, r"格瑞那達|格林纳达|Grenada", [-61.7, 12.1], False),
    ("伯利兹", "Belize", r"貝里斯|伯利兹|Belize", [-88.7, 17.2], False),
    ("多哥兰", None, r"多哥蘭|多哥兰|Togoland", [1.0, 8.5], False),
    # ---- 2026-11-05 三补：Wikidata 返回的欧洲城邦/海湾小国与岛屿 ----
    ("黑山", "Montenegro", r"蒙特內哥羅|蒙特内哥罗|黑山|Montenegro", [19.3, 42.8], False),
    ("摩纳哥", None, r"摩納哥|摩纳哥|Monaco", [7.4, 43.7], False),
    ("安道尔", None, r"安道爾|安道尔|Andorra", [1.6, 42.5], False),
    ("列支敦士登", None, r"列支敦斯登|列支敦士登|Liechtenstein", [9.6, 47.2], False),
    ("圣马力诺", None, r"聖馬利諾|圣马力诺|San\s?Marino", [12.4, 43.9], False),
    ("巴林", None, r"巴林|Bahrain", [50.6, 26.1], False),
    ("所罗门群岛", "Solomon Is.", r"所羅門群島|所罗门群岛|Solomon", [160.2, -9.4], False),
    ("马恩岛", None, r"馬恩島|马恩岛|Isle\s?of\s?Man", [-4.5, 54.2], False),
    ("纽埃", None, r"紐埃|纽埃|Niue", [-169.9, -19.1], False),
]

REGION_RE = [(name, eng, re.compile(rx), fallback, is_cn)
             for name, eng, rx, fallback, is_cn in REGIONS]

# emoji 国旗 → 规范中文名（库里 region 字段的形态）
FLAG_MAP = {
    "🇨🇳": "中国", "🇭🇰": "中国香港", "🇲🇴": "中国澳门", "🇺🇸": "美国",
    "🇬🇧": "英国", "🇯🇵": "日本", "🇷🇺": "俄罗斯", "🇮🇳": "印度",
    "🇰🇵": "朝鲜", "🇰🇷": "韩国", "🇿🇦": "南非", "🇨🇺": "古巴",
    "🇸🇪": "瑞典", "🇪🇬": "埃及", "🇵🇸": "巴勒斯坦", "🇫🇷": "法国",
    "🇩🇪": "德国", "🇨🇦": "加拿大", "🇦🇺": "澳大利亚", "🇧🇷": "巴西",
}


def _first_sentence(s: str, limit: int = 110) -> str:
    """取定义性首句（『XX，挪威计算机科学家』），避免后文旅居/任职地干扰。"""
    s = re.split(r"[。！？!\n]", s or "", maxsplit=1)[0]
    return s[:limit]


# 地区置信度 / 依据编码（前端 conf_names / rsrc_names 与之对应）
CONF_EXPLICIT, CONF_HIGH, CONF_MID, CONF_WEAK, CONF_NONE = 0, 1, 2, 3, 4
RS_NONE, RS_FLAG, RS_WIKIDATA, RS_CATS, RS_BIO, RS_TEXT, RS_NAME = 0, 1, 2, 3, 4, 5, 6


def _vote(sources: list[tuple[str, int]]):
    """多来源加权投票；每个来源只取「最具体」的一次命中，返回 (地区名, 总分, 命中来源数)。"""
    score: collections.Counter[str] = collections.Counter()
    hits: collections.Counter[str] = collections.Counter()
    for src, weight in sources:
        if not src:
            continue
        for name, _eng, rx, _fb, _cn in REGION_RE:
            if rx.search(src):
                score[name] += weight
                hits[name] += 1
                break
    if not score:
        return "", 0, 0
    name, total = score.most_common(1)[0]
    return name, total, hits[name]


def _flag_region(flag: str) -> str:
    if not flag:
        return ""
    if re.search(r"台|臺|Taiwan", flag):
        return "中国台湾"
    if re.search(r"香|港|HK|Hong", flag):
        return "中国香港"
    if re.search(r"澳|Mac", flag):
        return "中国澳门"
    if re.search(r"\(美\)|美籍", flag):
        return "美国"
    for k, v in FLAG_MAP.items():
        if k in flag:
            return v
    return ""


def guess_region_full(flag: str, cat: str, bio: str, head: str, name_en: str,
                      cats: str = "", occ: str = "", text: str = "",
                      name_zh: str = "", name_trad: str = "", aliases: str = "",
                      wd: dict | None = None):
    """返回 (规范地区名, 置信度, 依据编码)。

    优先级：原库 flag 标记 > Wikidata 结构化字段 > 摘要/分类 > 维基全部分类 > 正文 > 姓名。
    旧版 guess_region 的判定保持不变（保证既有 61.2% 定位结果稳定），
    扩展来源只用于补齐原先「无线索」的记录。
    """
    fr = _flag_region(flag)
    if fr:
        return fr, CONF_EXPLICIT, RS_FLAG
    if wd and wd.get("region"):
        return wd["region"], min(CONF_MID, max(CONF_HIGH, int(wd.get("conf", 2)))), RS_WIKIDATA

    base = guess_region(flag, cat, bio, head, name_en)
    if base:
        return base, CONF_MID, RS_CATS

    # ---- 扩展来源：原先完全无线索者 ----
    cats_s = (cats or "") + " " + (occ or "")
    sources = [
        (cats_s[:600], 3),
        (_first_sentence(text), 2),
        ((text or "")[:1200], 1),
        ((bio or "")[:400], 1),
        ((head or "")[:900], 1),
    ]
    name_s = " ".join(x for x in (name_zh, name_trad, aliases, name_en) if x)
    sources.append((name_s, 1))
    reg, total, nhit = _vote(sources)
    if reg:
        # 只有姓名命中（如外国音译名不含地名）时不应据此落位
        src_from_name = (reg and _vote([(name_s, 1)])[0] == reg
                         and _vote(sources[:-1])[0] != reg)
        return reg, CONF_WEAK, RS_NAME if src_from_name else RS_CATS
    return "", CONF_NONE, RS_NONE


def guess_region(flag: str, cat: str, bio: str, head: str, name_en: str) -> str:
    """多来源加权投票推断地区，返回规范中文名；无线索返回空串（不落地图）。

    权重反映「定义性」：维基分类与摘要首句是身份定义，正文后段常出现旅居、
    留学、任职等干扰地名，故只给低权重。每个来源只贡献其最具体的一次命中，
    避免宽泛词表（如含大量中国地名）靠重复出现刷分。
    """
    if flag:
        # 形如 🇨🇳(台湾) / 🇨🇳(香港)/🇺🇸 / 🇨🇳(美) —— 括号内限定优先
        if re.search(r"台|臺|Taiwan", flag):
            return "中国台湾"
        if re.search(r"香|港|HK|Hong", flag):
            return "中国香港"
        if re.search(r"澳|Mac", flag):
            return "中国澳门"
        if re.search(r"\(美\)|美籍", flag):
            return "美国"
        for k, v in FLAG_MAP.items():
            if k in flag:
                return v
    sources = [
        (cat or "", 3),
        (_first_sentence(bio), 3),
        (_first_sentence(head), 2),
        ((bio or "")[:220], 1),
        ((head or "")[:420], 1),
        (name_en or "", 1),
    ]
    score: collections.Counter[str] = collections.Counter()
    for src, weight in sources:
        if not src:
            continue
        for name, _eng, rx, _fb, _cn in REGION_RE:
            if rx.search(src):
                score[name] += weight
                break
    return score.most_common(1)[0][0] if score else ""


# ------------------------------------------------------------------- 领域表 --
# 与 reader/build_jiahe.py 的 FIELD_RULES 同源（精简版，避免依赖笔记产物）
FIELD_RULES = [
    ("配音", r"配音|聲優|声优"),
    ("演艺", r"演員|演员|藝人|艺人|模特|主持人|舞臺|舞台|表演"),
    ("音乐", r"歌手|音樂|音乐|作曲家|演奏|吉他|鋼琴|钢琴|樂團|乐团|指揮|指挥|聲樂|声乐"),
    ("影视", r"導演|导演|編劇|编剧|攝影師|摄影师|製片|制片|剪輯|剪辑|電影|电影|電視|电视"),
    ("文学", r"作家|詩人|诗人|小說家|小说家|文學|文学|翻譯家|翻译家|散文|劇作家|剧作家|詞人|词人"),
    ("美术", r"畫家|画家|書法|书法|雕塑|漫畫|漫画|插畫|插画|藝術家|艺术家|設計師|设计师|建築師|建筑师"),
    ("体育", r"運動員|运动员|球員|球员|選手|选手|教練|教练|棋手|賽車|赛车|體操|体操|柔道|相撲|拳擊|拳击|足球|籃球|篮球|棒球|乒乓球|游泳|田徑|田径|馬拉松|马拉松|網球|网球"),
    ("学术", r"學者|学者|教授|科學家|科学家|院士|數學家|数学家|物理學家|物理学家|化學家|化学家|生物學家|生物学家|經濟學家|经济学家|歷史學家|历史学家|哲學家|哲学家|人類學家|人类学家|社會學家|社会学家|心理學家|心理学家|天文學家|天文学家|地質學家|地质学家|語言學家|语言学家|研究員|研究员|教育家"),
    ("医学", r"醫生|医生|醫學|医学|藥學|药学|護理|护士|外科|牙醫|牙医|中醫|中医"),
    ("法律", r"律師|律师|法官|檢察官|检察官|法學|法学|大法官|警察|警官"),
    ("军事", r"軍人|军人|將軍|将军|陸軍|陆军|海軍|海军|空軍|空军|上將|上将|中將|中将|少將|少将|元帥|元帅|士兵|飛行員|飞行员|司令|烈士|軍閥|军阀|間諜|间谍|抗戰|抗战"),
    ("商界", r"企業家|企业家|商人|實業家|实业家|銀行|银行|金融|投資|投资|董事|總裁|总裁|商業|商业"),
    ("宗教", r"僧|禪師|禅师|法師|法师|道士|主教|神父|牧師|牧师|宗教|活佛|喇嘛|阿訇|和尚|教宗|修女|穆斯林|伊斯蘭|伊斯兰|佛教|道教|基督教|天主教|傳教士|传教士"),
    ("王室", r"王室|皇族|貴族|贵族|國王|国王|皇帝|君主|公爵|伯爵|侯爵|王子|公主|蘇丹|苏丹|天皇|皇后|親王|亲王"),
    ("工程", r"工程師|工程师|發明家|发明家|程式|程序員|程序员|軟體|软件|航空|航天|計算機|计算机"),
    ("传媒", r"記者|记者|編輯|编辑|出版|新聞|新闻|專欄|专栏|主播|評述|评述"),
    ("教育", r"教師|教师|校長|校长|教育"),
    ("政治", r"政治|總統|总统|主席|總理|总理|首相|委員|委员|議員|议员|部長|部长|省長|省长|縣長|县长|市長|市长|書記|书记|外交官|大使|政客|政府|國務|国务|黨|党|议会|議會|元首|總督|总督|革命家|開國|开国"),
    ("犯罪", r"罪犯|殺手|杀手|殺人|杀人|毒梟|毒枭|連環|连环"),
]
FIELD_RE = [(n, re.compile(p)) for n, p in FIELD_RULES]


def guess_field(cat: str, bio: str) -> str:
    for src in (cat or "", (bio or "")[:160]):
        if not src:
            continue
        for name, rx in FIELD_RE:
            if rx.search(src):
                return name
    return "分类缺失" if not cat else "其他"


# --------------------------------------------------------------------- 主流程 --
def parse_date(s: str):
    """-> (year, month, day, prec)  prec: 0=日 1=月 2=年 3=缺失"""
    if not s:
        return (0, 0, 0, 3)
    s = s.strip()
    m = re.match(r"^(-?\d{1,4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", s)
    if not m:
        return (0, 0, 0, 3)
    y = int(m.group(1))
    mo = int(m.group(2) or 0)
    d = int(m.group(3) or 0)
    if d:
        return (y, mo, d, 0)
    if mo:
        return (y, mo, 0, 1)
    return (y, 0, 0, 2)


WD_FILE = HERE / "data" / "wd_regions.json"
SHARD_SIZE = 1000            # 每人 id // 1000 → 一个懒加载分片
MAX_BIO_CHARS = 30000        # 超长条目截断，避免单片过大
CAUSES = ["未知", "心脑血管", "癌症", "疾病", "呼吸/感染", "自然衰老",
          "自杀", "事故", "遇害", "其他"]
CONF_NAMES = ["原库标记", "Wikidata·高", "文本推断·中", "文本推断·弱", "未定位"]
RSRC_NAMES = ["无", "原库地区标记", "Wikidata 国籍/出生地", "维基分类/摘要",
              "生平摘要", "维基正文", "姓名线索"]


def guess_field_full(cat: str, bio: str, cats: str, name_zh: str) -> str:
    """领域推断：分类 > 摘要 > 全部分类 > 姓名中的消歧义括注（如「(足球运动员)」）。"""
    f = guess_field(cat, bio)
    if f not in ("分类缺失", "其他"):
        return f
    src = (cats or "")[:400]
    if src:
        for name, rx in FIELD_RE:
            if rx.search(src):
                return name
    m = re.search(r"[（(]([^）)]{2,20})[）)]\s*$", name_zh or "")
    if m:
        for name, rx in FIELD_RE:
            if rx.search(m.group(1)):
                return name
    return f


def load_wd() -> dict:
    if not WD_FILE.exists():
        return {}
    try:
        return json.loads(WD_FILE.read_text(encoding="utf-8")).get("items", {})
    except Exception as e:
        print("Wikidata 补全文件读取失败（忽略）:", e)
        return {}


def occ_text(raw: str) -> str:
    try:
        d = json.loads(raw or "{}")
    except Exception:
        return ""
    out = []
    if isinstance(d, dict):
        for v in d.values():
            if isinstance(v, list):
                out.extend(str(x) for x in v)
    elif isinstance(d, list):
        out.extend(str(x) for x in d)
    return " ".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--check", action="store_true", help="只打印统计，不写文件")
    ap.add_argument("--no-bio", action="store_true", help="不生成完整生平分片")
    args = ap.parse_args()

    for f in (LAND_JSON, COUNTRIES_JSON):
        if not f.exists():
            sys.exit("缺少地理源文件: %s" % f)
    if not Path(args.db).exists():
        sys.exit("缺少数据库: %s" % args.db)

    land_topo = json.loads(LAND_JSON.read_text(encoding="utf-8"))
    ctry_topo = json.loads(COUNTRIES_JSON.read_text(encoding="utf-8"))
    path = land_svg_path(land_topo)
    cents = country_centroids(ctry_topo)

    reg_points, reg_cn = {}, {}
    miss_eng = []
    for name, eng, _rx, fb, is_cn in REGIONS:
        pt = cents.get(eng) if eng else None
        if not pt:
            pt = fb
            if eng:
                miss_eng.append(eng)
        reg_points[name] = pt
        reg_cn[name] = 1 if is_cn else 0
    reg_names = [r[0] for r in REGIONS]
    reg_idx = {n: i for i, n in enumerate(reg_names)}

    wd = load_wd()
    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    q = """SELECT p.id, p.name_zh, p.name_trad, p.name_en, p.aliases,
                  p.born_date, p.died_date, p.cat, p.region, p.bio_short,
                  p.wiki_zh_url, p.wiki_zh_title, p.excluded, p.cause_cat,
                  p.cause_raw, p.occupation,
                  r.zh_text AS text, r.zh_cats AS cats
           FROM person p LEFT JOIN raw r ON r.person_id = p.id"""
    rows = []
    shards: dict[int, dict] = collections.defaultdict(dict)
    stats = collections.Counter()
    region_count = collections.Counter()
    field_count = collections.Counter()
    year_count = collections.Counter()
    cause_count = collections.Counter()
    conf_count = collections.Counter()
    rsrc_count = collections.Counter()
    cause_idx = {c: i for i, c in enumerate(CAUSES)}

    for x in con.execute(q):
        if x["excluded"]:
            stats["excluded"] += 1
            continue
        y, mo, d, prec = parse_date(x["died_date"] or "")
        if not y or y < 1900 or y > 2100:
            stats["no_date"] += 1
            continue
        by, _bm, _bd, _bp = parse_date(x["born_date"] or "")
        age = (y - by) if by and 0 < y - by <= 122 else 0
        cat = (x["cat"] or "").strip()
        bio = (x["bio_short"] or "").strip()
        text = x["text"] or ""
        head = text[:500]
        cats = (x["cats"] or "").strip()
        occ = occ_text(x["occupation"] or "")
        pid = x["id"]
        wdr = wd.get(str(pid))
        reg, conf, rsrc = guess_region_full(
            (x["region"] or "").strip(), cat, bio, head, x["name_en"] or "",
            cats=cats, occ=occ, text=text, name_zh=x["name_zh"] or "",
            name_trad=x["name_trad"] or "", aliases=x["aliases"] or "", wd=wdr)
        fld = guess_field_full(cat, bio, cats + " " + occ, x["name_zh"] or "")
        cau = cause_idx.get((x["cause_cat"] or "未知").strip(), 0)
        region_count[reg or "未定位"] += 1
        field_count[fld] += 1
        year_count[y] += 1
        cause_count[CAUSES[cau]] += 1
        conf_count[CONF_NAMES[conf]] += 1
        rsrc_count[RSRC_NAMES[rsrc]] += 1
        if rsrc == RS_WIKIDATA:
            stats["wd_used"] += 1
        hasbio = 1 if text.strip() else 0
        rows.append([
            x["name_zh"] or "",                 # 0 姓名
            y, mo, d, prec,                    # 1..4 逝世日期
            by, age,                           # 5..6 出生年 / 享年
            reg_idx.get(reg, -1),              # 7 地区下标（-1=未定位）
            fld,                               # 8 领域
            cat[:36],                          # 9 原始分类（短）
            re.sub(r"\s+", " ", bio)[:110],    # 10 摘要
            x["wiki_zh_url"] or "",            # 11 维基链接
            pid,                               # 12 数据库 id（懒加载全文用）
            cau,                               # 13 死因类别下标
            conf,                              # 14 地区置信度
            rsrc,                              # 15 地区依据
            hasbio,                            # 16 是否有完整生平
        ])
        if hasbio and not args.no_bio:
            t = text.strip()
            if len(t) > MAX_BIO_CHARS:
                t = t[:MAX_BIO_CHARS] + "\n\n［原文过长，此处仅保留前 %d 字；完整内容见维基原文］" % MAX_BIO_CHARS
            try:
                al = json.loads(x["aliases"] or "[]")
            except Exception:
                al = []
            shards[pid // SHARD_SIZE][pid] = {
                "t": t,
                "cr": (x["cause_raw"] or "").strip(),
                "cs": (cats or occ)[:300],
                "al": "、".join(str(a) for a in al[:6]),
                "ti": (x["wiki_zh_title"] or "").strip(),
            }
        stats["kept"] += 1
    con.close()

    rows.sort(key=lambda r: (r[1], r[2], r[3], r[0]))
    years = sorted(year_count)
    payload = {
        "build": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "n": len(rows),
        "span": [years[0], years[-1]] if years else [0, 0],
        "by_year": [[y, year_count[y]] for y in years],
        "regions": reg_names,
        "region_points": [reg_points[n] for n in reg_names],
        "region_cn": [reg_cn[n] for n in reg_names],
        "fields": [f for f, _ in field_count.most_common()],
        "causes": CAUSES,
        "conf_names": CONF_NAMES,
        "rsrc_names": RSRC_NAMES,
        "shard_size": SHARD_SIZE,
        "shards": len(shards),
        "bio_count": sum(len(v) for v in shards.values()),
        "wd_count": stats["wd_used"],
        "land": path,
        "rows": rows,
        "cols": ["n", "y", "m", "d", "prec", "by", "age", "reg", "fld", "cat",
                 "bio", "wiki", "id", "cause", "conf", "rsrc", "hasbio"],
        "note": "地区为按 Wikidata 结构化字段 / 维基分类 / 正文推断的落位参考值，非事实结论；未定位者不落地图但完整保留于名单。",
    }

    print("=== 生成统计 ===")
    print("保留记录:", stats["kept"], " 排除非人物:", stats["excluded"], " 无有效日期:", stats["no_date"])
    print("年份跨度:", payload["span"], " 年数:", len(years))
    located = sum(v for k, v in region_count.items() if k != "未定位")
    print("已定位:", located, "(%.1f%%)" % (100 * located / max(1, stats["kept"])),
          " 未定位:", region_count["未定位"], " Wikidata 补齐:", stats["wd_used"])
    print("置信度:", conf_count.most_common())
    print("地区依据:", rsrc_count.most_common())
    print("地区 top12:", region_count.most_common(12))
    print("领域 top10:", field_count.most_common(10))
    print("死因:", cause_count.most_common())
    print("完整生平:", payload["bio_count"], "人 /", len(shards), "分片",
          " 合计 %.1f MB" % (sum(len(v["t"]) for s in shards.values() for v in s.values()) / 1e6))
    print("陆地轮廓 path 长度:", len(path), " 国家质心数:", len(cents),
          " 未匹配英文名:", len(miss_eng), miss_eng[:8])
    print("地区表条目:", len(reg_names))

    if args.check:
        return
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    f = out / "starmap.js"
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    f.write_text("window.JHSTAR=" + body + ";\n", encoding="utf-8")
    print("已写出:", f, "%.2f MB" % (f.stat().st_size / 1e6))

    if not args.no_bio:
        for si, items in sorted(shards.items()):
            parts = ["o[%d]=%s;" % (k, json.dumps(v, ensure_ascii=False, separators=(",", ":")))
                     for k, v in sorted(items.items())]
            js = "(function(o){%s})(window.JHBIO=window.JHBIO||{});\n" % "".join(parts)
            fp = out / ("bio-%03d.js" % si)
            fp.write_text(js, encoding="utf-8")
        print("已写出完整生平分片:", len(shards), "个文件 ->", out)


if __name__ == "__main__":
    main()
