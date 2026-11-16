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
  initReviewHistory();
  initStudioUxOverhaul();
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
 * 初始化草稿快照儲存與退回按鈕。
 * @returns {void}
 */
function initReviewHistory() {
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

/**
 * 觸發影片渲染並鎖定重複點擊，即時顯示渲染狀態與錯誤提示。
 * @param {string} mode 渲染模式（html 或 poster）。
 * @returns {Promise<void>}
 */
async function runRenderEndpoint(mode) {
  if (!state.currentJob || state.busyRender) return;
  state.busyRender = true;
  const htmlBtn = document.getElementById('renderHtmlBtn');
  const posterBtn = document.getElementById('renderPosterBtn');
  const logEl = document.getElementById('renderLog');
  if (htmlBtn) htmlBtn.disabled = true;
  if (posterBtn) posterBtn.disabled = true;
  if (logEl) logEl.textContent = `⏳ 正在執行 ${mode.toUpperCase()} 影片渲染，請稍候並查看下方即時 Terminal 日誌…`;
  showToast('已開始渲染影片，過程約需 1–5 分鐘', 'info');
  try {
    const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/video/${mode}`, {
      method: 'POST', body: JSON.stringify({}),
    });
    if (logEl) logEl.textContent = res.output;
    showToast('影片渲染完成', 'success');
    await loadJobDetail(state.currentJob);
  } catch (err) {
    if (logEl) logEl.textContent = `渲染失敗：${err.message}`;
    showToast(`渲染失敗：${err.message}`, 'error');
  } finally {
    state.busyRender = false;
    if (htmlBtn) htmlBtn.disabled = false;
    if (posterBtn) posterBtn.disabled = false;
  }
}

/**
 * 新增或更新詞彙表項目。
 * @returns {Promise<void>}
 */
async function handleSaveVocab() {
  const res = await api('/api/vocab', {
    method: 'POST',
    body: JSON.stringify({
      key: document.getElementById('vocKey').value.trim(),
      subtitle: document.getElementById('vocSub').value.trim(),
      tts: document.getElementById('vocTts').value.trim(),
    }),
  });
  document.getElementById('vocabListLog').textContent = (await api('/api/vocab')).output;
  showToast(res.output || '已更新詞彙表', 'success');
}

/**
 * 儲存全域 .env 設定並關閉設定視窗。
 * @returns {Promise<void>}
 */
async function handleSaveEnv() {
  const res = await api('/api/settings/env', {
    method: 'PUT',
    body: JSON.stringify({
      values: {
        VOICEBOX_URL: document.getElementById('envVoicebox').value.trim(),
        OLLAMA_BASE_URL: document.getElementById('envOllama').value.trim(),
        OLLAMA_MODEL: document.getElementById('envOllamaModel').value.trim(),
        SADTALKER_DIR: document.getElementById('envSadtalkerDir').value.trim(),
        LOG_LEVEL: document.getElementById('envLogLevel').value,
      },
    }),
  });
  document.getElementById('globalSettingsModal')?.classList.remove('open');
  showToast(res.output || '已儲存全域設定', 'success');
}

/**
 * 將符合副檔名的 input/ 清單填入指定 select 元素。
 * @param {string} id 目標 select 元素 ID。
 * @param {string[]} files 候選檔名陣列。
 * @param {string} cur 目前已設定檔名。
 * @param {string} [emptyLabel='（無）'] 空值選項文字。
 * @returns {void}
 */
function _fillFileSelect(id, files, cur, emptyLabel = '（無）') {
  const el = document.getElementById(id);
  if (!el) return;
  if (el.tagName !== 'SELECT') { el.value = cur || ''; return; }
  const opts = [`<option value="">${emptyLabel}</option>`].concat(
    files.map(f => `<option value="${esc(f)}">${esc(f)}</option>`)
  );
  if (cur && !files.includes(cur)) opts.push(`<option value="${esc(cur)}">${esc(cur)}</option>`);
  el.innerHTML = opts.join('');
  el.value = cur || '';
}

/**
 * 將工作 input/ 檔案清單填入下拉選單，避免手動輸入檔名。
 * @param {object} d 工作詳情回應。
 * @param {object} c job.toml 設定物件。
 * @returns {void}
 */
function populateInputFileSelects(d, c) {
  const files = d.input_files || [];
  _fillFileSelect('cfgAvatarImage', files.filter(f => /\.(png|jpe?g|webp)$/i.test(f)), c.avatar?.image, '（未指定）');
  _fillFileSelect('cfgInScript', files.filter(f => /\.(md|txt)$/i.test(f)), c.inputs?.script, '（未指定）');
  _fillFileSelect('cfgInPptx', files.filter(f => /\.pptx$/i.test(f)), c.inputs?.pptx);
  _fillFileSelect('cfgInPoster', files.filter(f => /\.(png|jpe?g|pdf)$/i.test(f)), c.inputs?.poster);
  _fillFileSelect('cfgInScenes', files.filter(f => /\.toml$/i.test(f)), c.inputs?.scenes);
  const titleEl = document.getElementById('projectFormTitle');
  if (titleEl) titleEl.textContent = `編輯目前專案：${d.name}`;
}

/**
 * 依選擇的語音語言篩選 edge-tts 可用聲線（避免英文選到中文人聲）。
 * @returns {void}
 */
function filterVoicesByLanguage() {
  const lang = (document.getElementById('cfgVoiceLanguage')?.value || 'zh').toLowerCase();
  const sel = document.getElementById('cfgEdgeVoice');
  if (!sel) return;
  let firstVisible = '';
  Array.from(sel.options).forEach(opt => {
    const match = !opt.dataset.lang || opt.dataset.lang === lang;
    opt.hidden = !match;
    opt.disabled = !match;
    if (match && !firstVisible) firstVisible = opt.value;
  });
  const curOpt = sel.selectedOptions[0];
  if ((!curOpt || curOpt.disabled) && firstVisible) sel.value = firstVisible;
}

/**
 * 背景預先快取目前選定聲線的 10 秒標準/活力/沉穩試聽檔。
 * @returns {Promise<void>}
 */
async function prewarmVoiceSamples() {
  const engine = document.getElementById('cfgVoiceEngine')?.value || 'edge-tts';
  const language = document.getElementById('cfgVoiceLanguage')?.value || 'zh';
  const voice = engine === 'voicebox'
    ? (document.getElementById('cfgVoiceProfile')?.value || 'My Voice')
    : (document.getElementById('cfgEdgeVoice')?.value || 'zh-TW-HsiaoChenNeural');
  const rate = document.getElementById('cfgEdgeRate')?.value || '+0%';
  const statusEl = document.getElementById('voiceSampleStatus');
  if (!voice) return;
  try {
    let res = await api(`/api/voice/samples?voice=${encodeURIComponent(voice)}`);
    if (!res.ready) {
      if (statusEl) statusEl.textContent = `正在預先準備 ${voice} 的 10 秒試聽範本…`;
      await api('/api/voice/samples/prewarm', {
        method: 'POST',
        body: JSON.stringify({ voice, language, engine, rate }),
      });
      for (let i = 0; i < 6; i++) {
        await new Promise(r => setTimeout(r, 1500));
        res = await api(`/api/voice/samples?voice=${encodeURIComponent(voice)}`);
        if (res.ready) break;
      }
    }
    if (res.ready) {
      window._cachedVoiceSamples = res.files || {};
      if (statusEl) statusEl.textContent = `已就緒（${voice}）：點擊右側即可即時試聽`;
    } else if (statusEl) {
      statusEl.textContent = `試聽準備中，請稍候再點試聽`;
    }
  } catch {
    if (statusEl) statusEl.textContent = '目前無法預先抓取試聽（離線或引擎未啟動）';
  }
}

/**
 * 綁定依用途上傳素材的檔案選擇器並自動對應至 job.toml。
 * @param {string} inputId input[type=file] 元素 ID。
 * @param {string} role 素材用途 ('poster' | 'script' | 'avatar')。
 * @returns {void}
 */
function _bindRoleUpload(inputId, role) {
  document.getElementById(inputId)?.addEventListener('change', async e => {
    const file = e.target.files?.[0];
    if (!file || !state?.currentJob) return;
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await fetch(`/api/jobs/${encodeURIComponent(state.currentJob)}/upload`, { method: 'POST', body: fd });
      if (!res.ok) throw new Error(await res.text());
      await loadJobDetail(state.currentJob);
      const map = {
        poster: file.name.toLowerCase().endsWith('.pptx') ? 'cfgInPptx' : 'cfgInPoster',
        script: 'cfgInScript',
        avatar: 'cfgAvatarImage',
      };
      const sel = document.getElementById(map[role]);
      if (sel) sel.value = file.name;
      if (typeof handleSaveJobConfig === 'function') await handleSaveJobConfig();
      showToast(`已上傳並自動對應：${file.name}`, 'success');
    } catch (err) {
      showToast(`上傳失敗：${err.message}`, 'error');
    } finally {
      e.target.value = '';
    }
  });
}

/**
 * 初始化全螢幕切換、全域設定視窗與推擠式對話欄收合控制。
 * @returns {void}
 */
function _initShellAndDrawerControls() {
  const fsBtn = document.getElementById('fullscreenBtn');
  fsBtn?.addEventListener('click', () => {
    if (document.fullscreenElement) document.exitFullscreen?.();
    else document.documentElement.requestFullscreen?.();
  });
  document.addEventListener('fullscreenchange', () => {
    if (fsBtn) fsBtn.lastChild.textContent = document.fullscreenElement ? ' 退出全螢幕' : ' 全螢幕';
  });
  const modal = document.getElementById('globalSettingsModal');
  document.getElementById('openGlobalSettingsBtn')?.addEventListener('click', () => modal?.classList.add('open'));
  document.getElementById('closeGlobalSettingsBtn')?.addEventListener('click', () => modal?.classList.remove('open'));
  modal?.addEventListener('click', e => { if (e.target === modal) modal.classList.remove('open'); });
  document.getElementById('mainWorkspace')?.addEventListener('click', e => {
    if (!document.body.classList.contains('qa-open')) return;
    if (e.target.closest('#qaToggleBtn, #runAgyPlanBtn, #qaDrawer')) return;
    if (typeof toggleDrawer === 'function') toggleDrawer(false);
  });
  document.querySelectorAll('#qaThreadSeg button').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#qaThreadSeg button').forEach(b => b.classList.toggle('on', b === btn));
      if (typeof state !== 'undefined') state.qaThreadMode = btn.dataset.thread || 'continue';
    });
  });
}

/**
 * 初始化分頁切換、依用途上傳、語言聲線聯動與 10 秒即時試聽。
 * @returns {void}
 */
function initStudioUxOverhaul() {
  _initShellAndDrawerControls();
  document.querySelectorAll('#scriptViewSeg button').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#scriptViewSeg button').forEach(b => b.classList.toggle('on', b === btn));
      const isEdit = btn.dataset.stab === 'edit';
      document.getElementById('scriptTabEdit').style.display = isEdit ? 'block' : 'none';
      document.getElementById('scriptTabBilingual').style.display = isEdit ? 'none' : 'block';
    });
  });
  _bindRoleUpload('rolePosterInput', 'poster');
  _bindRoleUpload('roleScriptInput', 'script');
  _bindRoleUpload('roleAvatarInput', 'avatar');
  document.getElementById('cfgVoiceLanguage')?.addEventListener('change', () => { filterVoicesByLanguage(); prewarmVoiceSamples(); });
  document.getElementById('cfgEdgeVoice')?.addEventListener('change', prewarmVoiceSamples);
  document.getElementById('cfgVoiceEngine')?.addEventListener('change', prewarmVoiceSamples);
  document.querySelectorAll('[data-sample-preset]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const preset = btn.dataset.samplePreset;
      let files = window._cachedVoiceSamples || {};
      if (!files[preset]) await prewarmVoiceSamples();
      files = window._cachedVoiceSamples || {};
      const player = document.getElementById('voiceSampleAudio');
      if (player && files[preset]) {
        player.src = `${files[preset]}?t=${Date.now()}`;
        player.play().catch(() => {});
      } else {
        showToast('試聽檔仍在背景準備中，請稍後幾秒再試', 'warning');
      }
    });
  });
  document.getElementById('saveAndNextStep3Btn')?.addEventListener('click', async () => {
    if (typeof handleSaveJobConfig === 'function') await handleSaveJobConfig();
    if (typeof switchView === 'function') switchView('narrate');
  });
  document.getElementById('resetNewJobBtn')?.addEventListener('click', () => {
    const titleEl = document.getElementById('projectFormTitle');
    if (titleEl) titleEl.textContent = '建立新專案';
  });
}



