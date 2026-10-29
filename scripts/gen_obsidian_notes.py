#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 obituary-atlas 全量人物从本地 SQLite 生成到 Obsidian「驾鹤集/名人逝世」。

- 复刻现有 385 篇精校笔记的富格式（frontmatter + 基本信息表 + 生平 + 死因 + 身份标签 + 来源）
- 已有同名 .md 文件的（385 篇 verified 精校）一律跳过，绝不覆盖
- 数据来源：data/jiaheji.db 的 person 表（生卒/死因/领域/地区/状态/维基链接）+ raw 表（zh_text 全文 / zh_cats 标签）
- 用法：python3 scripts/gen_obsidian_notes.py [--out DIR] [--limit N] [--dry]
"""
import os, sys, json, sqlite3, argparse, re
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "jiaheji.db")
DEFAULT_OUT = os.path.expanduser("~/Obsidian/Noteshelf/我的书库/驾鹤集/名人逝世")
# 生成器专属标记，用于 --overwrite 时识别「自己的产物」而不误伤精校笔记
GENERATED_MARK = "obituary-atlas（本地离线镜像）"

ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]+')

def slug_name(name: str) -> str:
    s = ILLEGAL.sub("_", (name or "").strip())
    s = s.strip("._ ")
    return s or "未命名"

def compute_age(born: str, died: str):
    try:
        b = date.fromisoformat(born)
        d = date.fromisoformat(died)
        a = d.year - b.year - ((d.month, d.day) < (b.month, b.day))
        return a
    except Exception:
        return None

def parse_cats(raw):
    if not raw:
        return []
    try:
        v = json.loads(raw)
        if isinstance(v, list):
            return [str(x) for x in v if x]
    except Exception:
        pass
    # 可能是管道/逗号分隔
    return [c.strip() for c in re.split(r"[|,]", raw) if c.strip()]

STATUS_LABEL = {
    "verified": "✔ 已核实",
    "partial": "◐ 部分核实",
    "wiki_only": "○ 仅索引（维基无独立词条）",
}

# 维基分类里的噪声（「1921年出生」这类不是领域），不作为 category
NOISE_CAT = re.compile(r"^\d{3,4}年(出生|逝世|生|卒)")
# 维基分类里「上海人 / 北京市 / 无锡县」这类是籍贯，不是领域/职业
PLACE_CAT = re.compile(r"(人|縣|县|市|省|區|区|鎮|镇|村|鄉|乡|旗|盟|州|出身人物|裔)$")
# 奖项/家族/生卒者类分类，也不是「领域」
NOISE_TAIL = re.compile(r"(家族|獲得者|获得者|得主|出生者|逝世者|校友|毕业生)$")

def oneline(s) -> str:
    """字段压成单行：换行/制表/竖线一律替换，避免撑破 Markdown 表格。
    2026-10-29 修：此前 cause 含换行（如「并发症去世。\\n\\n 电影作品列表」）
    导致基本信息表断裂。"""
    if not s:
        return ""
    s = str(s).replace("|", "／").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return re.sub(r"\s{2,}", " ", s).strip()

def yq(s) -> str:
    """YAML 安全的字符串字面量（借 JSON 编码转义）：含冒号/引号的内容不会破坏 frontmatter。"""
    return json.dumps(str(s), ensure_ascii=False)

def build_note(p: dict, raw: dict or None):
    name = oneline(p["name_zh"] or p["name_trad"] or p["name_en"] or "未命名")
    en = oneline(p.get("name_en") or "")
    born = oneline(p.get("born_date") or "")
    died = oneline(p.get("died_date") or "")
    cause = oneline(p.get("cause_raw") or "")
    cause_cat = oneline(p.get("cause_cat") or "")
    cat = oneline(p.get("cat") or "")
    if NOISE_CAT.match(cat):      # 「1921年出生」之类不是领域
        cat = ""
    origin = ""
    if cat and PLACE_CAT.search(cat):   # 「上海人 / 北京市」是籍贯，不是领域 → 移到 origin
        origin = cat
        cat = ""
    if cat and NOISE_TAIL.search(cat):  # 奖项/家族/校友类，不是领域
        cat = ""
    region = oneline(p.get("region") or "")
    status = p.get("status") or "wiki_only"
    wiki = oneline(p.get("wiki_zh_url") or "")
    aliases = [en] if en else []

    age = compute_age(born, died)
    age_txt = f"{age} 岁" if age is not None else "—"

    # tags：固定 + 死因类型（领域偏噪，仅作补充，不强行塞入）
    tags = ["驾鹤集"]
    if cause_cat:
        tags.append(cause_cat)
    if cat and cat not in tags:
        tags.append(cat)

    fm = ["---"]
    fm.append(f"title: {yq(name)}")
    if aliases:
        fm.append("aliases: [" + ", ".join(yq(a) for a in aliases) + "]")
    if born:
        fm.append(f"born: {born}")
        by = born[:4]
        if by.isdigit():
            fm.append(f"born_year: {int(by)}")
    if died:
        fm.append(f"died: {died}")
        dy = died[:4]
        if dy.isdigit():
            fm.append(f"died_year: {int(dy)}")
    if cause:
        fm.append(f"cause: {yq(cause)}")
    if cause_cat:
        fm.append(f"cause_cat: {yq(cause_cat)}")
    if cat:
        fm.append(f"category: {yq(cat)}")
    if origin:
        fm.append(f"origin: {yq(origin)}")
    if region:
        fm.append(f"region: {yq(region)}")
    fm.append(f"status: {yq(status)}")
    if wiki:
        fm.append(f"wiki: {yq(wiki)}")
    fm.append("tags: [" + ", ".join(yq(t) for t in tags) + "]")
    fm.append("---")

    # 正文
    lines = []
    lines.append(f"# {name}")
    sub = []
    if en:
        sub.append(en)
    if region:
        sub.append(region)
    if sub:
        lines.append("")
        lines.append("*" + "　".join(sub) + "*")

    # 基本信息表
    lines.append("")
    lines.append("## 基本信息")
    lines.append("")
    lines.append("| 项目 | 内容 |")
    lines.append("| --- | --- |")
    lines.append(f"| 出生 | {born+'年'.join(['',''])[0] if born else '—'} |".replace("年", "年", 1) if False else f"| 出生 | {born or '—'} |")
    lines.append(f"| 逝世 | {died or '—'} |")
    lines.append(f"| 享年 | {age_txt} |")
    lines.append(f"| 死因 | 🕯️ {cause} |" if cause else "| 死因 | — |")
    lines.append(f"| 死因类型 | {cause_cat} |" if cause_cat else "| 死因类型 | — |")
    lines.append(f"| 领域 | {cat} |" if cat else "| 领域 | — |")
    if origin:
        lines.append(f"| 籍贯 | {origin} |")
    lines.append(f"| 地区 | {region} |" if region else "| 地区 | — |")
    if status in STATUS_LABEL:
        lines.append(f"| 核实状态 | {STATUS_LABEL[status]} |")

    # 生平
    lines.append("")
    lines.append("## 生平")
    lines.append("")
    text = (raw or {}).get("zh_text") or ""
    if text:
        # 取全文（本地离线百科），但去掉可能的过多空行
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        lines.append(text)
    elif p.get("bio_short"):
        lines.append(p["bio_short"])
    else:
        lines.append(f"{name}（{born} — {died}），详见维基百科。")

    # 逝世与死因
    if cause:
        lines.append("")
        lines.append("## 逝世与死因")
        lines.append("")
        lines.append(f"- **死因**：{cause}")

    # 身份标签
    cats = parse_cats((raw or {}).get("zh_cats") or "")
    if cats:
        lines.append("")
        lines.append("## 身份标签")
        lines.append("")
        lines.append("`" + "`　`".join(cats[:24]) + "`")

    # 来源
    lines.append("")
    lines.append("## 来源")
    lines.append("")
    if wiki:
        lines.append(f"- [zhwiki]({wiki})")
    lines.append("- 数据来自 obituary-atlas（本地离线镜像）")
    lines.append("")
    lines.append("相关：[[驾鹤集 · 索引]]")

    # 2026-10-29 修：此前 return 只拼了 lines，fm（YAML 头）被整体丢弃，
    # 导致 48,767 篇笔记没有 frontmatter、Obsidian Dataview 全部查不到。
    return "\n".join(fm + [""] + lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--overwrite", action="store_true",
                    help="覆盖生成器自己此前写出的笔记（靠固定标记识别）；精校笔记仍不覆盖")
    args = ap.parse_args()

    con = sqlite3.connect(args.db); con.row_factory = sqlite3.Row
    out = args.out
    os.makedirs(out, exist_ok=True)

    rows = con.execute(
        "SELECT p.* FROM person p WHERE p.excluded=0 ORDER BY p.died_date DESC, p.name_zh"
    ).fetchall()

    seen = set()
    total = 0
    skipped = 0
    written = 0
    no_raw = 0
    for p in rows:
        total += 1
        name = p["name_zh"] or p["name_trad"] or p["name_en"] or "未命名"
        fn = slug_name(name) + ".md"
        # 同名冲突：追加逝世年
        if fn in seen:
            fn = f"{slug_name(name)}_{p['died_date'][:4] if p['died_date'] else 'x'}.md"
        seen.add(fn)
        path = os.path.join(out, fn)
        if os.path.exists(path):
            # 默认跳过；--overwrite 时只重写「生成器自己的产物」，
            # 判据 = 正文含固定标记（精校笔记没有该标记，故永不被覆盖）
            if not args.overwrite:
                skipped += 1
                continue
            try:
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    body = fh.read()
            except Exception:
                body = ""
            if GENERATED_MARK not in body:
                skipped += 1
                continue
        raw = con.execute(
            "SELECT zh_text, zh_cats FROM raw WHERE person_id=?", (p["id"],)
        ).fetchone()
        if not raw or not (raw["zh_text"] or "").strip():
            no_raw += 1
        if args.dry:
            continue
        note = build_note(dict(p), dict(raw) if raw else None)
        with open(path, "w", encoding="utf-8") as f:
            f.write(note)
        written += 1
        if args.limit and written >= args.limit:
            break

    print(f"[gen_obsidian_notes] DB persons={total} | skipped(existing)={skipped} | "
          f"written={written} | wiki_only(no full text)={no_raw} | out={out}")


if __name__ == "__main__":
    main()
