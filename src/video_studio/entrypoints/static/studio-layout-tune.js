/* 用途：提供參考線視覺檢查（Cmd/Ctrl+Shift+G）與 8px 網格拖曳微調模式，支援 per-viewport 記憶與複製 AI 規格（對齊 notebooklm-batch-studio）。 */

let _layoutGuidesHooked = false;
let _tuneActive = false;
let _tuneDragState = null;

/**
 * 判斷目前視窗屬於 desktop、tablet 或 mobile 斷點。
 * @returns {'mobile'|'tablet'|'desktop'} 視口分類名稱。
 */
function guideViewportBucket() {
  const w = window.innerWidth;
  if (w <= 760) return 'mobile';
  if (w <= 1180) return 'tablet';
  return 'desktop';
}

/**
 * 取得元素的簡短識別標籤。
 * @param {HTMLElement} el 目標 DOM 元素。
 * @returns {string} 簡短標籤文字。
 */
function guideLabelFor(el) {
  const tag = el.tagName.toLowerCase();
  if (el.id) return `${tag}#${el.id}`;
  const cls = [...el.classList].filter(c => !['on', 'tune-box'].includes(c)).slice(0, 2);
  return cls.length ? `${tag}.${cls.join('.')}` : tag;
}

/**
 * 建立元素的完整 DOM 路徑與尺寸摘要字串。
 * @param {HTMLElement} el 目標 DOM 元素。
 * @returns {string} 含視口與尺寸的完整路徑字串。
 */
function guideFullPathFor(el) {
  const parts = [];
  let cur = el;
  while (cur && cur.nodeType === 1 && parts.length < 5) {
    parts.unshift(guideLabelFor(cur));
    if (cur.id === 'app') break;
    cur = cur.parentElement;
  }
  const r = el.getBoundingClientRect();
  return `[${guideViewportBucket()} ${window.innerWidth}px] ${parts.join(' > ')} (${Math.round(r.width)}x${Math.round(r.height)})`;
}

/**
 * 檢查元素是否可見且位於目前可視範圍內。
 * @param {HTMLElement} el 目標 DOM 元素。
 * @returns {boolean} 是否應繪製參考線。
 */
function _isGuideVisible(el) {
  const st = getComputedStyle(el);
  if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) < 0.05) return false;
  const r = el.getBoundingClientRect();
  return r.width > 6 && r.height > 6 && r.bottom > 0 && r.top < window.innerHeight && r.right > 0 && r.left < window.innerWidth;
}

/**
 * 重新繪製所有可見區塊與互動元件的參考線框與標籤。
 * @returns {void}
 */
function renderLayoutGuides() {
  const app = document.getElementById('app');
  if (!app || !app.classList.contains('layout-guides')) return;
  let layer = document.getElementById('layoutGuideLayer');
  if (!layer) {
    layer = document.createElement('div');
    layer.id = 'layoutGuideLayer';
    layer.className = 'layout-guide-layer';
    app.appendChild(layer);
  }
  const sel = '.dock,.topbar,.stepper,.card,.qa-drawer,button,select,input,textarea,.dock-btn';
  const els = [...document.querySelectorAll(sel)].filter(_isGuideVisible);
  const colors = { button: '#db2777', select: '#9333ea', input: '#9333ea', textarea: '#0284c7', aside: '#2563eb', header: '#e11d48' };
  const placed = [];
  layer.innerHTML = els.map(el => {
    const r = el.getBoundingClientRect();
    const c = colors[el.tagName.toLowerCase()] || '#0f766e';
    let ty = 0;
    while (placed.some(p => Math.abs(p.x - r.left) < 110 && Math.abs(p.y - (r.top + ty)) < 14)) ty += 14;
    placed.push({ x: r.left, y: r.top + ty });
    const label = guideLabelFor(el);
    const fullPath = guideFullPathFor(el);
    return `<div class="lg-box" data-full-path="${esc(fullPath)}" style="left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px;border-color:${c}">
      <span class="lg-tag" style="background:${c};top:${ty}px">${esc(label)}</span></div>`;
  }).join('');
}

/**
 * 依滑鼠座標高亮對應的參考線外框。
 * @param {number} x 滑鼠 X 座標。
 * @param {number} y 滑鼠 Y 座標。
 * @returns {void}
 */
function _highlightGuideAt(x, y) {
  const layer = document.getElementById('layoutGuideLayer');
  if (!layer) return;
  layer.querySelectorAll('.lg-box').forEach(box => {
    const r = box.getBoundingClientRect();
    const hit = x >= r.left && x <= r.right && y >= r.top && y <= r.bottom;
    box.classList.toggle('hit', hit);
  });
}

