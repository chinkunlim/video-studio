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
