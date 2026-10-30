# 驾鹤集 (JiaHeJi)

> 自 1976 年以来的逝者图谱：带索引、可查询的生平事迹可视化档案。

**在线访问：<https://lymeyes.github.io/obituary-atlas/>**

## 项目简介

驾鹤集是一个从中文维基百科全量 XML dump 解析出生卒信息、构建「1976-01-01 至今逝世人物」结构化档案的开源项目。核心交付物是一个**静态站点**（名录 / 日历 / 年表 / 统计 + 每人生平详情），可通过 GitHub Pages 公开访问，支持按姓名、年份、领域、地区检索；每个人物的生平、主要成就与死因均可溯源至维基百科原文。

你要的形态就是它——**有索引、每人生平事迹可查的图表**。

## 数据来源与准确性

- 中文维基百科 XML dump（存储在 NAS，NUC 上建 FTS5 索引）。
- 生卒日期解析自条目 `{{bd}}` / `{{death date and age}}` 等**结构化生卒模板**，而非自由文本猜测——这是人物条目生卒日期的原始出处，准确率远高于句级文本配对（早期版本曾把张国荣错抽成 1987 年，改用模板后修正为 2003-04-01）。
- `data/seed385.json` 为手工核校的权威种子（毛泽东、周恩来、邓丽君、张国荣、李小龙等 386 人），日期与死因以 seed 为准。
- 简繁自动归一（zhconv），繁体条目（如「張國榮」「鄧麗君」）统一索引。

## 仓库结构

```
jiaheji/
├── src/jiaheji/        # 入库(db.py / build_db.py)、渲染(render_*.py)、排除(excl.py)
├── reader/             # 离线人物浏览器（build_jiahe.py 生成器 + web/ 前端模板 + detect_nonperson.py 审计）
├── scripts/            # dump 扫描(scan_tpl.py)、抽取、探针脚本
├── data/               # 真源数据（全部进 git，可离线重建全库）
│   ├── seed385.json         # 手工核校种子（权威）
│   ├── tpl_people.jsonl     # 全量扫描生卒索引（85,211 条命中 → 过滤后 49,042 人）
│   ├── full_49k.jsonl.xz    # 30,128 人维基正文（xz 压缩，124.6 MB → 33.1 MB）
│   ├── SHA256SUMS           # 真源校验和
│   ├── title_overrides.json # 维基标题别名映射
│   └── excluded.txt         # 用户排除名单（只打标，不删除数据）
├── out/site/           # 渲染出的静态站点（由代码重建，见 .gitignore）
├── SOURCE-DATA.md      # 真源清单 + 从零重建手册（15 分钟）
├── build.sh            # 一键重建
└── README.md
```

## 真源与灾备

**本仓库自带可重建全库的真源数据**，无需依赖任何外部服务器或二次抓取：

| 真源 | 体积 | 作用 |
|---|---|---|
| `data/tpl_people.jsonl` | 11.8 MB | 生卒索引（全部人物 + 日期，100% 结构化）|
| `data/full_49k.jsonl.xz` | 33.1 MB | 30,128 人维基正文（4,170 万字）|
| `data/seed385.json` | 0.13 MB | 386 人手工核校权威值 |

数据库（162 MB）、静态站点（218 MB）、Obsidian 笔记（252 MB）**均不入库**——它们是纯派生数据，可由上面三个真源在 15 分钟内重建。完整步骤见 **[SOURCE-DATA.md](SOURCE-DATA.md)**。

```bash
git clone https://github.com/lymeyes/obituary-atlas.git && cd obituary-atlas
xz -dk data/full_49k.jsonl.xz
python3 src/jiaheji/build_db.py && python3 src/jiaheji/build_db.py merge
python3 src/jiaheji/render_site.py
```

## 构建流程

```bash
python3 scripts/scan_tpl.py            # 1. 扫描维基 dump，从生卒模板抽取 (姓名, 生, 卒, 字数)
python3 src/jiaheji/build_db.py        # 2. 全量入库（seed 权威覆盖 + 排除名单打标 + 1976–2025 过滤）
python3 src/jiaheji/build_db.py merge  # 3. 合并 NUC 取回的正文（生平/死因/成就）
python3 src/jiaheji/render_site.py     # 4. 渲染静态站点
python3 src/jiaheji/render_notes.py    # 5. 渲染 Obsidian 笔记（可选）
```

## 部署（GitHub Pages）

站点已发布在 **`gh-pages` 分支根目录**（站点文件直接位于分支根，不是 `out/site/` 子目录），GitHub Pages 设为 `gh-pages` + `/(root)` 即可访问 <https://lymeyes.github.io/obituary-atlas/>。

重新发布：

```bash
rsync -a out/site/ /tmp/ghpages_root/
git checkout --orphan gh-pages
git --work-tree=/tmp/ghpages_root --git-dir=.git add -A
git -c commit.gpgsign=false commit -m "site: publish"
git push origin HEAD:gh-pages
```

站点为纯静态、无外部依赖，可直接被 Obsidian 的 iframe 或任意静态托管加载。

