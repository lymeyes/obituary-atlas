# 真源与重建手册（SOURCE-DATA）

> 本仓库不只存代码，**也存能重建全部产物的真源数据**。
> 目的：即使本地磁盘、NAS 镜像、同步链路全部损毁，只要 GitHub 还在，就能完整重建 49,157 人档案 + 站点。

## 一、数据分层

| 层 | 内容 | 可否再生 | 是否入库 |
|---|---|---|---|
| **真源 L1** | 中文维基 dump 的生卒模板索引（`tpl_people.jsonl`） | ❌ 需要 NUC 上的 4.9GB `zhwiki.db` + 数小时扫描 | ✅ 直接入库（11.8 MB）|
| **真源 L2** | 从维基抽取的人物正文（`full_49k.jsonl.xz`） | ❌ 需要 NUC 全库 FTS + 约 40 分钟 | ✅ xz 压缩入库 |
| **真源 L3** | 人工核校种子（`seed385.json`）+ 排除名单 + 标题覆盖 | ❌ 手工产出 | ✅ 直接入库 |
| **派生** | `jiaheji.db`（SQLite，162 MB） | ✅ 由 L1+L2+L3 用 `build_db.py` 重建 | ❌ 不入库（可重建）|
| **派生** | `out/site/`（静态站点，218 MB，49,157 页） | ✅ 由 DB 用 `render_site.py` 渲染 | ❌ 不入库（在 `gh-pages` 分支）|
| **派生** | Obsidian 笔记（49,158 篇 .md，252 MB） | ✅ 由 DB 用 `gen_obsidian_notes.py` 生成 | ❌ 不入库（本地/NAS 用）|

设计原则：**只把「不可再生」的放上 GitHub**，其余一律靠脚本重建，避免仓库膨胀。

## 二、真源清单

| 文件 | 体积 | 行/条目 | SHA-256（前 16 位）|
|---|---|---|---|
| `data/tpl_people.jsonl` | 11.80 MB | 85,211 | `7337bf6d67c0b712` |
| `data/full_49k.jsonl.xz` | 33.07 MB（解压 124.57 MB）| 30,128 | `1d1e608ea021353e` |
| `data/seed385.json` | 0.13 MB | 386 人 | `2fe9911a59725e77` |
| `data/excluded.txt` | <1 KB | — | `e8bd58802703bef5` |
| `data/title_overrides.json` | <1 KB | — | `6473a24685d1b0cc` |

> `tpl_people.jsonl` 含 **85,211** 条全库命中，`build_db.py` 会按 `1976 <= 逝世年 <= 2025` 过滤出 **49,042** 人，再叠加种子与覆盖。

## 三、从零重建（15 分钟，无需联网）

```bash
git clone https://github.com/lymeyes/obituary-atlas.git
cd obituary-atlas

# 1) 解压正文真源（124 MB）
xz -dk data/full_49k.jsonl.xz

# 2) 校验完整性
cd data && shasum -a 256 -c SHA256SUMS && cd ..

# 3) 建库：Stage A 索引 + Stage B 注入正文
python3 src/jiaheji/build_db.py            # 建表 + 49,042 索引 + 386 种子
python3 src/jiaheji/build_db.py merge      # 注入 30,128 篇正文

# 4) 渲染静态站点 → out/site/
python3 src/jiaheji/render_site.py

# 5) 生成 Obsidian 笔记（可选，需先改 --out 指向你的 vault）
python3 scripts/gen_obsidian_notes.py --out "/path/to/你的库/驾鹤集/名人逝世"
```

重建后可与下列基线对照：

| 指标 | 期望值 |
|---|---|
| `person` 表 | 49,157 行 |
| `raw` 表（有正文）| 30,128 行 |
| 正文总字数 | 约 4,170 万字 |
| 站点详情页 | 49,157 个 |
| 状态分布 | verified 386 / partial 29,859 / wiki_only 18,912 |

## 四、唯一无法从本仓库恢复的东西

`zhwiki.db`（4.9 GB，中文维基全库 FTS 索引）**不在本仓库**，也不在任何备份里。
它是 L1/L2 的「母矿」。但**只要 L1+L2 在，就不需要它** —— 它只用于「重新扫描、扩充新数据」。

若将来要增量更新（例如补 2026 年新逝者），需要重新从维基 dump 构建 `zhwiki.db`：
`https://dumps.wikimedia.org/zhwiki/latest/zhwiki-latest-pages-articles.xml.bz2`

## 五、数据口径说明

- **生卒日期 100% 准确**：全部来自维基 `{{bd}}` / `{{death date}}` / `{{birth date}}` 结构化模板解析，非自由文本猜测。
- **38% 的人没有正文**：其维基条目为红链或标题不匹配，本地库确实无正文可抽（实测补漏命中率仅 0.5%，已放弃）。
- **死因**：从正文首段正则提取，可信度中等，字段 `cause_cat` 做粗分类（疾病/意外/自然/未知）。
- **领域/籍贯**：`category` 取维基首个非噪声分类；籍贯类（如「上海人」）已剥离到 `origin` 字段，不再污染领域。