/**
 * 在參考線開啟時點擊元件即可複製其完整選擇器路徑。
 * @param {MouseEvent} e 滑鼠點擊事件。
 * @returns {void}
 */
function _copyGuideLabelAt(e) {
  const app = document.getElementById('app');
  if (!app || !app.classList.contains('layout-guides')) return;
  if (e.target.closest('#layoutGuideHud, .tune-bar, .tune-handle')) return;
  const boxes = [...document.querySelectorAll('#layoutGuideLayer .lg-box')].filter(b => {
    const r = b.getBoundingClientRect();
    return e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
  });
  if (!boxes.length) return;
  boxes.sort((a, b) => (a.offsetWidth * a.offsetHeight) - (b.offsetWidth * b.offsetHeight));
  const path = boxes[0].dataset.fullPath || '';
  if (navigator.clipboard?.writeText && path) navigator.clipboard.writeText(path).catch(() => {});
  if (typeof showToast === 'function') showToast(`已複製路徑：${path}`, 'success', 2400);
}

/**
 * 開關視覺參考線檢查模式（快捷鍵 Cmd/Ctrl+Shift+G）。
 * @returns {void}
 */
function toggleLayoutGuides() {
  const app = document.getElementById('app');
  if (!app) return;
  const on = app.classList.toggle('layout-guides');
  document.getElementById('btnLayoutGuides')?.classList.toggle('on', on);
  document.getElementById('btnLayoutGuidesTop')?.classList.toggle('on', on);
  let hud = document.getElementById('layoutGuideHud');
  if (!hud) {
    hud = document.createElement('div');
    hud.id = 'layoutGuideHud';
    hud.className = 'layout-guide-hud';
    app.appendChild(hud);
  }
  const vp = guideViewportBucket();
  hud.innerHTML = `<span>參考線｜點擊框線複製路徑（${esc(vp)} ${window.innerWidth}×${window.innerHeight}）</span>
    <button type="button" class="btn btn-ghost btn-sm" id="btnTuneMode" onclick="toggleLayoutTuneMode()">拖曳微調</button>
    <button type="button" class="btn btn-ghost btn-sm" onclick="toggleLayoutGuides()">關閉</button>`;
  if (!_layoutGuidesHooked) {
    _layoutGuidesHooked = true;
    window.addEventListener('resize', () => requestAnimationFrame(renderLayoutGuides));
    document.addEventListener('scroll', () => requestAnimationFrame(renderLayoutGuides), true);
    document.addEventListener('click', _copyGuideLabelAt, true);
    document.addEventListener('click', () => setTimeout(renderLayoutGuides, 80), true);
    document.addEventListener('mousemove', e => _highlightGuideAt(e.clientX, e.clientY));
  }
  if (on) renderLayoutGuides();
}

/**
 * 取得目前視口對應的版面微調 localStorage 鍵名。
 * @returns {string} localStorage 鍵名。
 */
function _tuneStorageKey() {
  return `vs.layoutTune.${guideViewportBucket()}`;
}

/**
 * 讀取已儲存的版面尺寸微調映射表。
 * @returns {Record<string, {width: number, height: number}>} 選擇器對應寬高的物件。
 */
function _loadTuneMap() {
  try {
    return JSON.parse(localStorage.getItem(_tuneStorageKey()) || '{}') || {};
  } catch {
    return {};
  }
}

/**
 * 寫入目前視口的版面尺寸微調映射表。
 * @param {Record<string, {width: number, height: number}>} map 選擇器對應寬高的物件。
 * @returns {void}
 */
function _saveTuneMap(map) {
  localStorage.setItem(_tuneStorageKey(), JSON.stringify(map));
}

/**
 * 套用目前視口已儲存的版面寬高設定。
 * @returns {void}
 */
function applySavedLayoutTunes() {
  const map = _loadTuneMap();
  Object.entries(map).forEach(([sel, dims]) => {
    const el = document.querySelector(sel);
    if (!el || !dims) return;
    if (dims.width) el.style.width = `${dims.width}px`;
    if (dims.height) el.style.minHeight = `${dims.height}px`;
  });
}

/**
 * 開關卡片與面板右下角 8px 網格拖曳微調模式。
 * @returns {void}
 */
function toggleLayoutTuneMode() {
  _tuneActive = !_tuneActive;
  document.getElementById('btnTuneMode')?.classList.toggle('on', _tuneActive);
  document.querySelectorAll('.tune-box').forEach(el => el.classList.remove('tune-box'));
  document.querySelectorAll('.tune-handle, .tune-bar').forEach(el => el.remove());
  if (!_tuneActive) {
    if (typeof showToast === 'function') showToast('已關閉版面拖曳微調模式', 'info', 1800);
    return;
  }
  _mountTuneHandles();
  _mountTuneActionBar();
  if (typeof showToast === 'function') showToast('已開啟拖曳微調：拖拉面板右下角即可調整大小（8px 網格吸附）', 'info', 3000);
}

