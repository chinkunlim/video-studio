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

  const rows = (jobsRes.output || '')
    .split('\n')
    .map(l => l.trim().match(/^(generate|dub|extract)\s+([A-Za-z0-9._-]+)(?:\s+(.*))?$/))
    .filter(Boolean)
    .map(m => ({ type: m[1], name: m[2], meta: (m[3] || '').trim() }));
  const names = rows.map(r => r.name);
  state.jobs = names;
  const sel = document.getElementById('jobSelect');
  const prev = state.currentJob || sel.value;
  sel.innerHTML = names.length ? names.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('') : '<option value="">尚無專案</option>';
  if (names.includes(prev)) sel.value = prev;
  state.currentJob = sel.value;
  const grid = document.getElementById('projectCardsGrid');
  if (grid) {
    grid.innerHTML = rows.length
      ? rows.map(r => {
          const on = r.name === state.currentJob ? ' on' : '';
          return `<button type="button" class="proj-card${on}" data-proj="${esc(r.name)}"><div class="proj-card-head"><span>${esc(r.name)}</span><span class="pill">${esc(r.type)}</span></div><div class="muted">${esc(r.meta || '點擊載入專案')}</div></button>`;
        }).join('')
      : '<span class="muted">尚無專案，請點右上「＋ 建立新專案」。</span>';
    grid.querySelectorAll('[data-proj]').forEach(btn => {
      btn.addEventListener('click', () => {
        state.currentJob = btn.dataset.proj;
        sel.value = state.currentJob;
        loadJobDetail(state.currentJob);
        refreshJobs();
      });
    });
  }
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
      ? d.input_files.map(f => `<span class="file-chip">${esc(f)}</span>`).join('')
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
  const leadEl = document.getElementById('cfgLeadInSec');
  if (leadEl) leadEl.value = c.voice?.lead_in_sec ?? 2.0;
  document.getElementById('cfgWhisperModel').value = c.whisper?.model || 'small';
  document.getElementById('cfgOpenccMode').value = c.whisper?.opencc_mode || 's2tw';
  document.getElementById('cfgWidth').value = c.output?.width ?? 1920;
  document.getElementById('cfgHeight').value = c.output?.height ?? 1080;
  if (typeof syncAspectPresetFromInputs === 'function') syncAspectPresetFromInputs();
  document.getElementById('cfgLoudness').value = c.output?.loudness ?? -16;
  document.getElementById('cfgFps').value = c.output?.fps ?? 30;
  document.getElementById('cfgBurnIn').value = String(c.subtitles?.burn_in ?? true);
  document.getElementById('cfgBilingualSubtitles').value = String(c.subtitles?.bilingual ?? false);
  document.getElementById('cfgSubtitleSecondaryLang').value = c.subtitles?.secondary_lang || 'zh-TW';
  document.getElementById('cfgSubtitleFontSize').value = c.subtitles?.font_size ?? 22;
  document.getElementById('cfgAvatarEngine').value = c.avatar?.engine || 'none';
  document.getElementById('cfgAvatarPosition').value = c.avatar?.position || 'bottom-right';
  document.getElementById('cfgBackupDir').value = c.output?.backup_dir || '';
  if (typeof populateInputFileSelects === 'function') populateInputFileSelects(d, c);
  document.getElementById('scriptEditor').value = d.script || '';
  if (typeof renderProsodyHighlights === 'function') renderProsodyHighlights();
  document.getElementById('briefEditor').value = d.brief || '';
  const draftName = localStorage.getItem('vs.draft.newName');
  if (!draftName || draftName === d.name) {
    document.getElementById('newType').value = d.type || 'generate';
    document.getElementById('newName').value = d.name || '';
    document.getElementById('newTitle').value = d.title || '';
    document.getElementById('newBrief').value = d.brief || '';
  }
  if (typeof filterVoicesByLanguage === 'function') filterVoicesByLanguage();
  if (typeof prewarmVoiceSamples === 'function') prewarmVoiceSamples();
  syncConfigVisibility();
  loadBilingualPreview(name);
  updateMediaPreview(name, d.latest_version, d.latest_files);
  const narrEl = document.getElementById('narrateLog');
  if (narrEl) {
    narrEl.textContent = d.latest_version && d.latest_files.includes('narration.wav')
      ? `已產出最新配音與字幕 (${d.latest_version})：\n${d.latest_files.join(', ')}`
      : '尚未執行';
  }
  const rendEl = document.getElementById('renderLog');
  if (rendEl) {
    const hasVid = d.latest_files.includes('video_subtitled.mp4') || d.latest_files.includes('video.mp4');
    rendEl.textContent = d.latest_version && hasVid
      ? `已產出最新影片 (${d.latest_version})：\n${d.latest_files.join(', ')}`
      : '尚未渲染';
  }
  if (typeof updateReleaseUI === 'function') updateReleaseUI(d);
  if (typeof resumeActivePlanIfAny === 'function') {
    resumeActivePlanIfAny(name);
  }
  if (typeof refreshReviewSnapshots === 'function') {
    refreshReviewSnapshots(name);
  }
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
  let nextPath = '';
  if (v && files.includes('video_subtitled.mp4')) {
    nextPath = `/api/jobs/${encodeURIComponent(name)}/output/${v}/video_subtitled.mp4`;
  } else if (v && files.includes('video.mp4')) {
    nextPath = `/api/jobs/${encodeURIComponent(name)}/output/${v}/video.mp4`;
  }
  if (nextPath) {
    if (player.dataset.baseSrc !== nextPath) {
      player.dataset.baseSrc = nextPath;
      player.src = `${nextPath}?t=${Date.now()}`;
    }
  } else {
    player.dataset.baseSrc = '';
    player.removeAttribute('src');
  }
  if (v && files.includes('video_contact_sheet.jpg')) {
    const sheetPath = `/api/jobs/${encodeURIComponent(name)}/output/${v}/video_contact_sheet.jpg`;
    if (sheet.dataset.baseSrc !== sheetPath) {
      sheet.dataset.baseSrc = sheetPath;
      sheet.src = `${sheetPath}?t=${Date.now()}`;
    }
  } else {
    sheet.dataset.baseSrc = '';
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
  document.body.classList.toggle('qa-open', open);
  drawer.setAttribute('aria-hidden', open ? 'false' : 'true');
  if (typeof fitReviewPreviewFrame === 'function') setTimeout(fitReviewPreviewFrame, 260);
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
  const userText = instruction || '請依 brief.md 與時間軸規劃本工作分鏡。';
  appendChatMsg('user', userText);
  const typingEl = appendChatMsg('ai', '', true);
  try {
    const mode = document.getElementById('planModeSelect').value;
    const model = document.getElementById('planModelSelect')?.value || '';
    const follow_poster_design = document.getElementById('planFollowPoster')?.value !== 'false';
    const thread_mode = state.qaThreadMode || 'continue';
    const history = (state.qaHistory || []).slice(-6);
    state.qaHistory = [...(state.qaHistory || []), { role: 'user', text: userText }];
    const startRes = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/plan`, {
      method: 'POST',
      body: JSON.stringify({ instruction, mode, model, follow_poster_design, thread_mode, history }),
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
      const finalOut = st.output || st.error || '規劃完成（無文字輸出）';
      typingEl.textContent = finalOut;
      state.qaHistory = [...(state.qaHistory || []), { role: 'ai', text: finalOut }];
      await loadJobDetail(state.currentJob);
      break;
    }
  }
}

initTheme();
bindOverviewEvents();
bindSettingsEvents();
bindWorkflowEvents();
refreshJobs().catch(err => { document.getElementById('healthBadge').textContent = `錯誤：${err.message}`; });
