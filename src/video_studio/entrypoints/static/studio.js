/* video-studio 工作室前端邏輯：全設定編輯、媒體預覽與 Antigravity agy CLI 對話串流顯示。 */

const state = {
  jobs: [],
  currentJob: '',
  lastPrompt: '',
  busyPlan: false,
  stagedFiles: [],
};

/**
 * 跳脫 HTML 特殊字元以防止 XSS。
 * @param {string} str 原始字串。
 * @returns {string} 跳脫後的安全字串。
 */
function esc(str) {
  return String(str || '').replace(/[&<>"']/g, s => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[s]));
}

/**
 * 呼叫後端 JSON API 並統一處理錯誤。
 * @param {string} url 端點網址。
 * @param {RequestInit} [opts] Fetch 選項。
 * @returns {Promise<any>} 解析後的 JSON 物件。
 */
async function api(url, opts = {}) {
  const res = await fetch(url, { headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) }, ...opts });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

/**
 * 切換主要工作分頁。
 * @param {string} name 分頁名稱（overview/settings/narrate/render）。
 * @returns {void}
 */
function switchView(name) {
  document.querySelectorAll('.dock-btn, .step-chip').forEach(el => el.classList.toggle('on', el.dataset.view === name));
  document.querySelectorAll('.view').forEach(el => el.classList.toggle('on', el.id === `view-${name}`));
}

/**
 * 顯示非阻塞 Toast 通知訊息。
 * @param {string} msg 通知文字。
 * @param {'info'|'success'|'warning'|'error'} [type='info'] 樣式類型。
 * @param {number} [duration=2600] 自動消失毫秒數。
 * @returns {void}
 */
function showToast(msg, type = 'info', duration = 2600) {
  const stack = document.getElementById('toastStack');
  if (!stack) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  stack.appendChild(el);
  setTimeout(() => el.remove(), duration);
}

/**
 * 初始化並記憶色盤、亮暗主題、毛玻璃、側欄收合與雙欄/上下版面設定。
 * @returns {void}
 */
function initTheme() {
  const root = document.documentElement;
  const pal = localStorage.getItem('vs.palette') || 'forest';
  const mode = localStorage.getItem('vs.mode') || 'light';
  const glass = localStorage.getItem('vs.glass') || 'off';
  const layout = localStorage.getItem('vs.layout') || 'split';
  root.dataset.palette = pal;
  root.dataset.mode = mode;
  root.dataset.glass = glass;
  document.body.dataset.layout = layout;
  if (localStorage.getItem('vs.dockCollapsed') === '1') document.body.classList.add('dock-collapsed');

  document.getElementById('paletteSelect').value = pal;
  document.getElementById('paletteSelect').addEventListener('change', e => {
    root.dataset.palette = e.target.value;
    localStorage.setItem('vs.palette', e.target.value);
  });
  document.getElementById('modeToggle').addEventListener('click', () => {
    const next = root.dataset.mode === 'dark' ? 'light' : 'dark';
    root.dataset.mode = next;
    localStorage.setItem('vs.mode', next);
  });
  document.getElementById('glassToggle')?.addEventListener('click', () => {
    const next = root.dataset.glass === 'on' ? 'off' : 'on';
    root.dataset.glass = next;
    localStorage.setItem('vs.glass', next);
    showToast(`毛玻璃效果：${next === 'on' ? '開啟' : '關閉'}`, 'info', 1600);
  });
  document.getElementById('dockCollapseBtn')?.addEventListener('click', () => {
    const collapsed = document.body.classList.toggle('dock-collapsed');
    localStorage.setItem('vs.dockCollapsed', collapsed ? '1' : '0');
  });
  document.querySelectorAll('#layoutSeg button').forEach(btn => {
    btn.classList.toggle('on', btn.dataset.layout === layout);
    btn.addEventListener('click', () => {
      document.body.dataset.layout = btn.dataset.layout;
      localStorage.setItem('vs.layout', btn.dataset.layout);
      document.querySelectorAll('#layoutSeg button').forEach(b => b.classList.toggle('on', b === btn));
    });
  });
  document.getElementById('btnLayoutGuides')?.addEventListener('click', () => toggleLayoutGuides());
  document.getElementById('btnLayoutGuidesTop')?.addEventListener('click', () => toggleLayoutGuides());
  document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'g') {
      e.preventDefault();
      toggleLayoutGuides();
    }
  });
}

