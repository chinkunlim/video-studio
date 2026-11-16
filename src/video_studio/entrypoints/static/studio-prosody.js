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
 * 依推薦順序（1、2、3 標註）建立模型下拉選單 HTML。
 * @param {Array<{id: string, label: string}>} models 可用模型清單。
 * @param {string[]} recs 推薦排序的模型 ID 陣列。
 * @param {Record<string, string>} notes 推薦說明標籤。
 * @returns {string} HTML option 字串。
 */
function _buildRankedModelOptions(models, recs, notes) {
  const byId = new Map((models || []).map(m => [m.id, m.label]));
  const seen = new Set();
  const opts = [];
  recs.forEach((id, i) => {
    seen.add(id);
    const lbl = byId.get(id) || id;
    opts.push(`<option value="${esc(id)}">${i + 1}. ${esc(lbl)}（${esc(notes[id] || '推薦')}）</option>`);
  });
  for (const m of models || []) {
    if (!seen.has(m.id)) opts.push(`<option value="${esc(m.id)}">${esc(m.label)} (${esc(m.id)})</option>`);
  }
  opts.push('<option value="">交由 agy CLI 預設決定</option>');
  return opts.join('');
}

/**
 * 載入本機 agy CLI 可用模型清單至各階段選擇器（含 1、2、3 建議排序）。
 * @returns {Promise<void>}
 */
async function loadAgyModels() {
  const selScript = document.getElementById('scriptModelSelect');
  const selMain = document.getElementById('planModelSelect');
  const selDrawer = document.getElementById('qaModelSelect');
  const res = await api('/api/agy/models').catch(() => ({ models: [] }));
  const models = res.models || [];
  const scriptRecs = ['gemini-4-argon-medium', 'gemini-3.8-flash-high', 'gemini-4-hydrogen-medium'];
  const scriptNotes = {
    'gemini-4-argon-medium': '★ 推薦主力：快又準',
    'gemini-3.8-flash-high': '極速草稿與翻譯',
    'gemini-4-hydrogen-medium': '深度邏輯潤飾',
  };
  const planRecs = ['gemini-4-argon-high', 'gemini-4-hydrogen-high', 'claude-sonnet-5-5-high'];
  const planNotes = {
    'gemini-4-argon-high': '★ 推薦平衡：速度與畫質兼顧',
    'gemini-4-hydrogen-high': '最高畫質：複雜海報與 GSAP 首選',
    'claude-sonnet-5-5-high': '前端動畫精修備選',
  };
  if (selScript) {
    selScript.innerHTML = _buildRankedModelOptions(models, scriptRecs, scriptNotes);
    selScript.value = scriptRecs[0];
  }
  const planHtml = _buildRankedModelOptions(models, planRecs, planNotes);
  if (selMain) { selMain.innerHTML = planHtml; selMain.value = planRecs[0]; }
  if (selDrawer) { selDrawer.innerHTML = planHtml; selDrawer.value = planRecs[0]; }
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

/**
 * 將目前講稿翻譯為雙語字幕對照表（work/script_bilingual.tsv）。
 * @returns {Promise<void>}
 */
async function handleTranslateBilingual() {
  if (!state.currentJob) return;
  showToast('正在以 agy CLI 翻譯雙語字幕…', 'info', 3500);
  const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/subtitles/bilingual`, {
    method: 'POST',
    body: JSON.stringify({
      target_lang: document.getElementById('cfgSubtitleSecondaryLang').value,
      model: document.getElementById('scriptModelSelect')?.value || '',
    }),
  });
  showToast(res.output || '已完成雙語翻譯', 'success');
  await loadBilingualPreview(state.currentJob);
}

/**
 * 載入並顯示 work/script_bilingual.tsv 的雙語字幕對照內容。
 * @param {string} jobName 工作名稱。
 * @returns {Promise<void>}
 */
async function loadBilingualPreview(jobName) {
  const box = document.getElementById('bilingualPreviewBox');
  if (!box || !jobName) return;
  const res = await api(`/api/jobs/${encodeURIComponent(jobName)}/subtitles/bilingual`).catch(() => ({ exists: false }));
  if (!res.exists || !(res.rows || []).length) { box.style.display = 'none'; return; }
  box.style.display = 'block';
  box.textContent = res.rows.map(r => `[${r.index}] ${r.primary}\n    ${r.secondary}`).join('\n');
}

/**
 * 產生 10 秒標準 / 活力 / 沉穩韻律試聽音檔，讓使用者試聽並套用。
 * @returns {Promise<void>}
 */
async function handleProsodyPreview() {
  if (!state.currentJob) return;
  showToast('正在產生 10 秒韻律試聽（標準 / 活力 / 沉穩）…', 'info', 4000);
  const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/narrate/prosody-preview`, {
    method: 'POST', body: JSON.stringify({ sample_text: '' }),
  });
  const box = document.getElementById('prosodyPreviewBox');
  const labels = { normal: '標準自然 (normal)', energetic: '活力強音加速 (energetic)', calm: '沉穩放慢輕柔 (calm)' };
  box.style.display = 'grid';
  box.innerHTML = Object.entries(res.files || {}).map(([preset, fname]) => `
    <div class="card" style="padding:12px;">
      <strong>${esc(labels[preset] || preset)}</strong>
      <audio controls style="width:100%;" src="/api/jobs/${encodeURIComponent(state.currentJob)}/review/${encodeURIComponent(fname)}?t=${Date.now()}"></audio>
      <button type="button" class="btn btn-soft btn-sm" onclick="selectProsodyPreset('${esc(preset)}')">套用此風格</button>
    </div>`).join('');
  showToast(res.output, 'success');
}

/**
 * 將試聽選定的韻律風格套用至目前工作設定並儲存。
 * @param {string} preset 韻律預設名稱。
 * @returns {Promise<void>}
 */
async function selectProsodyPreset(preset) {
  document.getElementById('cfgProsodyPreset').value = preset;
  await handleSaveJobConfig();
}

document.addEventListener('DOMContentLoaded', initProsodyAndAgyControls);
