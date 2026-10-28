# 驾鹤集 (JiaHeJi)

> 自 1976 年以来的逝者图谱：带索引、可查询的生平事迹可视化档案。

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
├── scripts/            # dump 扫描(scan_tpl.py)、抽取、探针脚本
├── data/               # 种子 + 索引 + 排除名单（进 git）
│   ├── seed385.json         # 手工核校种子（权威）
│   ├── tpl_people.jsonl     # 全量扫描生卒索引（49,042 人，1976–2025）
│   ├── title_overrides.json # 维基标题别名映射
│   └── excluded.txt         # 用户排除名单（只打标，不删除数据）
├── out/site/           # 渲染出的静态站点（由代码重建，见 .gitignore）
├── build.sh            # 一键重建
└── README.md
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

将 `out/site/` 发布到 GitHub Pages（单独分支或 `/docs` 目录）即可获得公开可查的「图表」站点。站点为纯静态、无外部依赖，可直接被 Obsidian 的 iframe 或任意静态托管加载。

## 数据规模

- 全量索引：**49,042** 位 1976–2025 逝世人物（全球维基）。
- 分层：T1 顶级（条目 ≥1.2 万字）5,930 / T2 重要 17,783 / T3 一般 25,329。
- 深度档案：seed 386 人 + T1/T2 从维基正文补全生平、成就与死因。

## License

数据源自维基百科，遵循 CC BY-SA 4.0。代码采用 MIT。