/**
 * 重新載入工作清單、詞彙表與全域環境設定。
 * @returns {Promise<void>}
 */
async function refreshJobs() {
  const [health, jobsRes, vocRes, envRes, avRes] = await Promise.all([
    api('/health'),
    api('/api/jobs'),
    api('/api/vocab'),
    api('/api/settings/env'),
    api('/api/avatar/status').catch(() => null),
  ]);
  document.getElementById('healthBadge').textContent = `連線正常 · ${health.app_env}`;
  if (avRes) {
    const sad = avRes.sadtalker?.ready ? 'SadTalker 就緒' : 'SadTalker 尚未備齊權重';
    const lw = avRes.lightweight?.ready ? 'FFmpeg 輕量頭像就緒' : 'FFmpeg 不可用';
    const badge = document.getElementById('avatarStatusBadge');
    if (badge) badge.textContent = `Avatar 狀態：路線 B（${lw}）｜路線 A（${sad}）`;
  }
  document.getElementById('jobsListLog').textContent = jobsRes.output || '尚無工作';
  document.getElementById('vocabListLog').textContent = vocRes.output || '（詞彙表空白）';
  document.getElementById('envVoicebox').value = envRes.VOICEBOX_URL || '';
  document.getElementById('envOllama').value = envRes.OLLAMA_BASE_URL || '';
  document.getElementById('envOllamaModel').value = envRes.OLLAMA_MODEL || '';
  document.getElementById('envSadtalkerDir').value = envRes.SADTALKER_DIR || '';
  document.getElementById('envLogLevel').value = envRes.LOG_LEVEL || 'INFO';

  const names = (jobsRes.output || '')
    .split('\n')
    .map(l => l.trim().match(/^(generate|dub|extract)\s+([A-Za-z0-9._-]+)/))
    .filter(Boolean)
    .map(m => m[2]);
  const sel = document.getElementById('jobSelect');
  const prev = state.currentJob || sel.value;
  sel.innerHTML = names.length ? names.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('') : '<option value="">尚無工作</option>';
  if (names.includes(prev)) sel.value = prev;
  state.currentJob = sel.value;
  if (state.currentJob) await loadJobDetail(state.currentJob);
}

/**
 * 載入指定工作的 job.toml、講稿、規劃說明與成品預覽。
 * @param {string} name 工作名稱。
 * @returns {Promise<void>}
 */
