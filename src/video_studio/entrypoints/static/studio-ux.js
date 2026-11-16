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
  } else if (typeof state !== 'undefined' && state.busyPlan) {
    pct = 55;
    status = 'agy-cli 規劃分鏡中';
  }
  if (/完成：|Drafted review script|Applied .* avatar overlay|已儲存/.test(lines.slice(-4).join('\n'))) {
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
});
