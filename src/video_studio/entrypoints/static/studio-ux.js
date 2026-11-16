/* 用途：提供表單輸入離開/刷新自動暫存（localStorage），以及即時後端 Terminal 進度追蹤視窗。 */

const DRAFT_IDS = [
  'newType', 'newName', 'newTitle', 'newBrief',
  'scriptDraftInstruction', 'scriptDraftDuration', 'planInstruction', 'qaInput',
];
let _termTimer = null;

/**
 * 取得輸入欄位的 localStorage 暫存鍵名。
 * @param {string} id DOM 元素 ID。
 * @returns {string} 暫存鍵名。
 */
function _draftKey(id) {
  return `vs.draft.${id}`;
}

/**
 * 將指定輸入欄位的目前值寫入 localStorage 暫存。
 * @param {string} id DOM 元素 ID。
 * @returns {void}
 */
function saveInputDraft(id) {
  const el = document.getElementById(id);
  if (!el) return;
  localStorage.setItem(_draftKey(id), el.value);
}

/**
 * 還原所有已暫存的輸入框內容（若元素有暫存值）。
 * @returns {void}
 */
function restoreInputDrafts() {
  for (const id of DRAFT_IDS) {
    const el = document.getElementById(id);
    const saved = localStorage.getItem(_draftKey(id));
    if (el && saved !== null && saved !== '') el.value = saved;
  }
}

/**
 * 綁定輸入框的 input 與 blur 事件以自動暫存內容。
 * @returns {void}
 */
function initDraftAutosave() {
  restoreInputDrafts();
  for (const id of DRAFT_IDS) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.addEventListener('input', () => saveInputDraft(id));
    el.addEventListener('blur', () => saveInputDraft(id));
    el.addEventListener('change', () => saveInputDraft(id));
  }
}

/**
 * 依據日誌內容與目前執行狀態估算 0-100% 進度並更新進度條。
 * @param {string[]} lines 最新日誌行陣列。
 * @returns {void}
 */
function updateTerminalProgress(lines) {
  const fill = document.getElementById('termProgressFill');
  const label = document.getElementById('termProgressLabel');
  if (!fill || !label) return;
  const tailText = lines.slice(-25).join('\n');
  let pct = 0;
  let status = '待命中';
  const totalLines = (document.getElementById('scriptEditor')?.value || '')
    .split('\n').filter(l => l.trim() && !l.trim().startsWith('#')).length || 30;
  const matches = [...tailText.matchAll(/_generate_missing_takes:\d+\s*-\s*\[(\d+)\]/g)];
  if (matches.length) {
    const cur = Number(matches[matches.length - 1][1]);
    pct = Math.min(98, Math.round((cur / totalLines) * 100));
    status = `配音/對齊第 ${cur}/${totalLines} 句`;
  } else if (/\[agy\] 步驟/.test(tailText)) {
    pct = 65;
    status = 'agy-cli 執行工具與撰寫中';
  } else if (/\[agy\] (開始|啟動模型|執行單次)/.test(tailText) || (typeof state !== 'undefined' && state.busyPlan)) {
    pct = 30;
    status = 'agy-cli 啟動規劃中';
  }
  if (/完成：|\[agy\] 完成|Drafted review script|Applied .* avatar overlay|已儲存/.test(lines.slice(-4).join('\n'))) {
    pct = 100;
    status = '已完成';
  }
  fill.style.width = `${pct}%`;
  label.textContent = `${status} · ${pct}%`;
}

/**
 * 向後端 /api/logs/tail 取得最新日誌並更新 Terminal 視窗。
 * @returns {Promise<void>}
 */
async function refreshLiveTerminal() {
  const box = document.getElementById('terminalLogOutput');
  if (!box) return;
  try {
    const res = await api('/api/logs/tail?lines=60');
    const lines = res.lines || [];
    box.textContent = lines.length ? lines.join('\n') : '（尚無執行日誌）';
    box.scrollTop = box.scrollHeight;
    updateTerminalProgress(lines);
  } catch {
    // ignore transient poll errors
  }
}

/**
 * 切換即時 Terminal 日誌自動輪詢。
 * @param {boolean} enabled 是否啟用自動輪詢。
 * @returns {void}
 */
function setLiveTerminalPolling(enabled) {
  if (_termTimer) { clearInterval(_termTimer); _termTimer = null; }
  const btn = document.getElementById('termAutoBtn');
  if (btn) {
    btn.classList.toggle('on', enabled);
    btn.textContent = enabled ? '🟢 即時追蹤中 (1.5s)' : '⏸️ 已暫停追蹤';
  }
  if (enabled) {
    refreshLiveTerminal();
    _termTimer = setInterval(refreshLiveTerminal, 1500);
  }
}