async function loadJobDetail(name) {
  if (!name) return;
  const d = await api(`/api/jobs/${encodeURIComponent(name)}/detail`);
  document.getElementById('fileSummary').textContent =
    `input/: ${d.input_files.length} 個檔案 ｜ review/: ${d.review_files.join(', ') || '無'} ｜ 最新成品: ${d.latest_version || '無'}`;
  const listEl = document.getElementById('inputFilesList');
  if (listEl) {
    listEl.innerHTML = d.input_files.length
      ? d.input_files.map(f => `<span class="file-chip">📄 ${esc(f)}</span>`).join('')
      : '<span class="muted">（input/ 目前無檔案）</span>';
  }
  const c = d.config || {};
  document.getElementById('cfgTitle').value = c.job?.title || '';
  document.getElementById('cfgVisualMode').value = c.visual?.mode || 'auto';
  document.getElementById('cfgVoiceEngine').value = c.voice?.engine || 'voicebox';
  document.getElementById('cfgVoiceLanguage').value = c.voice?.language || 'zh';
  document.getElementById('cfgVoiceProfile').value = c.voice?.profile || 'My Voice';
  document.getElementById('cfgEdgeVoice').value = c.voice?.edge_voice || 'zh-TW-HsiaoChenNeural';
  document.getElementById('cfgEdgeRate').value = c.voice?.edge_rate || '+0%';
  document.getElementById('cfgProsodyPreset').value = c.voice?.prosody_preset || 'normal';
  document.getElementById('cfgWhisperModel').value = c.whisper?.model || 'small';
  document.getElementById('cfgOpenccMode').value = c.whisper?.opencc_mode || 's2tw';
  document.getElementById('cfgLoudness').value = c.output?.loudness ?? -16;
  document.getElementById('cfgFps').value = c.output?.fps ?? 30;
  document.getElementById('cfgBurnIn').value = String(c.subtitles?.burn_in ?? true);
  document.getElementById('cfgBilingualSubtitles').value = String(c.subtitles?.bilingual ?? false);
  document.getElementById('cfgSubtitleSecondaryLang').value = c.subtitles?.secondary_lang || 'zh-TW';
  document.getElementById('cfgSubtitleFontSize').value = c.subtitles?.font_size ?? 22;
  document.getElementById('cfgAvatarEngine').value = c.avatar?.engine || 'none';
  document.getElementById('cfgAvatarImage').value = c.avatar?.image || '';
  document.getElementById('cfgAvatarPosition').value = c.avatar?.position || 'bottom-right';
  document.getElementById('cfgBackupDir').value = c.output?.backup_dir || '';
  document.getElementById('cfgInScript').value = c.inputs?.script || '';
  document.getElementById('cfgInPptx').value = c.inputs?.pptx || '';
  document.getElementById('cfgInPoster').value = c.inputs?.poster || '';
  document.getElementById('cfgInScenes').value = c.inputs?.scenes || '';
  document.getElementById('scriptEditor').value = d.script || '';
  if (typeof renderProsodyHighlights === 'function') renderProsodyHighlights();
  document.getElementById('briefEditor').value = d.brief || '';
  updateMediaPreview(name, d.latest_version, d.latest_files);
}

/**
 * 更新成品影片播放器與抽格總覽圖片。
 * @param {string} name 工作名稱。
 * @param {string|null} v 最新版本資料夾名稱。
 * @param {string[]} files 最新版本檔案清單。
 * @returns {void}
 */
function updateMediaPreview(name, v, files) {
  const player = document.getElementById('videoPlayer');
  const sheet = document.getElementById('contactSheetImg');
  if (v && files.includes('video_subtitled.mp4')) {
    player.src = `/api/jobs/${encodeURIComponent(name)}/output/${v}/video_subtitled.mp4?t=${Date.now()}`;
  } else if (v && files.includes('video.mp4')) {
    player.src = `/api/jobs/${encodeURIComponent(name)}/output/${v}/video.mp4?t=${Date.now()}`;
  } else {
    player.removeAttribute('src');
  }
  if (v && files.includes('video_contact_sheet.jpg')) {
    sheet.src = `/api/jobs/${encodeURIComponent(name)}/output/${v}/video_contact_sheet.jpg?t=${Date.now()}`;
  } else {
    sheet.removeAttribute('src');
  }
}

/**
 * 開關右側 Antigravity 對話抽屜。
 * @param {boolean} open 是否開啟。
 * @returns {void}
 */
function toggleDrawer(open) {
  const drawer = document.getElementById('qaDrawer');
  drawer.classList.toggle('open', open);
  drawer.setAttribute('aria-hidden', open ? 'false' : 'true');
}

/**
 * 新增一則對話泡泡或輸入中動畫至抽屜。
 * @param {string} role 角色（user 或 ai）。
 * @param {string} text 訊息文字。
 * @param {boolean} [isTyping=false] 是否顯示輸入中跳動圓點。
 * @returns {HTMLDivElement} 建立的訊息元素。
 */
