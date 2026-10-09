// 精靈王石器資料庫：純靜態前端（資料由 tools/web/build.py 產生）
'use strict';

const TYPES = {
  item: '道具', pet: '寵物 / 怪物', npc: 'NPC', map: '地圖', skill: '技能', buff: '狀態', task: '任務',
};
const ORDER = Object.keys(TYPES);
const MAX_RESULTS = 300;

const $app = document.getElementById('app');
const $q = document.getElementById('q');
let INDEX = null;          // [類型, ID, 繁中, 簡中, 韓文, 附註]
let NAMES = new Map();     // "類型:ID" → 名稱
let DOCS = null;
const DETAIL = {};         // 類型 → Promise<{ID: 詳情}>
let MAPS = null;           // Promise<Map<ID, {w,h,data}>>

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const getJSON = (u) => fetch(u).then((r) => { if (!r.ok) throw new Error(u + ' ' + r.status); return r.json(); });

async function loadIndex() {
  if (INDEX) return;
  const [idx, docs] = await Promise.all([getJSON('data/index.json'), getJSON('data/docs.json')]);
  INDEX = idx.map((r) => ({ t: r[0], id: r[1], n: r[2], c: r[3], k: r[4], sub: r[5], key: (r[2] + '\u0001' + r[3] + '\u0001' + r[4]).toLowerCase() }));
  for (const r of INDEX) NAMES.set(r.t + ':' + r.id, r.n);
  DOCS = docs;
  document.getElementById('ver').textContent = docs.version ? ` 資料版本 ${docs.version}，匯出於 ${docs.built}。` : '';
}
const detail = (t) => (DETAIL[t] ||= getJSON(`data/${t}.json`));

