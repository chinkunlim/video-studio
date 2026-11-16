/* 用途：提供講稿詞彙級韻律彩色標記編輯器（強音/弱音/加速/放慢）、最原始初稿還原，以及 agy CLI 模型清單載入。 */

/**
 * 將講稿中的韻律標記轉為彩色 highlight HTML（唯讀互動檢視區，點擊標記可移除）。
 * @param {string} raw 原始講稿文字。
 * @returns {string} 含彩色 <mark> 標籤的 HTML 字串。
 */
function buildProsodyHighlightHtml(raw) {
  let html = esc(raw || '');
  html = html.replace(/\[(loud|soft|fast|slow)\]([\s\S]*?)\[\/\1\]/gi, (_, tag, inner) => {
    const t = tag.toLowerCase();
    return `<mark class="pmark pmark-${t}" data-tag="${t}" title="點擊移除 ${t} 標記">${inner}</mark>`;
  });
  html = html.replace(/\*\*([^*\n]+)\*\*/g, (_, inner) => {
    return `<mark class="pmark pmark-loud" data-tag="loud" data-star="1" title="點擊移除強音標記">${inner}</mark>`;
  });
  html = html.replace(/^\[(fast|slow|loud|soft)\]\s+(.+)$/gim, (_, tag, rest) => {
    const t = tag.toLowerCase();
    return `<mark class="pmark pmark-${t}" data-tag="${t}" data-prefix="1" title="整句標記（點擊移除）">${rest}</mark>`;
  });
  return html || '<span class="muted">（講稿空白，輸入或 AI 生成後將在此顯示彩色語氣標記）</span>';
}

/**
 * 同步更新彩色韻律預覽區內容。
 * @returns {void}
 */
function renderProsodyHighlights() {
  const ed = document.getElementById('scriptEditor');
  const view = document.getElementById('prosodyHighlightView');
  if (!ed || !view) return;
  view.innerHTML = buildProsodyHighlightHtml(ed.value);
}

/**
 * 為講稿編輯器中選取的文字加上指定韻律標記（loud/soft/fast/slow）。
 * @param {'loud'|'soft'|'fast'|'slow'} tag 韻律標籤名稱。
 * @returns {void}
 */
function wrapScriptProsody(tag) {
  const ed = document.getElementById('scriptEditor');
  if (!ed) return;
  let start = ed.selectionStart;
  let end = ed.selectionEnd;
  if (start === end) {
    const selText = window.getSelection()?.toString().trim();
    if (selText) {
      const idx = ed.value.indexOf(selText);
      if (idx >= 0) { start = idx; end = idx + selText.length; }
    }
  }
  if (start === end) {
    showToast('請先在講稿編輯區反白選取要調整語氣的詞彙或句子', 'warning');
    return;
  }
  const selected = ed.value.slice(start, end);
  const clean = selected.replace(/\[\/?(loud|soft|fast|slow)\]/gi, '').replace(/^\*\*|\*\*$/g, '');
  const wrapped = `[${tag}]${clean}[/${tag}]`;
  ed.value = ed.value.slice(0, start) + wrapped + ed.value.slice(end);
  renderProsodyHighlights();
  showToast(`已標記「${clean}」為 ${tag}`, 'success', 1800);
}

/**
 * 移除講稿編輯器選取範圍內的韻律標記。
 * @returns {void}
 */
function clearSelectedProsody() {
  const ed = document.getElementById('scriptEditor');
  if (!ed) return;
  const start = ed.selectionStart;
  const end = ed.selectionEnd;
  if (start === end) {
    showToast('請反白要移除標記的段落，或直接點擊下方彩色標記詞', 'info');
    return;
  }
  const selected = ed.value.slice(start, end);
  const clean = selected.replace(/\[\/?(loud|soft|fast|slow)\]/gi, '').replace(/\*\*(.+?)\*\*/g, '$1');
  ed.value = ed.value.slice(0, start) + clean + ed.value.slice(end);
  renderProsodyHighlights();
  showToast('已移除選取範圍內的韻律標記', 'info', 1800);
}

/**
 * 點擊預覽區的彩色 <mark> 時，移除該詞彙的韻律標記。
 * @param {MouseEvent} e 點擊事件。
 * @returns {void}
 */
function _onHighlightClick(e) {
  const mark = e.target.closest('mark.pmark');
  const ed = document.getElementById('scriptEditor');
  if (!mark || !ed) return;
  const text = mark.textContent || '';
  const tag = mark.dataset.tag || 'loud';
  let next = ed.value;
  if (mark.dataset.star === '1') {
    next = next.replace(`**${text}**`, text);
  } else if (mark.dataset.prefix === '1') {
    next = next.replace(new RegExp(`\\[${tag}\\]\\s*${text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`, 'i'), text);
  } else {
    next = next.replace(`[${tag}]${text}[/${tag}]`, text);
  }
  ed.value = next;
  renderProsodyHighlights();
  showToast(`已移除「${text}」的 ${tag} 標記`, 'info', 1800);
}

/**
 * 載入並還原保留的最原始初稿（review/script.original.md）。
 * @returns {Promise<void>}
 */
async function restoreOriginalScript() {
  if (!state.currentJob) return;
  const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/original-script`);
  if (!res.exists) {
    showToast('此工作尚未建立過最原始初稿（初次儲存或 AI 生成時會自動保留）', 'warning');
    return;
  }
  document.getElementById('scriptEditor').value = res.content;
  renderProsodyHighlights();
  showToast('已還原最原始初稿（尚未覆寫 input/script.md，請確認後儲存）', 'success', 2800);
}

/**
 * 載入本機 agy CLI 可用模型清單至選擇器。
 * @returns {Promise<void>}
 */
async function loadAgyModels() {
  const selMain = document.getElementById('planModelSelect');
  const selDrawer = document.getElementById('qaModelSelect');
  if (!selMain && !selDrawer) return;
  const res = await api('/api/agy/models').catch(() => ({ models: [] }));
  const opts = ['<option value="">預設 (agy 預設模型)</option>'].concat(
    (res.models || []).map(m => `<option value="${esc(m.id)}">${esc(m.label)} (${esc(m.id)})</option>`)
  );
  const html = opts.join('');
  if (selMain) selMain.innerHTML = html;
  if (selDrawer) selDrawer.innerHTML = html;
}

/**
 * 綁定視覺韻律編輯器與 agy 模型同步事件。
 * @returns {void}
 */
function initProsodyAndAgyControls() {
  document.getElementById('scriptEditor')?.addEventListener('input', renderProsodyHighlights);
  document.getElementById('prosodyHighlightView')?.addEventListener('click', _onHighlightClick);
  document.getElementById('restoreOriginalScriptBtn')?.addEventListener('click', restoreOriginalScript);
  document.getElementById('clearProsodyBtn')?.addEventListener('click', clearSelectedProsody);
  document.querySelectorAll('[data-prosody-tag]').forEach(btn => {
    btn.addEventListener('click', () => wrapScriptProsody(btn.dataset.prosodyTag));
  });
  const selMain = document.getElementById('planModelSelect');
  const selDrawer = document.getElementById('qaModelSelect');
  selMain?.addEventListener('change', () => { if (selDrawer) selDrawer.value = selMain.value; });
  selDrawer?.addEventListener('change', () => { if (selMain) selMain.value = selDrawer.value; });
  loadAgyModels();
}

document.addEventListener('DOMContentLoaded', initProsodyAndAgyControls);