## 本地离线版（Obsidian）

`scripts/gen_obsidian_notes.py` 可把数据库全量导出为 Obsidian 笔记（一人一篇，YAML frontmatter 含 `born`/`died`/`category`/`origin`/`cause_cat`/`region`/`tags`/`status`，天然支持 Dataview 检索）：

```bash
python3 scripts/gen_obsidian_notes.py --dry        # 预览将要写入的数量
python3 scripts/gen_obsidian_notes.py --limit 5    # 试写 5 篇核验格式
python3 scripts/gen_obsidian_notes.py              # 全量导出（跳过已存在的笔记）
python3 scripts/gen_obsidian_notes.py --overwrite  # 重写生成器自己的产物（精校笔记仍不碰）
```

手工精校笔记靠正文里的固定标记识别，**永远不会被覆盖**，因此增量重跑与全量重跑都安全。当前导出规模：49,158 篇（其中 30,856 篇含维基全文，约 252 MB），适合只做本地/NAS 同步、不进 git。

字段口径：`category` 为维基分类里首个职业/身份类标签；籍贯类分类（「上海人」「東京市出身人物」）已剥离到 `origin`，奖项/家族/校友类则直接丢弃，避免污染「领域」分组。

## 离线人物浏览器（reader/）

除在线站点和 Obsidian 笔记外，仓库附带一个**零依赖离线浏览器**：双击 `index.html` 即可在浏览器打开，无需服务器、无需 python，专为「在 Obsidian 之外也能随手翻查」设计。

- `reader/build_jiahe.py` —— 数据生成器。读取 `render_notes.py` 产出的 `名人逝世/*.md`，输出到 `~/Obsidian/Bookshelf/阅读器-驾鹤集/`（index.html + app.js + style.css + data/*.js，约 130 MB，**不入库**）。
- `reader/web/` —— 前端模板（三栏：名录 / 筛选 / 详情 + 年代图表视图 + 全文/标签检索）。
- `reader/detect_nonperson.py` —— 非人物条目审计脚本（见下）。

```bash
python3 reader/build_jiahe.py                 # 全量重建阅读器
python3 reader/build_jiahe.py --limit 3000    # 试跑
python3 reader/detect_nonperson.py            # 审计当前 data/，输出非人物清单 TSV
python3 reader/detect_nonperson.py --emit-keep  # 同时生成应剔除的姓名集合（写 excluded.txt 前用）
```

技术范式与诗词阅读器一致：小入口 + 分片懒加载，全部走 `<script>` 注入，`file://` 双击即开。

### 数据质量：非人物条目治理

数据源从维基「XXXX年逝世人物列表」采集链接，列表中混有**事件、列表页、组织、动物、以及重定向错配**条目，被一律当人物收录。全库审计确认 **181 条（0.37%）非人物**：事件/案件 128、动物 25、组织/团体 12、列表/年表 10、时间戳残留 4、非人概念 1、引号怪异名 1。

这些已在 `data/excluded.txt` 中按姓名排除——仅给 `person.excluded` 打标记，**原始数据不删、可逆**（删掉名单行重跑即恢复）。阅读器构建时自动读取该名单过滤。后续补新年份数据时，先跑 `detect_nonperson.py` 审计，再人工确认后追加到 `excluded.txt`。

> 注意：`detect_nonperson.py` 与 `build_jiahe.py` 读取的 `data/` 是**阅读器产物**（`~/Obsidian/Bookshelf/阅读器-驾鹤集/data`），不是仓库 `data/`。需先构建一次阅读器，审计才有数据可读。

## 数据规模

| 项 | 数量 |
|---|---|
| 全量索引（1976–2025 逝世） | **49,157** 人 |
| 含完整维基生平 | **30,128** 人（约 4,170 万字）|
| 仅生卒日期 + 维基链接 | 18,912 人（维基本地库无独立词条）|
| 手工精校种子 | 386 人 |
| 分层（按正文字数） | T1 ≥1.2 万字 / T2 ≥4 千字 / T3 其余 |

> 另有 **181 条非人物条目**（事件/动物/团体/列表/时间戳残留/非人概念）已在 `data/excluded.txt` 标记排除，离线浏览器（`reader/`）不收录，有效 **48,970** 人。详见「离线人物浏览器」一节。

> 正文覆盖率约 61%：对 18,914 个未命中项做过繁体优先双查补漏测试，命中率仅 0.5%，说明这是数据源（本地 zhwiki 镜像）的实际上限，而非抽取逻辑缺陷。

## License

本项目整体采用 **CC BY-SA 4.0**（Attribution-ShareAlike 4.0 International）。

- **数据**（生卒索引、从维基百科抽取的人物条目正文与死因）：源自中文维基百科，依其授权必须署名并以相同方式共享，故统一以 CC BY-SA 4.0 发布。
- **代码**（本仓库的 Python 源码与脚本）：同样以 CC BY-SA 4.0 授权，与数据保持一致、避免合规分歧。

使用本项目内容时，请保留署名并注明出处（中文维基百科），且任何衍生作品须以 CC BY-SA 4.0 共享。
