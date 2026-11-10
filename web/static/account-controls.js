const isAccountAdmin = document.body.dataset.role === 'admin';
const nativeFetch = window.fetch.bind(window);
window.fetch = async (url, options = {}) => {
  const target = new URL(url, location.href);
  if (target.origin !== location.origin || !target.pathname.startsWith('/api/')) {
    return nativeFetch(url, options);
  }
  const headers = new Headers(options.headers);
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes((options.method || 'GET').toUpperCase())) {
    headers.set('X-CSRF-Token', document.body.dataset.csrf);
  }
  const response = await nativeFetch(url, {...options, headers});
  if (response.status === 401) location.replace('/login');
  return response;
};
document.getElementById('logout-btn').addEventListener('click', async () => {
  try {
    const response = await fetch('/api/auth/logout', {method: 'POST'});
    if (!response.ok) throw new Error();
    location.replace('/login');
  } catch {
    alert('退出失败，请重试。');
  }
});

const auditDialog = document.getElementById('audit-dialog');
if (auditDialog) {
  const list = document.getElementById('audit-events');
  const more = document.getElementById('audit-more');
  const status = document.getElementById('audit-status');
  const labels = {create: '上报', status: '改状态', update: '修改', delete: '删除',
    reset_password: '重置密码', rotate_invite: '轮换邀请码', migrate_reporters: '补登记上报人'};
  const filters = document.getElementById('audit-filters');
  let query = new URLSearchParams();
  let cursor;
  let loadId = 0;

  async function loadAudit() {
    const id = ++loadId;
    more.disabled = true;
    list.setAttribute('aria-busy', 'true');
    status.textContent = '加载中…';
    try {
      const params = new URLSearchParams(query);
      if (cursor) params.set('cursor', cursor);
      const response = await fetch('/api/audit?' + params);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '日志加载失败，请重试。');
      if (id !== loadId) return;
      for (const event of data.events) {
        const item = document.createElement('tr');
        const change = event.from != null && event.to != null
          ? formatValue(event.from) + ' → ' + formatValue(event.to)
          : event.changes ? Object.entries(event.changes).map(([field, value]) =>
            `${field}：${formatValue(value.from)} → ${formatValue(value.to)}`).join('；')
          : [event.detail, event.fields?.join('、'), event.reporter,
            event.record_ids?.join('、'), event.role, event.target_user_id].filter(Boolean).join(' · ') || '—';
        const values = [new Date(event.t).toLocaleString('zh-CN'), event.user || '—',
          labels[event.action] || event.action,
          [event.record_id, event.room].filter(Boolean).join(' / ') || '—', change];
        for (const value of values) {
          const cell = document.createElement('td');
          cell.textContent = value;
          item.append(cell);
        }
        list.append(item);
      }
      cursor = data.next_cursor;
      more.hidden = !cursor;
      more.textContent = '加载更多';
      status.textContent = list.children.length ? `已显示 ${list.children.length} 条日志${cursor ? '' : '，已加载全部结果'}` : '暂无符合条件的操作日志。';
    } catch (error) {
      if (id === loadId) {
        status.textContent = error.message || '日志加载失败，请重试。';
        more.hidden = false;
        more.textContent = '重试加载';
      }
    } finally {
      if (id === loadId) {
        more.disabled = false;
        list.setAttribute('aria-busy', 'false');
      }
    }
  }

  function formatValue(value) {
    return typeof value === 'object' ? JSON.stringify(value) : String(value);
  }

  function refreshAudit() {
    const start = filters.elements.namedItem('start');
    const end = filters.elements.namedItem('end');
    end.setCustomValidity(start.value && end.value && start.value > end.value
      ? '结束日期不能早于开始日期' : '');
    if (!filters.reportValidity()) return;
    query = new URLSearchParams(new FormData(filters));
    cursor = null;
    list.replaceChildren();
    more.hidden = true;
    loadAudit();
  }
  filters.addEventListener('input', () => filters.elements.namedItem('end').setCustomValidity(''));
  filters.addEventListener('submit', event => {
    event.preventDefault();
    refreshAudit();
  });
  filters.addEventListener('reset', () => setTimeout(refreshAudit, 0));
  document.getElementById('audit-btn').addEventListener('click', () => {
    cursor = null;
    list.replaceChildren();
    more.hidden = true;
    auditDialog.showModal();
    refreshAudit();
  });
  more.addEventListener('click', loadAudit);
}
