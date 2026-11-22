/* 用途：Web Studio 事件綁定與工作操作處理（建立工作、上傳、設定儲存、AI 起草講稿與 Avatar 合成）。 */

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
  document.getElementById('resetNewJobBtn')?.addEventListener('click', () => {
    ['newName', 'newTitle', 'newBrief'].forEach(id => {
      document.getElementById(id).value = '';
      localStorage.removeItem(`vs.draft.${id}`);
    });
    showToast('已清空 Step 1 欄位，可建立新工作', 'info', 1800);
  });
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
  if (!name) { showToast('請先填寫英文代號 (slug)', 'warning'); return; }
  let outMsg = '';
  if (state.jobs.includes(name)) {
    const res = await api(`/api/jobs/${encodeURIComponent(name)}/brief`, { method: 'PUT', body: JSON.stringify({ content: brief }) });
    outMsg = res.output || `已更新 ${name}/input/brief.md`;
    showToast(`已更新工作 ${name} 說明`, 'success');
  } else {
    const res = await api('/api/jobs', { method: 'POST', body: JSON.stringify({ job_type, name, title }) });
    if (brief.trim()) await api(`/api/jobs/${encodeURIComponent(name)}/brief`, { method: 'PUT', body: JSON.stringify({ content: brief }) });
    outMsg = res.output;
    showToast(`已建立工作 ${name}`, 'success');
  }
  document.getElementById('createJobLog').textContent = outMsg;
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
    if (typeof filterVoicesByLanguage === 'function') filterVoicesByLanguage();
    if (typeof prewarmVoiceSamples === 'function') prewarmVoiceSamples();
    syncConfigVisibility();
  });
  document.getElementById('cfgVoiceEngine')?.addEventListener('change', syncConfigVisibility);
  document.getElementById('cfgAvatarEngine')?.addEventListener('change', syncConfigVisibility);
  document.getElementById('cfgBilingualSubtitles')?.addEventListener('change', syncConfigVisibility);
  document.getElementById('cfgProsodyPreset')?.addEventListener('change', () => handleSaveJobConfig());
  if (typeof filterVoicesByLanguage === 'function') filterVoicesByLanguage();
  if (typeof prewarmVoiceSamples === 'function') prewarmVoiceSamples();
  syncConfigVisibility();
  document.getElementById('draftScriptBtn')?.addEventListener('click', handleDraftScript);
  document.getElementById('loadReviewScriptBtn')?.addEventListener('click', handleLoadReviewScript);
  document.getElementById('approveScriptBtn')?.addEventListener('click', () => approveReviewFile('script.md'));
  document.getElementById('translateBilingualBtn')?.addEventListener('click', handleTranslateBilingual);
  document.getElementById('saveVocabBtn').addEventListener('click', handleSaveVocab);
  document.getElementById('saveEnvBtn').addEventListener('click', handleSaveEnv);
}

/**
 * 依選擇的配音引擎、雙語字幕與 Avatar 開關，動態顯示或隱藏對應欄位。
 * @returns {void}
 */
function syncConfigVisibility() {
  const voiceEngine = document.getElementById('cfgVoiceEngine')?.value || 'voicebox';
  const avatarEngine = document.getElementById('cfgAvatarEngine')?.value || 'none';
  const bilingual = document.getElementById('cfgBilingualSubtitles')?.value === 'true';
  document.querySelectorAll('.cfg-voicebox-only').forEach(el => el.classList.toggle('is-hidden', voiceEngine !== 'voicebox'));
  document.querySelectorAll('.cfg-edgetts-only').forEach(el => el.classList.toggle('is-hidden', voiceEngine !== 'edge-tts'));
  document.querySelectorAll('.cfg-avatar-only').forEach(el => el.classList.toggle('is-hidden', avatarEngine === 'none'));
  document.querySelectorAll('.cfg-bilingual-only').forEach(el => el.classList.toggle('is-hidden', !bilingual));
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
    lead_in_sec: Number(document.getElementById('cfgLeadInSec')?.value ?? 2.0),
    whisper_model: document.getElementById('cfgWhisperModel').value,
    opencc_mode: document.getElementById('cfgOpenccMode').value,
    width: Number(document.getElementById('cfgWidth')?.value || 1920),
    height: Number(document.getElementById('cfgHeight')?.value || 1080),
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
 * 綁定配音、AI 規劃、審核與渲染按鈕事件。
 * @returns {void}
 */
function bindWorkflowEvents() {
  document.getElementById('prosodyPreviewBtn')?.addEventListener('click', handleProsodyPreview);
  document.getElementById('buildNarrationBtn').addEventListener('click', async () => {
    if (!state.currentJob) return;
    document.getElementById('narrateLog').textContent = '⏳ 正在生成配音與雙語字幕（需依序合成每句並跑 Whisper 對齊），請稍候…';
    showToast('已開始生成配音與字幕，請稍候', 'info', 3500);
    try {
      const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/narrate/build`, { method: 'POST' });
      document.getElementById('narrateLog').textContent = res.output;
      showToast('配音與字幕生成完成！', 'success');
    } catch (err) {
      document.getElementById('narrateLog').textContent = `錯誤：${err.message}`;
      showToast(`配音失敗：${err.message}`, 'error', 4000);
    }
  });
  document.getElementById('calcTimingBtn').addEventListener('click', async () => {
    if (!state.currentJob) return;
    document.getElementById('narrateLog').textContent = '⏳ 正在計算每段秒數…';
    const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/video/timing`);
    document.getElementById('narrateLog').textContent = res.output;
    showToast('已計算投影片秒數', 'success');
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
      model: document.getElementById('scriptModelSelect')?.value || '',
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