/**
 * 初始化即時 Terminal 視窗控制按鈕。
 * @returns {void}
 */
function initLiveTerminal() {
  let polling = true;
  document.getElementById('termAutoBtn')?.addEventListener('click', () => {
    polling = !polling;
    setLiveTerminalPolling(polling);
  });
  document.getElementById('termRefreshBtn')?.addEventListener('click', refreshLiveTerminal);
  setLiveTerminalPolling(true);
}

document.addEventListener('DOMContentLoaded', () => {
  initDraftAutosave();
  initLiveTerminal();
  initAspectAndPreviewFit();
  initReviewHistoryAndPlanPreset();
});

let _resumedRunId = null;

/**
 * 重新載入或切換工作時，自動偵測並續接背景執行中的 Antigravity (agy CLI) 規劃任務。
 * @param {string} jobName 工作名稱。
 * @returns {Promise<void>}
 */
async function resumeActivePlanIfAny(jobName) {
  if (!jobName || (typeof state !== 'undefined' && state.busyPlan)) return;
  try {
    const res = await api(`/api/jobs/${encodeURIComponent(jobName)}/plan/active`);
    if (!res?.active || res.status !== 'running' || !res.run_id || res.run_id === _resumedRunId) {
      return;
    }
    _resumedRunId = res.run_id;
    state.busyPlan = true;
    toggleDrawer(true);
    const typingEl = appendChatMsg('ai', '', true);
    if (res.output) {
      typingEl.classList.remove('qa-typing');
      typingEl.textContent = `${res.output}\n\n▌ 已重新連線背景規劃中…`;
    } else {
      const span = typingEl.querySelector('span:last-child');
      if (span) span.textContent = '🔄 已重新連線背景執行中的 Antigravity 規劃…';
    }
    try {
      await pollPlanLoop(res.run_id, typingEl);
    } finally {
      state.busyPlan = false;
      _resumedRunId = null;
    }
  } catch {
    // ignore transient reconnect errors
  }
}

/**
 * 依 HTML data-width/data-height 或設定尺寸等比縮放 reviewPreviewFrame，確保完整畫面不裁切。
 * @returns {void}
 */
function fitReviewPreviewFrame() {
  const stage = document.getElementById('reviewStage');
  const frame = document.getElementById('reviewPreviewFrame');
  if (!stage || !frame) return;
  let w = Number(document.getElementById('cfgWidth')?.value || 1920) || 1920;
  let h = Number(document.getElementById('cfgHeight')?.value || 1080) || 1080;
  try {
    const docEl = frame.contentDocument?.documentElement;
    const dw = Number(docEl?.getAttribute('data-width') || 0);
    const dh = Number(docEl?.getAttribute('data-height') || 0);
    if (dw >= 320 && dh >= 320) { w = dw; h = dh; }
  } catch {
    // cross-origin guard
  }
  stage.style.aspectRatio = `${w} / ${h}`;
  frame.style.width = `${w}px`;
  frame.style.height = `${h}px`;
  const scale = stage.clientWidth > 0 ? stage.clientWidth / w : 1;
  frame.style.transform = `scale(${scale})`;
  const badge = document.getElementById('reviewDimBadge');
  if (badge) badge.textContent = `完整畫面等比縮放預覽 · ${w}×${h} (${Math.round(scale * 100)}%)`;
}

/**
 * 依寬高輸入框同步影片比例預設下拉選單。
 * @returns {void}
 */
function syncAspectPresetFromInputs() {
  const sel = document.getElementById('cfgAspectPreset');
  const w = Number(document.getElementById('cfgWidth')?.value || 1920);
  const h = Number(document.getElementById('cfgHeight')?.value || 1080);
  if (sel) {
    const key = `${w}x${h}`;
    const hasOpt = Array.from(sel.options).some(o => o.value === key);
    sel.value = hasOpt ? key : 'custom';
  }
  fitReviewPreviewFrame();
}

/**
 * 初始化影片比例預設選擇、自訂寬高同步與 review 預覽框自動等比縮放。
 * @returns {void}
 */