/**
 * 為可見的含 ID 卡片掛載右下角拖曳控制點。
 * @returns {void}
 */
function _mountTuneHandles() {
  document.querySelectorAll('.card[id]').forEach(el => {
    if (!el.id || !el.offsetParent) return;
    el.classList.add('tune-box');
    const handle = document.createElement('button');
    handle.type = 'button';
    handle.className = 'tune-handle';
    handle.title = '拖曳調整寬度與高度（8px 網格）';
    handle.setAttribute('aria-label', `調整 ${el.id} 尺寸`);
    handle.onpointerdown = e => _startTuneDrag(e, el);
    el.appendChild(handle);
  });
}

/**
 * 掛載底部浮動微調操作列。
 * @returns {void}
 */
function _mountTuneActionBar() {
  const bar = document.createElement('div');
  bar.className = 'tune-bar';
  bar.innerHTML = `<span class="muted">拖曳微調中（${guideViewportBucket()}）</span>
    <button type="button" class="btn btn-soft btn-sm" onclick="copyLayoutTuneDiff()">複製微調規格</button>
    <button type="button" class="btn btn-ghost btn-sm" onclick="resetLayoutTunes()">還原預設</button>
    <button type="button" class="btn btn-sm" onclick="toggleLayoutTuneMode()">完成</button>`;
  document.body.appendChild(bar);
}

/**
 * 開始拖曳調整目標容器大小。
 * @param {PointerEvent} e 指標按下事件。
 * @param {HTMLElement} el 目標容器元素。
 * @returns {void}
 */
function _startTuneDrag(e, el) {
  e.preventDefault();
  e.stopPropagation();
  const rect = el.getBoundingClientRect();
  _tuneDragState = { el, startX: e.clientX, startY: e.clientY, startW: rect.width, startH: rect.height };
  window.addEventListener('pointermove', _onTuneDragMove);
  window.addEventListener('pointerup', _endTuneDrag, { once: true });
}

/**
 * 拖曳移動時依 8px 網格即時更新容器尺寸。
 * @param {PointerEvent} e 指標移動事件。
 * @returns {void}
 */
function _onTuneDragMove(e) {
  if (!_tuneDragState) return;
  const { el, startX, startY, startW, startH } = _tuneDragState;
  const snap = v => Math.max(160, Math.round(v / 8) * 8);
  el.style.width = `${snap(startW + (e.clientX - startX))}px`;
  el.style.minHeight = `${snap(startH + (e.clientY - startY))}px`;
}

/**
 * 結束拖曳並將新尺寸寫入 localStorage。
 * @returns {void}
 */
function _endTuneDrag() {
  window.removeEventListener('pointermove', _onTuneDragMove);
  if (!_tuneDragState) return;
  const { el } = _tuneDragState;
  const r = el.getBoundingClientRect();
  const map = _loadTuneMap();
  map[`#${el.id}`] = { width: Math.round(r.width), height: Math.round(r.height) };
  _saveTuneMap(map);
  _tuneDragState = null;
  renderLayoutGuides();
}

/**
 * 將已調整的版面尺寸規格複製到剪貼簿，方便貼給 AI 進行 CSS 優化。
 * @returns {void}
 */
function copyLayoutTuneDiff() {
  const map = _loadTuneMap();
  const entries = Object.entries(map);
  if (!entries.length) {
    if (typeof showToast === 'function') showToast('目前尚未拖曳調整任何區塊尺寸', 'warning');
    return;
  }
  const text = `[Layout Tune @ ${guideViewportBucket()} ${window.innerWidth}px]\n` +
    entries.map(([sel, d]) => `- ${sel}: width=${d.width}px, min-height=${d.height}px`).join('\n');
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).catch(() => {});
  if (typeof showToast === 'function') showToast('已複製版面微調規格，可直接貼給 AI 套用', 'success', 2600);
}

/**
 * 清除目前視口的版面微調紀錄並還原預設 CSS 尺寸。
 * @returns {void}
 */
function resetLayoutTunes() {
  const map = _loadTuneMap();
  Object.keys(map).forEach(sel => {
    const el = document.querySelector(sel);
    if (el) {
      el.style.width = '';
      el.style.minHeight = '';
    }
  });
  localStorage.removeItem(_tuneStorageKey());
  renderLayoutGuides();
  if (typeof showToast === 'function') showToast('已還原目前裝置視口的預設版面尺寸', 'info', 2200);
}

window.addEventListener('resize', applySavedLayoutTunes);
document.addEventListener('DOMContentLoaded', applySavedLayoutTunes);