function appendChatMsg(role, text, isTyping = false) {
  const box = document.getElementById('qaMsgs');
  const div = document.createElement('div');
  div.className = `qa-msg ${role}`;
  if (isTyping) {
    div.classList.add('qa-typing');
    div.innerHTML = '<span class="qa-typing-dots"><i></i><i></i><i></i></span><span>Antigravity (agy CLI) 正在規劃分鏡…</span>';
  } else {
    div.textContent = text;
  }
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
  return div;
}

/**
 * 啟動 agy CLI 背景規劃並輪詢顯示串流回覆。
 * @param {string} instruction 使用者規劃指示。
 * @returns {Promise<void>}
 */
async function runAntigravityPlan(instruction) {
  if (!state.currentJob || state.busyPlan) return;
  state.busyPlan = true;
  toggleDrawer(true);
  appendChatMsg('user', instruction || '請依 brief.md 與時間軸規劃本工作分鏡。');
  const typingEl = appendChatMsg('ai', '', true);
  try {
    const mode = document.getElementById('planModeSelect').value;
    const model = document.getElementById('planModelSelect')?.value || '';
    const startRes = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/plan`, {
      method: 'POST',
      body: JSON.stringify({ instruction, mode, model }),
    });
    state.lastPrompt = startRes.prompt || '';
    if (!startRes.available) {
      typingEl.classList.remove('qa-typing');
      typingEl.textContent = `${startRes.error}\n\n可點右上「複製提示詞」貼到 Antigravity App。`;
      return;
    }
    await pollPlanLoop(startRes.run_id, typingEl);
  } catch (err) {
    typingEl.classList.remove('qa-typing');
    typingEl.textContent = `規劃失敗：${err.message}`;
  } finally {
    state.busyPlan = false;
  }
}

/**
 * 輪詢 agy CLI 執行狀態直到完成。
 * @param {string} runId 任務 ID。
 * @param {HTMLDivElement} typingEl 回覆訊息泡泡元素。
 * @returns {Promise<void>}
 */
async function pollPlanLoop(runId, typingEl) {
  while (true) {
    await new Promise(r => setTimeout(r, 1500));
    const st = await api(`/api/plan/${runId}`);
    if (st.output) {
      typingEl.classList.remove('qa-typing');
      typingEl.textContent = st.output + (st.status === 'running' ? '\n\n▌ 規劃中…' : '');
    }
    if (st.status !== 'running') {
      typingEl.classList.remove('qa-typing');
      typingEl.textContent = st.output || st.error || '規劃完成（無文字輸出）';
      await loadJobDetail(state.currentJob);
      break;
    }
  }
}

/**
 * 綁定導覽、工作建立與素材上傳事件。
 * @returns {void}
 */
function bindOverviewEvents() {
  document.querySelectorAll('.dock-btn, .step-chip').forEach(el => el.addEventListener('click', () => switchView(el.dataset.view)));
  document.getElementById('jobSelect').addEventListener('change', e => { state.currentJob = e.target.value; loadJobDetail(state.currentJob); });
  document.getElementById('refreshAllBtn').addEventListener('click', refreshJobs);
  document.getElementById('qaToggleBtn').addEventListener('click', () => toggleDrawer(true));
  document.getElementById('qaCloseBtn').addEventListener('click', () => toggleDrawer(false));
  document.getElementById('copyPromptBtn').addEventListener('click', () => navigator.clipboard.writeText(state.lastPrompt || ''));
  document.getElementById('createJobBtn').addEventListener('click', handleCreateJob);
  document.getElementById('uploadAssetBtn').addEventListener('click', handleUploadAsset);
  document.getElementById('clearStagedBtn')?.addEventListener('click', () => { state.stagedFiles = []; renderStagedFiles(); });
  document.getElementById('assetFileInput')?.addEventListener('change', e => {
    addStagedFiles(e.target.files);
    e.target.value = '';
  });
  const dz = document.getElementById('assetDropzone');
  dz?.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('over'); });
  dz?.addEventListener('dragleave', () => dz.classList.remove('over'));
  dz?.addEventListener('drop', e => {
    e.preventDefault();
    dz.classList.remove('over');
    addStagedFiles(e.dataTransfer?.files);
  });
  document.getElementById('checkJobBtn').addEventListener('click', async () => {
    if (!state.currentJob) return;
    const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/check`);
    document.getElementById('jobCheckLog').textContent = res.output;
  });
}

