/* 驾鹤集 · 人物档案浏览器
 * 依赖：data/catalog.js（统计）、data/jh.idx.js（索引）、data/jh.sNNN.js（正文分片）
 * 所有数据以经典 <script> 注入加载 —— file:// 下可用，无需服务器、无需 fetch。
 *
 * 只做可靠维度：生卒 / 享年 / 年代 / 领域 / 核实状态 / 全文检索。
 * 刻意不做死因统计（源头 89% 为「未详」），详情页只如实展示原文。
 */
(function () {
  'use strict';

  var I = window.JHIDX, CA = window.JHCA || {};
  var PER = 50;
  var N = I ? I.n : 0;
  var SH = I ? I.shard : 2000;
  var NSH = Math.ceil(N / SH);
  var STCN = ['已核实', '部分核实', '仅维基', '仅种子'];

  var S = {
    q: '', mode: 'meta', decade: '', byA: 0, byB: 0,
    cat: -1, st: -1, sort: 'dy-', page: 0, sel: -1, view: 'list',
    hits: null, hitQ: ''
  };

  var loaded = {}, loading = {}, waiting = {}, cur = null, qTimer = null;

  function $(id) { return document.getElementById(id); }
  function pad(k) { return ('00' + k).slice(-3); }

  /* ---------- 分片按需加载 ---------- */
  function need(k, cb) {
    if (window.JHT && window.JHT[k]) return cb();
    (waiting[k] = waiting[k] || []).push(cb);
    if (loading[k]) return;
    loading[k] = true;
    var s = document.createElement('script');
    s.src = 'data/jh.s' + pad(k) + '.js';
    s.onload = function () {
      loading[k] = false;
      var q = waiting[k] || []; waiting[k] = [];
      for (var i = 0; i < q.length; i++) q[i]();
    };
    s.onerror = function () { loading[k] = false; msg('分片加载失败：' + s.src); };
    document.head.appendChild(s);
  }

  function msg(t, prog) {
    var m = $('mask');
    if (t === null) { m.hidden = true; return; }
    m.hidden = false;
    $('mtext').textContent = t;
    $('mbar').style.width = (prog == null ? 0 : prog * 100) + '%';
  }

  /* ---------- 筛选 ---------- */
  function pass(i) {
    var dy = I.dy[i], by = I.by[i];
    if (S.decade !== '') {
      if (!dy || Math.floor(dy / 10) * 10 !== S.decade) return false;
    }
    if (S.byA && (!by || by < S.byA)) return false;
    if (S.byB && (!by || by > S.byB)) return false;
    if (S.cat >= 0 && I.fld[i] !== S.cat) return false;
    if (S.st >= 0 && I.st[i] !== S.st) return false;
    return true;
  }

  function keyOf(i) {
    switch (S.sort) {
      case 'dy+': return I.dy[i] || 9999;
      case 'dy-': return -(I.dy[i] || 0) || 9999;
      case 'by+': return I.by[i] || 9999;
      case 'by-': return -(I.by[i] || 0) || 9999;
      case 'age+': return I.age[i] || 999;
      case 'age-': return -(I.age[i] || 0) || 999;
      default: return 0;
    }
  }

  function build() {
    var res = [], i;
    if (S.q && S.mode === 'meta') {
      var q = S.q.toLowerCase();
      var tg = I.tg || [];
      for (i = 0; i < N; i++) {
        if (!pass(i)) continue;
        if (I.name[i].toLowerCase().indexOf(q) >= 0 ||
            (tg[i] && tg[i].toLowerCase().indexOf(q) >= 0)) res.push(i);
      }
    } else if (S.hits) {
      for (i = 0; i < S.hits.length; i++) if (pass(S.hits[i])) res.push(S.hits[i]);
    } else {
      for (i = 0; i < N; i++) if (pass(i)) res.push(i);
    }
    if (S.sort === 'name') {
      res.sort(function (a, b) { return I.name[a].localeCompare(I.name[b], 'zh'); });
    } else {
      res.sort(function (a, b) { return keyOf(a) - keyOf(b) || (I.name[a] < I.name[b] ? -1 : 1); });
    }
    cur = res;
    return res;
  }

  /* ---------- 列表 ---------- */
  function renderList() {
    var res = cur || build();
    var total = res.length;
    var pages = Math.max(1, Math.ceil(total / PER));
    if (S.page >= pages) S.page = pages - 1;
    if (S.page < 0) S.page = 0;

    $('listhead').innerHTML = '<b>' + total.toLocaleString() + '</b> 人' +
      '<select id="sort">' +
      [['dy-', '逝世↓'], ['dy+', '逝世↑'], ['by-', '生年↓'], ['by+', '生年↑'],
       ['age-', '享年↓'], ['age+', '享年↑'], ['name', '姓名']]
        .map(function (o) { return '<option value="' + o[0] + '"' + (S.sort === o[0] ? ' selected' : '') + '>' + o[1] + '</option>'; })
        .join('') + '</select>';
    $('sort').onchange = function () { S.sort = this.value; S.page = 0; renderList(); };

    var st = S.page * PER, en = Math.min(st + PER, total), h = [];
    for (var k = st; k < en; k++) {
      var i = res[k];
      var nm = I.name[i];
      var yr = (I.by[i] || '?') + '—' + (I.dy[i] || '?');
      var ag = I.age[i] ? (I.age[i] + '岁') : '';
      h.push('<div class="row' + (i === S.sel ? ' on' : '') + '" data-i="' + i + '">' +
        '<span class="nm">' + esc(nm) + '</span>' +
        (ag ? '<span class="rg">' + ag + '</span>' : '') +
        '<span class="yr">' + yr + '</span></div>');
    }
    $('rows').innerHTML = h.join('') || '<div class="empty" style="padding:30px;text-align:center">无匹配</div>';

    $('pager').innerHTML = total > PER
      ? '<button data-p="-1">‹</button><span>' + (S.page + 1) + ' / ' + pages + '</span><button data-p="1">›</button>'
      : '';
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c];
    });
  }

  /* ---------- 详情 ---------- */
  function open(i) {
    S.sel = i;
    markRows();
    var k = Math.floor(i / SH), off = i % SH;
    need(k, function () {
      var r = (window.JHT[k] || [])[off];
      if (!r) { $('read').innerHTML = '<div class="empty">数据缺失</div>'; return; }
      renderDetail(i, r);
    });
  }

  function markRows() {
    var rows = $('rows').children;
    for (var i = 0; i < rows.length; i++) {
      rows[i].classList.toggle('on', +rows[i].dataset.i === S.sel);
    }
  }

  function renderDetail(i, r) {
    var by = r.by, dy = r.dy, age = r.age;
    var decades = '';
    if (by && dy) decades = Math.floor(by / 10) * 10 + 's — ' + Math.floor(dy / 10) * 10 + 's';
    var wiki = r.wiki || ('https://zh.wikipedia.org/wiki/' + encodeURIComponent(r.n));
    var fld = I.fld[i] >= 0 ? I.fields[I.fld[i]] : '';
    var rawcat = I.cat[i] >= 0 ? I.cats[I.cat[i]] : '';

    var h = [];
    h.push('<h1>' + esc(r.n) + '</h1>');
    h.push('<div class="sub">' + esc(decades || '年代不详') +
      ' · <a href="' + esc(wiki) + '" target="_blank" rel="noopener">维基 ↗</a>' +
      (r.aliases ? ' · 别名 ' + esc(r.aliases) : '') + '</div>');

    h.push('<dl class="kv">');
    h.push('<div><dt>出生</dt><dd>' + (by || '—') + '</dd></div>');
    h.push('<div><dt>逝世</dt><dd>' + (dy || '—') + '</dd></div>');
    h.push('<div><dt>享年</dt><dd>' + (age ? age + ' 岁' : '—') + '</dd></div>');
    h.push('<div><dt>核实</dt><dd>' + (STCN[r.st] || '—') + '</dd></div>');
    if (fld) h.push('<div><dt>领域</dt><dd style="font-size:12.5px">' + esc(fld) + '</dd></div>');
    h.push('</dl>');
    if (rawcat) h.push('<div class="rawcat">原始分类：' + esc(rawcat) + '</div>');

    var bio = (r.bio || '').replace(/\r/g, '');
    if (S.hitQ && bio) {
      var re = new RegExp('(' + S.hitQ.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
      bio = bio.replace(re, '<mark>$1</mark>');
    }
    var paras = bio.split(/\n{1,}/).filter(function (x) { return x.trim(); });
    if (paras.length) {
      h.push('<div class="bio">' + paras.map(function (p) {
        if (/^#{2,4}\s/.test(p)) return '<h4>' + esc(p.replace(/^#{2,4}\s*/, '')) + '</h4>';
        return '<p>' + p.replace(/</g, '&lt;') + '</p>';
      }).join('') + '</div>');
      if (r.tr) h.push('<div class="trunc">正文过长，此处已截断 · 完整内容见 <a href="' + esc(wiki) + '" target="_blank" rel="noopener">维基百科 ↗</a></div>');
    } else {
      h.push('<div class="empty">此条目无生平正文（仅维基摘要）</div>');
    }

    if (r.tags && r.tags.length) {
      h.push('<h4>身份标签</h4><div class="tags">' +
        r.tags.map(function (t) { return '<span data-t="' + esc(t) + '">' + esc(t) + '</span>'; }).join('') + '</div>');
    }
    $('read').innerHTML = h.join('');
    $('read').scrollTop = 0;

    var ts = $('read').querySelectorAll('.tags span');
    for (var j = 0; j < ts.length; j++) {
      ts[j].onclick = function () {
        S.q = this.dataset.t; S.mode = 'meta'; S.hits = null; S.page = 0;
        $('q').value = S.q; $('mode').value = 'meta';
        renderList(); renderChips();
      };
    }
  }

  /* ---------- 筛选侧栏 ---------- */
  function renderChips() {
    // 逝世年代
    var dh = [], dec = CA.decades || [];
    var dcount = {};
    for (var i = 0; i < dec.length; i++) dcount[dec[i][0]] = dec[i][1];
    // 用当前索引重算（更准）
    var live = {};
    for (var j = 0; j < N; j++) if (I.dy[j]) { var dd = Math.floor(I.dy[j] / 10) * 10; live[dd] = (live[dd] || 0) + 1; }
    var keys = Object.keys(live).map(Number).sort(function (a, b) { return a - b; });
    dh.push(fchip('全部', S.decade === '', 'decade', ''));
    keys.forEach(function (d) {
      dh.push(fchip(d + 's', S.decade === d, 'decade', d, live[d]));
    });
    $('decades').innerHTML = dh.join('');

    // 状态
    var sh = [fchip('全部', S.st === -1, 'st', -1)];
    for (var s = 0; s < 4; s++) {
      var c = (CA.st && CA.st[s]) || 0;
      if (!c) continue;
      sh.push(fchip(STCN[s], S.st === s, 'st', s, c));
    }
    $('sts').innerHTML = sh.join('');

    // 领域
    renderCats();

    // 顶部摘要
    var t = [];
    if (S.q) t.push('<span class="chip">关键词 <b>' + esc(S.q) + '</b> ×</span>');
    if (S.decade !== '') t.push('<span class="chip">逝世 <b>' + S.decade + 's</b> ×</span>');
    if (S.byA || S.byB) t.push('<span class="chip">生年 <b>' + (S.byA || '…') + '–' + (S.byB || '…') + '</b> ×</span>');
    if (S.cat >= 0) t.push('<span class="chip">领域 <b>' + esc(I.fields[S.cat]) + '</b> ×</span>');
    if (S.st >= 0) t.push('<span class="chip">状态 <b>' + STCN[S.st] + '</b> ×</span>');
    if (!t.length) t.push('<span class="none">未设筛选 · 全库 ' + N.toLocaleString() + ' 人</span>');
    $('chips').innerHTML = t.join('') +
      '<span class="chip stat">当前 ' + ((cur || []).length).toLocaleString() + ' 人</span>';
  }

  function fchip(label, on, kind, val, cnt) {
    return '<button class="f' + (on ? ' on' : '') + '" data-k="' + kind + '" data-v="' + val + '">' +
      esc(label) + (cnt != null ? '<i>' + cnt + '</i>' : '') + '</button>';
  }

  var catLimit = 30;
  function renderCats() {
    // 领域：已由构建时归并到 ~20 桶（原始维基分类 8,678 种，无法直接筛）
    var flds = I.fields || [], h = [], cnt = {};
    for (var j = 0; j < N; j++) { var c = I.fld[j]; cnt[c] = (cnt[c] || 0) + 1; }
    h.push(fchip('全部', S.cat === -1, 'cat', -1));
    for (var i = 0; i < flds.length; i++) {
      h.push(fchip(flds[i], S.cat === i, 'cat', i, cnt[i] || 0));
    }
    $('cats').innerHTML = h.join('');
    $('ccount').textContent = flds.length + ' 类';
  }

  /* ---------- 全文检索 ---------- */
  function fullSearch(done) {
    var q = S.q.toLowerCase(), hits = [], k = 0, hitsMax = 3000;
    msg('全文检索：准备…', 0);
    (function step() {
      if (k >= NSH) {
        S.hits = hits; S.hitQ = S.q; S.page = 0;
        msg(null); renderList(); renderChips(); done && done();
        return;
      }
      need(k, function () {
        var arr = window.JHT[k] || [];
        for (var j = 0; j < arr.length; j++) {
          var r = arr[j], txt = (r.bio || '') + ' ' + (r.tags ? r.tags.join(' ') : '');
          if (txt.toLowerCase().indexOf(q) >= 0) {
            hits.push(k * SH + j);
            if (hits.length >= hitsMax) { k = NSH; break; }
          }
        }
        k++;
        msg('全文检索 ' + Math.min(k, NSH) + '/' + NSH + ' 片 · 命中 ' + hits.length.toLocaleString(), k / NSH);
        setTimeout(step, 0);
      });
    })();
  }

  /* ---------- 图表 ---------- */
  function drawBars(id, data, color, clickable) {
    var cv = $(id);
    if (!cv) return;
    var dpr = window.devicePixelRatio || 1;
    var w = cv.clientWidth, h = 260;
    cv.width = w * dpr; cv.height = h * dpr;
    cv.style.height = h + 'px';
    var g = cv.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);

    var css = getComputedStyle(document.documentElement);
    var cLine = css.getPropertyValue('--line').trim() || '#ddd';
    var cInk3 = css.getPropertyValue('--ink3').trim() || '#888';
    var cInk = css.getPropertyValue('--ink').trim() || '#000';
    var cAcc = color || css.getPropertyValue('--accent2').trim();

    if (!data.length) return;
    var max = Math.max.apply(null, data.map(function (d) { return d[1]; }));
    var pad = 34, bw = (w - pad - 8) / data.length;
    var cw = Math.max(1, bw - 2);

    g.strokeStyle = cLine; g.lineWidth = 1;
    g.beginPath(); g.moveTo(pad, 6); g.lineTo(pad, h - 20); g.lineTo(w - 6, h - 20); g.stroke();

    data.forEach(function (d, i) {
      var bh = (h - 34) * d[1] / max;
      var x = pad + i * bw, y = h - 20 - bh;
      g.fillStyle = cAcc;
      g.globalAlpha = (S.decade !== '' && d[0] === S.decade) ? 1 : 0.72;
      g.fillRect(x, y, cw, bh);
      g.globalAlpha = 1;
      if (i % Math.ceil(data.length / 12) === 0 || data.length <= 14) {
        g.fillStyle = cInk3; g.font = '10px system-ui'; g.textAlign = 'center';
        g.save(); g.translate(x + cw / 2, h - 8); g.fillText(String(d[0]).replace(/^(\d{2})(\d{2})$/, '$1$2'), 0, 0); g.restore();
      }
      if (bh > 12) {
        g.fillStyle = cInk; g.font = '9px system-ui'; g.textAlign = 'center';
        g.fillText(d[1], x + cw / 2, y - 3);
      }
    });
    if (clickable) {
      cv.onclick = function (e) {
        var r = cv.getBoundingClientRect();
        var i = Math.floor((e.clientX - r.left - pad) / bw);
        if (i < 0 || i >= data.length) return;
        var v = data[i][0];
        S.decade = (S.decade === v) ? '' : v;
        S.page = 0; S.hits = null; S.q = ''; $('q').value = '';
        renderList(); renderChips();
      };
    }
  }

  function drawCharts() {
    // 逝世 / 出生：按十年
    var die = {}, born = {};
    for (var i = 0; i < N; i++) {
      if (I.dy[i]) { var d = Math.floor(I.dy[i] / 10) * 10; die[d] = (die[d] || 0) + 1; }
      if (I.by[i]) { var b = Math.floor(I.by[i] / 10) * 10; born[b] = (born[b] || 0) + 1; }
    }
    var dk = Object.keys(die).map(Number).sort(function (a, b) { return a - b; });
    var bk = Object.keys(born).map(Number).sort(function (a, b) { return a - b; });
    drawBars('c-die', dk.map(function (k) { return [k, die[k]]; }), null, true);
    drawBars('c-born', bk.map(function (k) { return [k, born[k]]; }), null, false);

    // 享年分布
    var bins = new Array(12).fill(0), lo = 0;
    for (var j = 0; j < N; j++) {
      var a = I.age[j];
      if (!a) continue;
      var bi = Math.min(11, Math.floor(a / 10));
      bins[bi]++;
    }
    var bdata = bins.map(function (c, k) { return [k * 10 + '–' + (k * 10 + 9), c]; });
    drawAge(bdata);
    if ($('agehint')) {
      var withAge = 0;
      for (var m = 0; m < N; m++) if (I.age[m]) withAge++;
      $('agehint').textContent = '有效样本 ' + withAge.toLocaleString() + ' 人 · 中位 ' +
        (CA.age_med || '—') + ' 岁 · 缺生/卒年者不计入';
    }
  }

  function drawAge(data) {
    var cv = $('c-age');
    if (!cv) return;
    var dpr = window.devicePixelRatio || 1;
    var w = cv.clientWidth, h = 240;
    cv.width = w * dpr; cv.height = h * dpr;
    cv.style.height = h + 'px';
    var g = cv.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    var css = getComputedStyle(document.documentElement);
    var cLine = css.getPropertyValue('--line').trim() || '#ddd';
    var cInk3 = css.getPropertyValue('--ink3').trim() || '#888';
    var cInk = css.getPropertyValue('--ink').trim() || '#000';
    var cAcc = css.getPropertyValue('--accent2').trim();

    var max = Math.max.apply(null, data.map(function (d) { return d[1]; })) || 1;
    var padL = 8, padB = 22, bw = (w - padL - 8) / data.length, cw = bw - 3;
    g.strokeStyle = cLine;
    g.beginPath(); g.moveTo(padL, 6); g.lineTo(padL, h - padB); g.lineTo(w - 6, h - padB); g.stroke();
    data.forEach(function (d, i) {
      var bh = (h - padB - 12) * d[1] / max;
      var x = padL + i * bw, y = h - padB - bh;
      g.fillStyle = cAcc; g.globalAlpha = 0.75;
      g.fillRect(x, y, cw, bh); g.globalAlpha = 1;
      g.fillStyle = cInk3; g.font = '10px system-ui'; g.textAlign = 'center';
      g.fillText(d[0].split('–')[0], x + cw / 2, h - 7);
      if (bh > 14) { g.fillStyle = cInk; g.font = '9px system-ui'; g.fillText(d[1], x + cw / 2, y - 3); }
    });
  }

  function switchView() {
    S.view = S.view === 'list' ? 'chart' : 'list';
    $('btn-view').textContent = S.view === 'list' ? '列 表' : '年 代';
    $('main').hidden = S.view !== 'list';
    $('charts').hidden = S.view !== 'chart';
    if (S.view === 'chart') drawCharts();
  }

  /* ---------- 事件 ---------- */
  function refresh() {
    S.page = 0;
    build();
    renderList();
    renderChips();
  }

  function boot() {
    if (!I) { document.body.innerHTML = '<p style="padding:40px">索引未加载：data/jh.idx.js 缺失。</p>'; return; }

    $('hint').textContent = N.toLocaleString() + ' 人 · 收录 ' + CA.dy_span[0] + '–' + CA.dy_span[1] +
      ' 年逝世 · 生 ' + CA.by_span[0] + '–' + CA.by_span[1];

    $('q').addEventListener('input', function () {
      var v = this.value.trim();
      clearTimeout(qTimer);
      qTimer = setTimeout(function () {
        S.q = v;
        if (!v) { S.hits = null; S.hitQ = ''; refresh(); return; }
        if (S.mode === 'meta') { S.hits = null; refresh(); }
        else fullSearch();
      }, S.mode === 'meta' ? 120 : 400);
    });

    $('mode').addEventListener('change', function () {
      S.mode = this.value;
      S.hits = null;
      if (S.q) { if (S.mode === 'full') fullSearch(); else refresh(); }
    });

    $('byA').addEventListener('input', function () { S.byA = +this.value || 0; refresh(); });
    $('byB').addEventListener('input', function () { S.byB = +this.value || 0; refresh(); });

    document.addEventListener('click', function (e) {
      var f = e.target.closest && e.target.closest('.f');
      if (f) {
        var k = f.dataset.k, v = f.dataset.v;
        if (v === 'more') { catLimit = 0; renderCats(); return; }
        v = (v === '' ) ? '' : (+v);
        if (k === 'decade') S.decade = (S.decade === v) ? '' : v;
        else if (k === 'st') S.st = (S.st === v) ? -1 : v;
        else if (k === 'cat') S.cat = (S.cat === v) ? -1 : v;
        refresh();
        return;
      }
      var chip = e.target.closest && e.target.closest('.chip');
      if (chip && chip.parentNode.id === 'chips' && !chip.classList.contains('stat')) {
        var t = chip.textContent;
        if (t.indexOf('关键词') >= 0) { S.q = ''; S.hits = null; $('q').value = ''; }
        else if (t.indexOf('逝世') >= 0) S.decade = '';
        else if (t.indexOf('生年') >= 0) { S.byA = S.byB = 0; $('byA').value = ''; $('byB').value = ''; }
        else if (t.indexOf('领域') >= 0) S.cat = -1;
        else if (t.indexOf('状态') >= 0) S.st = -1;
        refresh();
        return;
      }
      var row = e.target.closest && e.target.closest('.row');
      if (row) { open(+row.dataset.i); return; }
      var pg = e.target.closest && e.target.closest('#pager button');
      if (pg) { S.page += +pg.dataset.p; renderList(); $('rows').scrollTop = 0; }
    });

    $('btn-view').onclick = switchView;
    $('btn-random').onclick = function () {
      var res = cur || build();
      if (!res.length) return;
      var i = res[Math.floor(Math.random() * res.length)];
      S.sel = i; S.page = Math.floor(res.indexOf(i) / PER);
      renderList(); open(i);
    };

    document.addEventListener('keydown', function (e) {
      var tag = (e.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'select' || tag === 'textarea') {
        if (e.key === 'Escape') e.target.blur();
        return;
      }
      if (e.key === '/') { e.preventDefault(); $('q').focus(); }
      else if (e.key === 'r') $('btn-random').click();
      else if (e.key === 'v') switchView();
      else if (e.key === 'ArrowRight') { if (S.sel >= 0) open(S.sel + 1); }
      else if (e.key === 'ArrowLeft') { if (S.sel > 0) open(S.sel - 1); }
    });

    var rt;
    window.addEventListener('resize', function () {
      if (S.view !== 'chart') return;
      clearTimeout(rt);
      rt = setTimeout(drawCharts, 180);
    });

    refresh();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
