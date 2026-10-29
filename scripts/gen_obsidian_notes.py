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

def build_note(p: dict, raw: dict or None):
    name = p["name_zh"] or p["name_trad"] or p["name_en"] or "未命名"
    en = p.get("name_en") or ""
    born = p.get("born_date") or ""
    died = p.get("died_date") or ""
    cause = p.get("cause_raw") or ""
    cause_cat = p.get("cause_cat") or ""
    cat = p.get("cat") or ""
    region = p.get("region") or ""
    status = p.get("status") or "wiki_only"
    wiki = p.get("wiki_zh_url") or ""
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
    fm.append(f"title: {name}")
    if aliases:
        fm.append(f"aliases: [{', '.join(aliases)}]")
    if born:
        fm.append(f"born: {born}")
    if died:
        fm.append(f"died: {died}")
    if cause:
        fm.append(f"cause: {cause}")
    if cause_cat:
        fm.append(f"cause_cat: {cause_cat}")
    if cat:
        fm.append(f"category: {cat}")
    if region:
        fm.append(f"region: {region}")
    fm.append(f"status: {status}")
    if wiki:
        fm.append(f"wiki: {wiki}")
    fm.append(f"tags: [{', '.join(tags)}]")
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

    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry", action="store_true")
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