/**
 * 建立新工作並儲存規劃說明。
 * @returns {Promise<void>}
 */
async function handleCreateJob() {
  const job_type = document.getElementById('newType').value;
  const name = document.getElementById('newName').value.trim();
  const title = document.getElementById('newTitle').value.trim();
  const brief = document.getElementById('newBrief').value;
  const res = await api('/api/jobs', { method: 'POST', body: JSON.stringify({ job_type, name, title }) });
  if (brief.trim()) await api(`/api/jobs/${encodeURIComponent(name)}/brief`, { method: 'PUT', body: JSON.stringify({ content: brief }) });
  document.getElementById('createJobLog').textContent = res.output;
  state.currentJob = name;
  await refreshJobs();
}

/**
 * 將選取或拖曳的檔案累積加入待上傳清單（支援跨資料夾分次選取）。
 * @param {FileList|File[]|null|undefined} fileList 檔案清單。
 * @returns {void}
 */
function addStagedFiles(fileList) {
  for (const f of [...(fileList || [])]) {
    if (!state.stagedFiles.some(x => x.name === f.name && x.size === f.size)) {
      state.stagedFiles.push(f);
    }
  }
  renderStagedFiles();
}

/**
 * 渲染待上傳檔案清單標籤。
 * @returns {void}
 */
function renderStagedFiles() {
  const box = document.getElementById('stagedFilesList');
  if (!box) return;
  if (!state.stagedFiles.length) { box.innerHTML = ''; return; }
  box.innerHTML = state.stagedFiles.map((f, idx) =>
    `<span class="file-chip staged">➕ ${esc(f.name)} <button type="button" onclick="removeStagedFile(${idx})" aria-label="移除">×</button></span>`
  ).join('');
}

/**
 * 從待上傳清單移除指定索引的檔案。
 * @param {number} idx 清單索引。
 * @returns {void}
 */
function removeStagedFile(idx) {
  state.stagedFiles.splice(idx, 1);
  renderStagedFiles();
}

/**
 * 批次上傳待上傳清單內的所有檔案至目前工作的 input/ 目錄。
 * @returns {Promise<void>}
 */
async function handleUploadAsset() {
  if (!state.currentJob) { showToast('請先建立或選擇一個工作', 'warning'); return; }
  if (!state.stagedFiles.length) { showToast('請先選取或拖曳檔案加入清單', 'warning'); return; }
  const files = [...state.stagedFiles];
  const logs = [];
  for (const f of files) {
    const fd = new FormData();
    fd.append('file', f);
    const res = await fetch(`/api/jobs/${encodeURIComponent(state.currentJob)}/upload`, { method: 'POST', body: fd });
    const data = await res.json().catch(() => ({}));
    logs.push(data.output || data.detail || `${f.name}: HTTP ${res.status}`);
  }
  state.stagedFiles = [];
  renderStagedFiles();
  document.getElementById('jobCheckLog').textContent = logs.join('\n');
  showToast(`已批次上傳 ${files.length} 個檔案至 input/`, 'success');
  await loadJobDetail(state.currentJob);
}

/**
 * 綁定設定分頁表單儲存事件。
 * @returns {void}
 */