function initAspectAndPreviewFit() {
  const sel = document.getElementById('cfgAspectPreset');
  const wInput = document.getElementById('cfgWidth');
  const hInput = document.getElementById('cfgHeight');
  sel?.addEventListener('change', () => {
    if (sel.value !== 'custom' && sel.value.includes('x')) {
      const [w, h] = sel.value.split('x').map(Number);
      if (wInput) wInput.value = String(w);
      if (hInput) hInput.value = String(h);
    }
    fitReviewPreviewFrame();
  });
  wInput?.addEventListener('input', syncAspectPresetFromInputs);
  hInput?.addEventListener('input', syncAspectPresetFromInputs);

  const stage = document.getElementById('reviewStage');
  const frame = document.getElementById('reviewPreviewFrame');
  frame?.addEventListener('load', fitReviewPreviewFrame);
  if (stage && typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(fitReviewPreviewFrame).observe(stage);
  }
  document.getElementById('openReviewTabBtn')?.addEventListener('click', () => {
    if (typeof state !== 'undefined' && state.currentJob) {
      window.open(`/api/jobs/${encodeURIComponent(state.currentJob)}/review/index.html`, '_blank', 'noopener');
    }
  });
  fitReviewPreviewFrame();
}

const DEFAULT_PLAN_RULES = [
  '- 講解中的 section，寬度約為總螢幕的 3/4（~75%），置中呈現；若該 section 高度大於螢幕畫面，講解到該部分時使用平滑 scrolling 下滑呈現。',
  '- 必要時適當使用手寫（SVG 筆畫）、手繪標記（圓圈／底線／箭頭）增加動畫。',
  '- 移除所有 emoji，背景海報輪廓水平與垂直置中。',
].join('\n');

/**
 * 重新載入目前工作的 review/ 草稿版本快照清單。
 * @param {string} jobName 工作名稱。
 * @returns {Promise<void>}
 */
async function refreshReviewSnapshots(jobName) {
  const sel = document.getElementById('reviewSnapshotSelect');
  if (!sel || !jobName) return;
  try {
    const res = await api(`/api/jobs/${encodeURIComponent(jobName)}/review/snapshots`);
    const items = res.snapshots || [];
    if (!items.length) {
      sel.innerHTML = '<option value="">（尚無草稿快照，執行 agy 規劃前會自動備份）</option>';
      return;
    }
    sel.innerHTML = items.map(s =>
      `<option value="${esc(s.id)}">${esc(s.id)} · ${esc(s.created_at)} · ${esc(s.note)} (${esc((s.files || []).join(', '))})</option>`
    ).join('');
  } catch {
    // ignore transient load errors
  }
}

/**
 * 初始化草稿快照儲存／退回按鈕與預設規則插入按鈕。
 * @returns {void}
 */
function initReviewHistoryAndPlanPreset() {
  document.getElementById('insertPlanPresetBtn')?.addEventListener('click', () => {
    const box = document.getElementById('planInstruction');
    if (!box) return;
    box.value = box.value.trim() ? `${box.value.trim()}\n${DEFAULT_PLAN_RULES}` : DEFAULT_PLAN_RULES;
    box.dispatchEvent(new Event('input'));
  });
  document.getElementById('saveSnapshotBtn')?.addEventListener('click', async () => {
    if (!state?.currentJob) return;
    const note = window.prompt('輸入此草稿快照備註（方便日後識別）：', '手動備份') ?? '';
    if (!note.trim()) return;
    try {
      const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/review/snapshots`, {
        method: 'POST',
        body: JSON.stringify({ note: note.trim() }),
      });
      await refreshReviewSnapshots(state.currentJob);
      alert(res.output || '已儲存草稿快照');
    } catch (err) {
      alert(`儲存快照失敗：${err.message}`);
    }
  });
  document.getElementById('restoreSnapshotBtn')?.addEventListener('click', async () => {
    const sel = document.getElementById('reviewSnapshotSelect');
    const snapId = sel?.value;
    if (!state?.currentJob || !snapId) return;
    if (!window.confirm(`確定要將 review/ 退回至快照 ${snapId}？（退回前會自動備份目前版本）`)) return;
    try {
      const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/review/snapshots/${encodeURIComponent(snapId)}/restore`, {
        method: 'POST',
      });
      await refreshReviewSnapshots(state.currentJob);
      const frame = document.getElementById('reviewPreviewFrame');
      if (frame) frame.src = `/api/jobs/${encodeURIComponent(state.currentJob)}/review/index.html?t=${Date.now()}`;
      await loadJobDetail(state.currentJob);
      alert(res.output || '已退回至指定草稿版本');
    } catch (err) {
      alert(`退回失敗：${err.message}`);
    }
  });
}



