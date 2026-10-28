#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""驾鹤集 · 排除名单

用户不必认识的每一个人都收进最终列表。`data/excluded.txt` 里一行一个名字（或文件名 key），
构建时把这些人的 `person.excluded` 置 1：

- 名录、日历、年表、统计、Obsidian 笔记全部不再出现
- **数据库里的原始文本与来源一条不删**，把那一行从文件里去掉、重跑构建，人就完整回来

文件格式：
    # 注释行，忽略
    某人姓名
    某个文件名key

用法：
    python3 src/jiaheji/excl.py add 张三 李四     # 追加
    python3 src/jiaheji/excl.py list            # 看当前名单
    python3 src/jiaheji/excl.py rm 张三          # 从名单移除
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FILE = os.path.join(ROOT, "data", "excluded.txt")

HEADER = """# 驾鹤集 · 排除名单
# 一行一个：姓名或详情页文件名（p/<key>.html 里的 key）
# 以 # 开头为注释；从本文件删掉某行并重跑构建，该人会完整回来（原始数据从未删除）
"""


def load() -> set:
    if not os.path.exists(FILE):
        return set()
    out = set()
    with open(FILE, encoding="utf-8") as f:
        for ln in f:
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            out.add(s)
    return out


def _read_lines():
    if not os.path.exists(FILE):
        return []
    with open(FILE, encoding="utf-8") as f:
        return f.read().splitlines()


def _write_lines(lines):
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    with open(FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")


def add(names):
    lines = _read_lines()
    if not lines:
        lines = HEADER.rstrip().splitlines()
    body = {ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")}
    added = []
    for n in names:
        n = n.strip()
        if n and n not in body:
            lines.append(n)
            body.add(n)
            added.append(n)
    _write_lines(lines)
    return added


def rm(names):
    kill = {n.strip() for n in names}
    lines = _read_lines()
    keep = [ln for ln in lines if not (ln.strip() in kill and not ln.strip().startswith("#"))]
    _write_lines(keep)
    return len(lines) - len(keep)


def apply(con):
    """把名单落到 person.excluded。每次构建全量重算，幂等。

    返回 (标记数, 未匹配上的名单项)
    """
    names = load()
    con.execute("UPDATE person SET excluded=0")
    if not names:
        return 0, []
    q = "UPDATE person SET excluded=1 WHERE name_zh=? OR key=? OR name_trad=?"
    hit = set()
    for n in names:
        cur = con.execute(q, (n, n, n))
        if cur.rowcount:
            hit.add(n)
    return len(hit), sorted(names - hit)


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("list", "ls"):
        names = sorted(load())
        print("排除名单：%d 人  →  %s" % (len(names), FILE))
        for n in names:
            print("  " + n)
        return
    cmd, rest = args[0], [a for a in args[1:] if a.strip()]
    if cmd in ("add", "rm", "del", "remove") and rest:
        if cmd == "add":
            got = add(rest)
            print("已加入 %d 项：%s" % (len(got), "、".join(got) or "（均已存在）"))
        else:
            n = rm(rest)
            print("已移除 %d 项" % n)
        return
    print(__doc__)


if __name__ == "__main__":
    main()