function bindSettingsEvents() {
  document.getElementById('saveJobConfigBtn').addEventListener('click', handleSaveJobConfig);
  document.getElementById('saveScriptBtn').addEventListener('click', () => saveScript(false));
  document.getElementById('formatScriptBtn').addEventListener('click', () => saveScript(true));
  document.getElementById('saveBriefBtn').addEventListener('click', async () => {
    const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/brief`, {
      method: 'PUT', body: JSON.stringify({ content: document.getElementById('briefEditor').value }),
    });
    showToast(res.output || '已儲存 brief.md', 'success');
  });
  document.getElementById('cfgVoiceLanguage')?.addEventListener('change', e => {
    const defaults = { zh: 'zh-TW-HsiaoChenNeural', en: 'en-US-AriaNeural', ja: 'ja-JP-NanamiNeural', ko: 'ko-KR-SunHiNeural' };
    if (defaults[e.target.value]) document.getElementById('cfgEdgeVoice').value = defaults[e.target.value];
    if (e.target.value === 'en') document.getElementById('cfgBilingualSubtitles').value = 'true';
  });
  document.getElementById('draftScriptBtn')?.addEventListener('click', handleDraftScript);
  document.getElementById('loadReviewScriptBtn')?.addEventListener('click', handleLoadReviewScript);
  document.getElementById('approveScriptBtn')?.addEventListener('click', () => approveReviewFile('script.md'));
  document.getElementById('translateBilingualBtn')?.addEventListener('click', handleTranslateBilingual);
  document.getElementById('saveVocabBtn').addEventListener('click', handleSaveVocab);
  document.getElementById('saveEnvBtn').addEventListener('click', handleSaveEnv);
}

/**
 * 儲存 job.toml 設定。
 * @returns {Promise<void>}
 */
async function handleSaveJobConfig() {
  if (!state.currentJob) return;
  const payload = {
    title: document.getElementById('cfgTitle').value,
    visual_mode: document.getElementById('cfgVisualMode').value,
    voice_engine: document.getElementById('cfgVoiceEngine').value,
    voice_language: document.getElementById('cfgVoiceLanguage').value,
    voice_profile: document.getElementById('cfgVoiceProfile').value,
    edge_voice: document.getElementById('cfgEdgeVoice').value,
    edge_rate: document.getElementById('cfgEdgeRate').value,
    prosody_preset: document.getElementById('cfgProsodyPreset').value,
    whisper_model: document.getElementById('cfgWhisperModel').value,
    opencc_mode: document.getElementById('cfgOpenccMode').value,
    loudness: Number(document.getElementById('cfgLoudness').value || -16),
    fps: Number(document.getElementById('cfgFps').value || 30),
    burn_in: document.getElementById('cfgBurnIn').value === 'true',
    bilingual_subtitles: document.getElementById('cfgBilingualSubtitles').value === 'true',
    subtitle_secondary_lang: document.getElementById('cfgSubtitleSecondaryLang').value,
    subtitle_font_size: Number(document.getElementById('cfgSubtitleFontSize').value || 22),
    avatar_engine: document.getElementById('cfgAvatarEngine').value,
    avatar_image: document.getElementById('cfgAvatarImage').value.trim(),
    avatar_position: document.getElementById('cfgAvatarPosition').value,
    backup_dir: document.getElementById('cfgBackupDir').value,
    inputs: {
      script: document.getElementById('cfgInScript').value,
      pptx: document.getElementById('cfgInPptx').value,
      poster: document.getElementById('cfgInPoster').value,
      scenes: document.getElementById('cfgInScenes').value,
    },
  };
  const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/config`, { method: 'PUT', body: JSON.stringify(payload) });
  showToast(res.output || '已儲存 job.toml 設定', 'success');
}

/**
 * 儲存講稿並選擇是否自動斷句。
 * @param {boolean} autoFormat 是否自動斷句。
 * @returns {Promise<void>}
 */
async function saveScript(autoFormat) {
  const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/script`, {
    method: 'PUT', body: JSON.stringify({ content: document.getElementById('scriptEditor').value, auto_format: autoFormat }),
  });
  if (autoFormat) {
    document.getElementById('scriptEditor').value = res.content;
    if (typeof renderProsodyHighlights === 'function') renderProsodyHighlights();
  }
  showToast(res.output || '已儲存講稿', 'success');
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
 * 儲存全域 .env 設定。
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
  showToast(res.output || '已儲存全域設定', 'success');
}

/**
 * 綁定配音、AI 規劃、審核與渲染按鈕事件。
 * @returns {void}
 */
function bindWorkflowEvents() {
  document.getElementById('prosodyPreviewBtn')?.addEventListener('click', handleProsodyPreview);
  document.getElementById('buildNarrationBtn').addEventListener('click', async () => {
    const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/narrate/build`, { method: 'POST' });
    document.getElementById('narrateLog').textContent = res.output;
  });
  document.getElementById('calcTimingBtn').addEventListener('click', async () => {
    const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/video/timing`);
    document.getElementById('narrateLog').textContent = res.output;
  });
  document.getElementById('runAgyPlanBtn').addEventListener('click', () => runAntigravityPlan(document.getElementById('planInstruction').value));
  document.getElementById('qaSendBtn').addEventListener('click', () => {
    const input = document.getElementById('qaInput');
    const txt = input.value.trim();
    if (!txt) return;
    input.value = '';
    runAntigravityPlan(txt);
  });
  document.getElementById('qaInput').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); document.getElementById('qaSendBtn').click(); }
  });
  document.getElementById('previewReviewHtmlBtn').addEventListener('click', () => {
    if (state.currentJob) document.getElementById('reviewPreviewFrame').src = `/api/jobs/${encodeURIComponent(state.currentJob)}/review/index.html?t=${Date.now()}`;
  });
  document.getElementById('approveHtmlBtn').addEventListener('click', () => approveReviewFile('index.html'));
  document.getElementById('approveScenesBtn').addEventListener('click', () => approveReviewFile('scenes.toml'));
  document.getElementById('renderHtmlBtn').addEventListener('click', () => runRenderEndpoint('html'));
  document.getElementById('renderPosterBtn').addEventListener('click', () => runRenderEndpoint('poster'));
  document.getElementById('previewAvatarAbBtn')?.addEventListener('click', handlePreviewAvatarAb);
  document.getElementById('applyAvatarBtn')?.addEventListener('click', handleApplyAvatar);
  document.getElementById('checkVideoBtn').addEventListener('click', async () => {
    const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/video/check`);
    document.getElementById('renderLog').textContent = res.output;
  });
}