// ---------------- 路由 ----------------
function parseHash() {
  const h = decodeURIComponent(location.hash.replace(/^#\/?/, ''));
  const [path, qs] = h.split('?');
  return { path, params: new URLSearchParams(qs || '') };
}
window.addEventListener('hashchange', route);
async function route() {
  const { path, params } = parseHash();
  try {
    await loadIndex();
    if (path === '' || path === 'search') return renderSearch(params.get('q') || '', params.get('t') || '');
    if (path === 'docs') return renderDocs();
    if (path.startsWith('doc/')) return renderDoc(path.slice(4), params.get('f') || '');
    const m = path.match(/^(\w+)\/(-?\d+)$/);
    if (m && TYPES[m[1]]) return renderDetail(m[1], +m[2], params);
    $app.innerHTML = '<p>找不到這個頁面。<a href="#/">回首頁</a></p>';
  } catch (e) {
    $app.innerHTML = `<p>載入失敗：${esc(e.message)}</p>`;
    console.error(e);
  }
}

// ---------------- 搜尋 ----------------
let typing;
$q.addEventListener('input', () => {
  clearTimeout(typing);
  typing = setTimeout(() => {
    const q = $q.value.trim();
    const { path, params } = parseHash();
    const t = path === '' || path === 'search' ? params.get('t') || '' : '';
    const h = '#/?q=' + encodeURIComponent(q) + (t ? '&t=' + t : '');
    if (path === '' || path === 'search') { history.replaceState(null, '', h); route(); } else location.hash = h;
  }, 150);
});
document.getElementById('qform').addEventListener('submit', (e) => { e.preventDefault(); $q.blur(); });

function search(q) {
  const k = q.toLowerCase();
  const isNum = /^-?\d+$/.test(q);
  const out = [];
  for (const r of INDEX) {
    let s;
    if (isNum && String(r.id) === q) s = 0;
    else {
      const i = r.key.indexOf(k);
      if (i < 0) continue;
      const names = r.key.split('\u0001');
      s = names.includes(k) ? 1 : names.some((n) => n.startsWith(k)) ? 2 : 3;
    }
    out.push([s, r]);
  }
  out.sort((a, b) => a[0] - b[0] || ORDER.indexOf(a[1].t) - ORDER.indexOf(b[1].t) || a[1].n.length - b[1].n.length || a[1].id - b[1].id);
  return out.map((x) => x[1]);
}

function renderSearch(q, t) {
  if (document.activeElement !== $q) $q.value = q;
  document.title = q ? `${q} - 精靈王石器資料庫` : '精靈王石器資料庫';
  if (!q) return renderHome();
  const all = search(q);
  const cnt = {};
  for (const r of all) cnt[r.t] = (cnt[r.t] || 0) + 1;
  const list = t ? all.filter((r) => r.t === t) : all;
  const chip = (key, label, n) => `<a class="chip${t === key ? ' on' : ''}" href="#/?q=${encodeURIComponent(q)}${key ? '&t=' + key : ''}">${label}<span class="n">${n}</span></a>`;
  let h = '<div class="chips">' + chip('', '全部', all.length) + ORDER.filter((k) => cnt[k]).map((k) => chip(k, TYPES[k], cnt[k])).join('') + '</div>';
  if (!list.length) h += `<p class="muted">找不到「${esc(q)}」。可以試試簡體、韓文或 ID。</p>`;
  else {
    h += '<ul class="results">' + list.slice(0, MAX_RESULTS).map((r) =>
      `<li><a href="#/${r.t}/${r.id}"><span class="tag">${TYPES[r.t]}</span><span class="name">${hl(r.n, q)}</span>` +
      (r.c ? `<span class="sub">${hl(r.c, q)}</span>` : '') + (r.k ? `<span class="sub">${hl(r.k, q)}</span>` : '') +
      (r.sub ? `<span class="sub">· ${esc(r.sub)}</span>` : '') + `<span class="id">ID ${r.id}</span></a></li>`).join('') + '</ul>';
    if (list.length > MAX_RESULTS) h += `<p class="muted">只顯示前 ${MAX_RESULTS} 筆（共 ${list.length} 筆），請輸入更精確的關鍵字或選分類。</p>`;
  }
  $app.innerHTML = h;
}
function hl(s, q) {
  const i = s.toLowerCase().indexOf(q.toLowerCase());
  return i < 0 ? esc(s) : esc(s.slice(0, i)) + '<mark>' + esc(s.slice(i, i + q.length)) + '</mark>' + esc(s.slice(i + q.length));
}

function renderHome() {
  const cnt = {};
  for (const r of INDEX) cnt[r.t] = (cnt[r.t] || 0) + 1;
  const ex = ['烏力', '小的爪', '老村長', '薩姆吉爾', '우리', '初入石器'];
  const cats = DOCS.docs.filter((d) => /README\.md$/.test(d[0]));
  $app.innerHTML = `<section class="home">
    <h1>精靈王石器（PrimalSA）資料庫</h1>
    <p class="muted">在上方輸入名稱或 ID 搜尋。資料共 ${ORDER.map((k) => `${TYPES[k]} ${cnt[k] || 0}`).join('、')} 筆。</p>
    <p>試試：${ex.map((e) => `<a href="#/?q=${encodeURIComponent(e)}">${esc(e)}</a>`).join('　')}</p>
    <h2 class="muted" style="font-size:16px;margin-top:24px">文件分類</h2>
    <div class="grid2">${cats.map((d) => `<a href="#/doc/${d[0]}"><b>${esc(d[1])}</b><span>${esc(d[2] || d[0])}</span></a>`).join('')}
      <a href="#/docs"><b>全部文件</b><span>${DOCS.docs.length} 份</span></a></div>
  </section>`;
  setTimeout(() => $q.focus(), 0);
}

// ---------------- 詳情 ----------------
function seg(x) {
  if (typeof x === 'string') return esc(x);
  if (x[0] === 'pos') {
    const [, m, px, py] = x;
    const name = NAMES.get('map:' + m) || '地圖' + m;
    return `<a href="#/map/${m}?x=${px}&y=${py}">${esc(name)}(${m}) ${px},${py}</a>`;
  }
  if (x[0] === 'doc') return `<a href="#/doc/${x[1]}">${esc(x[2])}</a>`;
  const [t, id] = x;
  return `<a href="#/${t}/${id}">${esc(NAMES.get(t + ':' + id) || '#' + id)}</a>`;
}
const line = (l) => l.map(seg).join('');

async function renderDetail(t, id, params) {
  $app.innerHTML = '<p class="muted">載入中…</p>';
  const d = (await detail(t))[id];
  if (!d) { $app.innerHTML = `<p>找不到 ${TYPES[t]} ID ${id}。</p>`; return; }
  document.title = `${d.n} - ${TYPES[t]} - 精靈王石器資料庫`;
  let h = `<article class="card"><span class="tag">${TYPES[t]}</span> <span class="muted">ID ${id}</span>
    <h1>${esc(d.n || '#' + id)}</h1>`;
  const alt = [d.c && d.c !== d.n ? '簡中：' + d.c : '', d.k ? '韓文：' + d.k : ''].filter(Boolean);
  if (alt.length) h += `<div class="alt">${esc(alt.join('　'))}</div>`;
  if (d.f) h += '<dl class="fields">' + d.f.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${line(v)}</dd>`).join('') + '</dl>';
  if (d.d) h += `<p class="desc">${esc(d.d)}</p>`;
  h += '</article>';
  if (t === 'map') h += mapCard(id, d);
  for (const [title, lines] of d.s || []) {
    h += `<section class="card"><h2>${esc(title)}<span class="muted" style="font-weight:400"> ${lines.length}</span></h2>
      <ul class="lines">${lines.map((l) => `<li>${line(l)}</li>`).join('')}</ul></section>`;
  }
  $app.innerHTML = h;
  window.scrollTo(0, 0);
  if (t === 'map' && d.g) drawMap(id, d, +params.get('x'), +params.get('y'), params.has('x'));
}

// ---------------- 地圖通行格 ----------------
function mapCard(id, d) {
  if (!d.g) return '';
  return `<section class="card"><h2>通行格</h2>
    <div class="legend"><span><i style="background:var(--c1)"></i>可走</span><span><i style="background:var(--c2)"></i>水 / 懸崖</span>
      <span><i style="background:var(--c3)"></i>障礙</span><span><i style="background:#e5484d"></i>NPC</span><span><i style="background:#30a46c"></i>出口</span>
      <span><i style="background:#f5a623"></i>指定座標</span>
      <button class="zoom" data-z="-1">縮小</button><button class="zoom" data-z="1">放大</button></div>
    <div class="maptip muted" id="maptip">滑鼠移到地圖上看座標；點 NPC / 出口可跳轉。以俯視方格繪製（遊戲畫面是斜角，x 往右上、y 往右下）。</div>
    <div class="mapbox" id="mapbox"><canvas id="mapcv"></canvas></div></section>`;
}

function loadMaps() {
  return (MAPS ||= fetch('data/maps.bin').then((r) => r.arrayBuffer()).then((buf) => {
    const dv = new DataView(buf);
    const magic = new TextDecoder().decode(new Uint8Array(buf, 0, 7));
    if (magic !== 'PSAMAP1') throw new Error('maps.bin 格式不對');
    const n = dv.getInt32(7, true);
    const out = new Map();
    let p = 11;
    for (let i = 0; i < n; i++) {
      const id = dv.getInt32(p, true), w = dv.getUint16(p + 4, true), h = dv.getUint16(p + 6, true), len = dv.getInt32(p + 8, true);
      p += 12;
      out.set(id, { w, h, raw: new Uint8Array(buf, p, len) });
      p += len;
    }
    return out;
  }));
}
async function inflate(raw) {
  const s = new Blob([raw]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
  return new Uint8Array(await new Response(s).arrayBuffer());
}

async function drawMap(id, d, tx, ty, hasTarget) {
  const m = (await loadMaps()).get(id);
  const cv = document.getElementById('mapcv');
  if (!m || !cv) return;
  const cells = m.cells || (m.cells = await inflate(m.raw));
  const { w, h } = m;
  const box = document.getElementById('mapbox');
  let z = Math.max(1, Math.min(20, Math.floor((box.clientWidth - 2) / w), Math.floor(600 / h) || 1));
  const css = getComputedStyle(document.documentElement);
  const dark = matchMedia('(prefers-color-scheme: dark)').matches;
  const col = dark ? ['', '#5b5a52', '#2b4a6b', '#26262b'] : ['', '#e9e3d3', '#a9c6e3', '#6d685e'];
  box.style.setProperty('--c1', col[1]); box.style.setProperty('--c2', col[2]); box.style.setProperty('--c3', col[3]);
  document.querySelector('.legend').style.cssText = `--c1:${col[1]};--c2:${col[2]};--c3:${col[3]}`;
  const marks = new Map();
  for (const [x, y, nid] of d.g.npc) marks.set(x + ',' + y, ['npc', nid]);
  for (const [x, y, tm] of d.g.exit) marks.set(x + ',' + y, ['map', tm]);

  function paint() {
    cv.width = w * z; cv.height = h * z;
    const g = cv.getContext('2d');
    const img = g.createImageData(w, h);
    const rgb = col.map((c) => c && [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)]);
    for (let i = 0; i < w * h; i++) {
      const c = rgb[cells[i]];
      if (!c) continue;
      img.data.set([c[0], c[1], c[2], 255], i * 4);
    }
    // 先畫 1:1 再放大（像素風）
    const tmp = document.createElement('canvas'); tmp.width = w; tmp.height = h;
    tmp.getContext('2d').putImageData(img, 0, 0);
    g.imageSmoothingEnabled = false;
    g.drawImage(tmp, 0, 0, w * z, h * z);
    const r = Math.max(2, z * 0.9);
    const dot = (x, y, color, rr = r) => { g.fillStyle = color; g.beginPath(); g.arc(x * z + z / 2, y * z + z / 2, rr, 0, 7); g.fill(); };
    for (const [x, y] of d.g.exit) dot(x, y, '#30a46c');
    for (const [x, y] of d.g.npc) dot(x, y, '#e5484d');
    if (hasTarget) { dot(tx, ty, '#f5a623', r * 1.6); g.strokeStyle = '#f5a623'; g.lineWidth = 2; g.strokeRect((tx - 3) * z, (ty - 3) * z, 7 * z, 7 * z); }
  }
  paint();
  if (hasTarget) { box.scrollLeft = tx * z - box.clientWidth / 2; box.scrollTop = ty * z - box.clientHeight / 2; }

  const tip = document.getElementById('maptip');
  const near = (ev) => {
    const b = cv.getBoundingClientRect();
    const x = Math.floor((ev.clientX - b.left) / z), y = Math.floor((ev.clientY - b.top) / z);
    let hit = null;
    for (let dy = -1; dy <= 1 && !hit; dy++) for (let dx = -1; dx <= 1 && !hit; dx++) hit = marks.get(x + dx + ',' + (y + dy)) || null;
    return { x, y, hit };
  };
  const KIND = ['無地面', '可走', '水 / 懸崖', '障礙'];
  cv.onmousemove = (ev) => {
    const { x, y, hit } = near(ev);
    if (x < 0 || y < 0 || x >= w || y >= h) return;
    let s = `(${x}, ${y}) ${KIND[cells[y * w + x]]}`;
    if (hit) s += hit[0] === 'npc' ? `　NPC：${NAMES.get('npc:' + hit[1]) || hit[1]}` : `　出口 → ${NAMES.get('map:' + hit[1]) || hit[1]}`;
    tip.textContent = s;
    cv.style.cursor = hit ? 'pointer' : 'crosshair';
  };
  cv.onclick = (ev) => { const { hit } = near(ev); if (hit) location.hash = `#/${hit[0]}/${hit[1]}`; };
  document.querySelectorAll('.zoom').forEach((b) => b.onclick = () => {
    z = Math.max(1, Math.min(24, z + (+b.dataset.z) * (z >= 4 ? 2 : 1)));
    paint();
  });
}

// ---------------- 文件 ----------------
function renderDocs() {
  document.title = '全部文件 - 精靈王石器資料庫';
  const groups = {};
  for (const d of DOCS.docs) (groups[d[0].includes('/') ? d[0].split('/')[0] : ''] ||= []).push(d);
  let h = '<h1 style="font-size:22px">全部文件</h1><p class="muted">由 knowledge/ 自動產生的分類文件；大型表格頁可以用頁內篩選。</p>';
  for (const [g, list] of Object.entries(groups)) {
    h += `<h2 style="font-size:16px;margin-top:20px">${esc(g || '索引')}</h2><div class="grid2">` +
      list.map((d) => `<a href="#/doc/${d[0]}"><b>${esc(d[1])}</b><span>${esc(d[0])}</span></a>`).join('') + '</div>';
  }
  $app.innerHTML = h;
}

const DOC_CACHE = {};
async function renderDoc(path, f) {
  const meta = DOCS.docs.find((d) => d[0] === path);
  if (!meta) { $app.innerHTML = '<p>找不到這份文件。<a href="#/docs">全部文件</a></p>'; return; }
  document.title = `${meta[1]} - 精靈王石器資料庫`;
  $app.innerHTML = '<p class="muted">載入中…</p>';
  const md = (DOC_CACHE[path] ||= await fetch('kb/' + path).then((r) => r.text()));
  const html = window.marked ? marked.parse(md, { gfm: true }) : `<pre>${esc(md)}</pre>`;
  $app.innerHTML = `<div class="doctools"><a href="#/docs">← 全部文件</a><span class="muted">${esc(path)}</span>
    <input id="docf" type="search" placeholder="篩選本頁表格列 / 段落" value="${esc(f)}"><span id="docn" class="muted"></span></div>
    <article class="doc" id="doc">${html}</article>`;
  const base = path.includes('/') ? path.slice(0, path.lastIndexOf('/') + 1) : '';
  for (const a of document.querySelectorAll('#doc a[href]')) {
    const href = a.getAttribute('href');
    if (/^(https?:|#|mailto:)/.test(href)) continue;
    let target = resolvePath(base, href.split('#')[0]);
    if (target.endsWith('/')) target += 'README.md';
    if (DOCS.docs.some((d) => d[0] === target)) a.setAttribute('href', '#/doc/' + target);
    else { a.removeAttribute('href'); a.title = '這份檔案沒有放上網站'; }
  }
  linkIdColumn(path);
  const inp = document.getElementById('docf');
  let tm;
  inp.addEventListener('input', () => { clearTimeout(tm); tm = setTimeout(() => filterDoc(inp.value.trim()), 120); });
  window.scrollTo(0, 0);
  if (f) filterDoc(f);
}
// 表格第一欄是 ID 的文件：把 ID 變成詳情頁連結
const DOC_ID_TYPE = [
  [/^items\/(?!suits|README)/, 'item'], [/^pets\/(type-|enemies-)/, 'pet'], [/^skills\/battle-skills/, 'skill'],
  [/^skills\/status-effects/, 'buff'], [/^world\/maps/, 'map'],
];
function linkIdColumn(path) {
  const t = (DOC_ID_TYPE.find(([re]) => re.test(path)) || [])[1];
  if (!t) return;
  for (const table of document.querySelectorAll('#doc table')) {
    if (table.querySelector('th')?.textContent.trim() !== 'ID') continue;
    for (const td of table.querySelectorAll('tbody tr > td:first-child')) {
      const id = td.textContent.trim();
      if (NAMES.has(t + ':' + id)) td.innerHTML = `<a href="#/${t}/${id}">${id}</a>`;
    }
  }
}
function resolvePath(base, rel) {
  const parts = (base + rel).split('/');
  const out = [];
  for (const p of parts) { if (p === '..') out.pop(); else if (p !== '.') out.push(p); }
  return out.join('/');
}
function filterDoc(f) {
  const k = f.toLowerCase();
  let shown = 0, total = 0;
  for (const table of document.querySelectorAll('#doc table')) {
    let n = 0;
    for (const tr of table.querySelectorAll('tbody tr')) {
      total++;
      const ok = !k || tr.textContent.toLowerCase().includes(k);
      tr.style.display = ok ? '' : 'none';
      if (ok) n++;
    }
    shown += n;
    // 整張表都沒有符合的列：連同表格前面的標題一起藏起來
    const hide = k && !n;
    table.style.display = hide ? 'none' : '';
    const prev = table.previousElementSibling;
    if (prev && /^H[2-6]$/.test(prev.tagName)) prev.style.display = hide ? 'none' : '';
  }
  for (const el of document.querySelectorAll('#doc > p, #doc > ul > li, #doc > ol > li')) {
    el.style.display = !k || el.textContent.toLowerCase().includes(k) ? '' : 'none';
  }
  document.getElementById('docn').textContent = k && total ? `${shown} / ${total} 列` : '';
}

route();
