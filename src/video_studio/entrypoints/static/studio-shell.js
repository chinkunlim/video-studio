/* 用途：提供素材選單填入、語言聲線聯動預熱、依用途上傳與工作室外殼控制。 */

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
      statusEl.textContent = '試聽準備中，請稍候再點試聽';
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