/**
 * 核可 review/ 草稿並移入 input/。
 * @param {string} filename 檔案名稱。
 * @returns {Promise<void>}
 */
async function approveReviewFile(filename) {
  const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/approve`, {
    method: 'POST', body: JSON.stringify({ filename }),
  });
  showToast(res.output || `已核可 ${filename}`, 'success');
  await loadJobDetail(state.currentJob);
}

/**
 * 觸發影片渲染並重新載入成品預覽。
 * @param {string} mode 渲染模式（html 或 poster）。
 * @returns {Promise<void>}
 */
async function runRenderEndpoint(mode) {
  const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/video/${mode}`, {
    method: 'POST', body: JSON.stringify({}),
  });
  document.getElementById('renderLog').textContent = res.output;
  await loadJobDetail(state.currentJob);
}

/**
 * 依使用者指令呼叫 AI 起草講稿並寫入 review/script.md。
 * @returns {Promise<void>}
 */
async function handleDraftScript() {
  if (!state.currentJob) return;
  showToast('正在以 agy CLI 生成講稿草稿…', 'info', 3500);
  const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/script/draft`, {
    method: 'POST',
    body: JSON.stringify({
      instruction: document.getElementById('scriptDraftInstruction').value,
      language: document.getElementById('cfgVoiceLanguage').value,
      duration_sec: Number(document.getElementById('scriptDraftDuration').value || 90),
      model: document.getElementById('planModelSelect')?.value || '',
    }),
  });
  document.getElementById('scriptEditor').value = res.content || '';
  if (typeof renderProsodyHighlights === 'function') renderProsodyHighlights();
  showToast(res.output || '已生成講稿草稿至 review/script.md，可修改後核可', 'success', 3200);
}

/**
 * 載入 review/script.md 到講稿編輯區供修改。
 * @returns {Promise<void>}
 */
async function handleLoadReviewScript() {
  if (!state.currentJob) return;
  const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/review-script`);
  if (!res.exists) { showToast('尚無 review/script.md 草稿', 'warning'); return; }
  document.getElementById('scriptEditor').value = res.content;
  if (typeof renderProsodyHighlights === 'function') renderProsodyHighlights();
  showToast('已載入 review/script.md，修改後可儲存或核可', 'info');
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
      model: document.getElementById('planModelSelect')?.value || '',
    }),
  });
  showToast(res.output || '已完成雙語翻譯', 'success');
}

