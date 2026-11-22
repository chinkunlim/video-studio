/**
 * @fileoverview 定稿發布（output/<job>/releases/）UI 控制模組。
 */

/**
 * 更新定稿版本下拉選單與目前發布狀態徽章。
 * @param {object} d 工作詳情物件。
 * @returns {void}
 */
function updateReleaseUI(d) {
  const sel = document.getElementById('releaseVersionSelect');
  const badge = document.getElementById('publishedReleaseBadge');
  const versions = d.output_versions || [];
  if (sel) {
    sel.innerHTML = versions.length
      ? versions.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join('')
      : '<option value="">無可用版本</option>';
    if (d.published_release?.version && versions.includes(d.published_release.version)) {
      sel.value = d.published_release.version;
    }
  }
  if (badge) {
    badge.textContent = d.published_release
      ? `已發布定稿：${d.published_release.version} (${d.published_release.files.length} 檔)`
      : '尚未發布定稿';
    badge.title = d.published_release ? d.published_release.release_dir : '';
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('publishReleaseBtn')?.addEventListener('click', async () => {
    if (!state.currentJob) return;
    const version = document.getElementById('releaseVersionSelect')?.value || null;
    const res = await api(`/api/jobs/${encodeURIComponent(state.currentJob)}/video/publish`, {
      method: 'POST',
      body: JSON.stringify({ version }),
    });
    document.getElementById('renderLog').textContent = res.output;
    showToast('已發布定稿至 releases/', 'success');
    await selectJob(state.currentJob);
  });
});
