"""驾鹤集 · 数据库层

设计原则：
1. 一切字段可溯源（source 表记录每个字段的来源与原文片段）
2. 原始文本单独存（raw 表），便于重新解析而不必重抓
3. 分批可重入（upsert 语义），支持增量更新
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterable

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "data", "jiaheji.db")

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- 人物主表
CREATE TABLE IF NOT EXISTS person (
    id            INTEGER PRIMARY KEY,
    key           TEXT UNIQUE NOT NULL,   -- 稳定 slug，用作文件名
    name_zh       TEXT NOT NULL,
    name_trad     TEXT,                   -- 繁体/异体名
    name_en       TEXT,
    aliases       TEXT DEFAULT '[]',      -- JSON 数组
    born_date     TEXT,                   -- YYYY-MM-DD / YYYY-MM / YYYY
    born_prec     TEXT,                   -- day|month|year
    died_date     TEXT,
    died_prec     TEXT,
    cause_raw     TEXT,                   -- 原文死因
    cause_cat     TEXT,                   -- 归类：疾病/事故/自杀/他杀/自然衰老/未知
    cat           TEXT,                   -- 领域：政治家/学者/文学/演艺/体育/媒体/企业家/艺术/宗教/其他
    region        TEXT,                   -- 国家/地区
    occupation    TEXT DEFAULT '[]',      -- JSON 数组
    bio_short     TEXT,                   -- 首段摘要
    wiki_zh_title TEXT,
    wiki_zh_url   TEXT,
    wiki_en_title TEXT,
    wiki_en_url   TEXT,
    wiki_id       INTEGER,                -- zhwiki 内部 id
    tier          INTEGER DEFAULT 3,      -- 1=顶级 2=重要 3=一般
    status        TEXT DEFAULT 'pending', -- verified|partial|pending|missing
    excluded      INTEGER DEFAULT 0,      -- 1=用户手工剔除（不渲染，数据仍保留）
    notes         TEXT,                   -- 人工批注
    created_at    TEXT,
    updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_person_died ON person(died_date);
CREATE INDEX IF NOT EXISTS idx_person_cat  ON person(cat);
CREATE INDEX IF NOT EXISTS idx_person_tier ON person(tier);

-- 来源可溯源
CREATE TABLE IF NOT EXISTS source (
    id           INTEGER PRIMARY KEY,
    person_id    INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    field        TEXT NOT NULL,        -- born/died/cause/bio/cat/...
    kind         TEXT NOT NULL,        -- zhwiki|zhwiki_cat|wikidata|manual|web
    ref          TEXT,                 -- URL / 分类名 / 说明
    snippet      TEXT,                 -- 原文片段（证据）
    retrieved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_source_person ON source(person_id);

-- 生平时间线
CREATE TABLE IF NOT EXISTS timeline (
    id        INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    year      INTEGER,
    date      TEXT,
    event     TEXT NOT NULL,
    source_id INTEGER REFERENCES source(id)
);
CREATE INDEX IF NOT EXISTS idx_timeline_person ON timeline(person_id);

-- 关系
CREATE TABLE IF NOT EXISTS relation (
    id               INTEGER PRIMARY KEY,
    person_id        INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    rel              TEXT NOT NULL,   -- 配偶/子女/师承/同事/对手
    target_name      TEXT NOT NULL,
    target_person_id INTEGER REFERENCES person(id)
);

-- 原始文本快照（便于重解析）
CREATE TABLE IF NOT EXISTS raw (
    person_id  INTEGER PRIMARY KEY REFERENCES person(id) ON DELETE CASCADE,
    zh_title   TEXT,
    zh_cats     TEXT,
    zh_text    TEXT,
    char_count INTEGER,
    fetched_at TEXT
);

-- 元数据（断点续传、抓取水位）
CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT
);
"""


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


@contextmanager
def connect(path: str | None = None):
    p = path or DEFAULT_DB
    os.makedirs(os.path.dirname(p), exist_ok=True)
    con = sqlite3.connect(p, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init(path: str | None = None) -> None:
    with connect(path) as con:
        con.executescript(SCHEMA)
        _migrate(con)


def _migrate(con: sqlite3.Connection) -> None:
    """向后兼容：给已存在的库补新列（CREATE TABLE IF NOT EXISTS 不会加列）"""
    cols = {r["name"] for r in con.execute("PRAGMA table_info(person)")}
    if "excluded" not in cols:
        con.execute("ALTER TABLE person ADD COLUMN excluded INTEGER DEFAULT 0")


def upsert_person(con: sqlite3.Connection, p: dict[str, Any]) -> int:
    """按 key upsert；只更新传入的非空字段。返回 person.id"""
    key = p.get("key") or p["name_zh"]
    row = con.execute("SELECT id FROM person WHERE key=?", (key,)).fetchone()
    ts = now()
    fields = {k: v for k, v in p.items() if k != "key"}
    if row:
        pid = row["id"]
        if fields:
            sets = ", ".join("%s=?" % k for k in fields)
            con.execute("UPDATE person SET %s, updated_at=? WHERE id=?" % sets,
                        (*fields.values(), ts, pid))
    else:
        fields["key"] = key
        fields.setdefault("created_at", ts)
        fields["updated_at"] = ts
        cols = ", ".join(fields)
        marks = ", ".join("?" * len(fields))
        cur = con.execute("INSERT INTO person (%s) VALUES (%s)" % (cols, marks),
                          tuple(fields.values()))
        pid = cur.lastrowid
    return pid


def add_source(con, person_id: int, field: str, kind: str, ref: str,
               snippet: str | None = None) -> int:
    cur = con.execute(
        "INSERT INTO source (person_id, field, kind, ref, snippet, retrieved_at) "
        "VALUES (?,?,?,?,?,?)",
        (person_id, field, kind, ref, (snippet or "")[:800], now()))
    return cur.lastrowid


def set_raw(con, person_id: int, title: str, cats: str, text: str) -> None:
    con.execute(
        "INSERT INTO raw (person_id, zh_title, zh_cats, zh_text, char_count, fetched_at) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(person_id) DO UPDATE SET zh_title=excluded.zh_title, "
        "zh_cats=excluded.zh_cats, zh_text=excluded.zh_text, "
        "char_count=excluded.char_count, fetched_at=excluded.fetched_at",
        (person_id, title, cats, text, len(text or ""), now()))


def meta_set(con, k: str, v: Any) -> None:
    con.execute("INSERT INTO meta (k,v) VALUES (?,?) "
                "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (k, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)))


def meta_get(con, k: str, default=None):
    r = con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def stats(path: str | None = None) -> dict:
    with connect(path) as con:
        out = {}
        out["person"] = con.execute("SELECT COUNT(*) c FROM person").fetchone()["c"]
        out["excluded"] = con.execute(
            "SELECT COUNT(*) c FROM person WHERE COALESCE(excluded,0)=1").fetchone()["c"]
        out["source"] = con.execute("SELECT COUNT(*) c FROM source").fetchone()["c"]
        out["raw"] = con.execute("SELECT COUNT(*) c FROM raw").fetchone()["c"]
        out["by_status"] = {r["status"]: r["c"] for r in con.execute(
            "SELECT status, COUNT(*) c FROM person GROUP BY status")}
        out["by_tier"] = {r["tier"]: r["c"] for r in con.execute(
            "SELECT tier, COUNT(*) c FROM person GROUP BY tier")}
        return out