/**
 * 依設定的 Avatar 引擎（路線 A SadTalker 或路線 B FFmpeg）合成講者頭像至最新影片。
 * @returns {Promise<void>}
 */
async function handleApplyAvatar() {
  if (!state.currentJob) return;
  const engine = document.getElementById('cfgAvatarEngine').value;
  if (engine === 'none') { showToast('請先於「2. 完整設定」選擇路線 A 或路線 B Avatar 模式', 'warning'); return; }
  showToast(`正在合成 ${engine} Avatar 講者頭像…`, 'info', 4000);
  const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/video/avatar`, {
    method: 'POST',
    body: JSON.stringify({
      engine,
      position: document.getElementById('cfgAvatarPosition').value,
      image_name: document.getElementById('cfgAvatarImage').value.trim(),
    }),
  });
  document.getElementById('renderLog').textContent = res.output;
  showToast('Avatar 合成完成！', 'success');
  await loadJobDetail(state.currentJob);
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

/**
 * 產生 10 秒 Avatar 路線 A 與路線 B 並排預覽供選擇。
 * @returns {Promise<void>}
 */
async function handlePreviewAvatarAb() {
  if (!state.currentJob) return;
  showToast('正在產生 10 秒 Avatar 路線 A/B 對比預覽（路線 A 若執行中約需 30-90 秒）…', 'info', 5000);
  const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/video/avatar-preview`, {
    method: 'POST', body: JSON.stringify({ image_name: document.getElementById('cfgAvatarImage').value.trim() }),
  });
  const box = document.getElementById('avatarAbBox');
  box.style.display = 'grid';
  const bUrl = `/api/jobs/${encodeURIComponent(state.currentJob)}/review/${encodeURIComponent(res.route_b_file)}?t=${Date.now()}`;
  const aHtml = res.route_a_file
    ? `<video class="player" controls src="/api/jobs/${encodeURIComponent(state.currentJob)}/review/${encodeURIComponent(res.route_a_file)}?t=${Date.now()}"></video>
       <button type="button" class="btn btn-sm" onclick="selectAvatarEngine('sadtalker')">採用路線 A</button>`
    : `<p class="muted">${esc(res.route_a_error || '路線 A 尚未就緒')}</p>`;
  box.innerHTML = `
    <div class="card"><strong>路線 B：輕量動態頭像 (FFmpeg)</strong><video class="player" controls src="${bUrl}"></video>
      <button type="button" class="btn btn-soft btn-sm" onclick="selectAvatarEngine('lightweight')">採用路線 B</button></div>
    <div class="card"><strong>路線 A：SadTalker AI 對嘴</strong>${aHtml}</div>`;
  showToast(res.output, 'success');
}

/**
 * 選定 Avatar 路線並儲存設定。
 * @param {'lightweight'|'sadtalker'} engine 選定的引擎。
 * @returns {Promise<void>}
 */
async function selectAvatarEngine(engine) {
  document.getElementById('cfgAvatarEngine').value = engine;
  await handleSaveJobConfig();
}

initTheme();
bindOverviewEvents();
bindSettingsEvents();
bindWorkflowEvents();
refreshJobs().catch(err => { document.getElementById('healthBadge').textContent = `錯誤：${err.message}`; });
