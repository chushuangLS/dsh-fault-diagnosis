/* ============================================================
   机房故障智能诊断助手 - 前端逻辑
   ============================================================ */

const $ = (sel) => document.querySelector(sel);

/* ============================================================
   落地页 ↔ 主应用 切换
   ============================================================ */
const landingEl = $('#landing');
const appEl = $('#app');
let currentView = 'chat';

function enterApp(view) {
  animateNumbersReset();
  landingEl.classList.add('exit');
  setTimeout(() => {
    landingEl.classList.add('hidden');
    appEl.classList.remove('hidden');
    switchView(view || 'chat');
    // 元素此时才可见，offsetWidth 才有值
    requestAnimationFrame(() => movePillIndicator());
  }, 380);
}

function backToLanding() {
  appEl.classList.add('hidden');
  landingEl.classList.remove('hidden', 'exit');
  // 重新触发入场动画
  landingEl.style.animation = 'none';
  void landingEl.offsetWidth;
  landingEl.style.animation = '';
  loadLandingStats();
}

// 落地页卡片点击
document.querySelectorAll('.entry-card').forEach(card => {
  card.addEventListener('click', () => enterApp(card.dataset.goto));
});

// 点击 Logo 返回首页
$('#brand-home').addEventListener('click', backToLanding);

/* ============================================================
   视图切换
   ============================================================ */
function switchView(view) {
  currentView = view;

  document.querySelectorAll('.pill-item').forEach(t => {
    t.classList.toggle('active', t.dataset.view === view);
  });

  // 滑动指示器跟随
  movePillIndicator();

  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  const target = $('#view-' + view);
  if (target) target.classList.add('active');

  if (view === 'records') loadRecords();
  if (view === 'stats') loadStats();
  if (view === 'tasks') loadTasks();
  if (view === 'chat') {
    const inp = $('#input');
    if (inp) setTimeout(() => inp.focus(), 100);
  }
  updateDrawer();
}

/**
 * 把指示器移动到当前选中项的位置和宽度
 */
function movePillIndicator() {
  const track = $('#pill-track');
  const indicator = $('#pill-indicator');
  if (!track || !indicator) return;

  const active = track.querySelector('.pill-item.active');
  if (!active) return;

  // 首次调用时禁用过渡，避免从初始位置滑入
  const first = indicator.dataset.init !== '1';

  indicator.style.width = active.offsetWidth + 'px';
  indicator.style.transform = `translateX(${active.offsetLeft - 5}px)`;

  if (first) {
    indicator.style.transition = 'none';
    indicator.dataset.init = '1';
    requestAnimationFrame(() => {
      indicator.style.transition = '';
    });
  }
}

document.querySelectorAll('.pill-item').forEach(item => {
  item.addEventListener('click', () => switchView(item.dataset.view));
});

// 窗口尺寸变化时重新定位指示器
window.addEventListener('resize', () => movePillIndicator());

/* ============================================================
   右侧抽屉
   ============================================================ */
const drawerEl = $('#drawer');
const handleEl = $('#drawer-handle');
// 遮罩直接使用 HTML 中定义的元素（它在 #app 内部，与 .drawer 同层叠上下文）
const maskEl = $('#drawer-mask');

function openDrawer() {
  drawerEl.classList.add('open');
  maskEl.classList.add('show');
  document.body.classList.add('drawer-open');
  updateDrawer();
}
function closeDrawer() {
  drawerEl.classList.remove('open');
  maskEl.classList.remove('show');
  document.body.classList.remove('drawer-open');
}

handleEl.addEventListener('click', () => {
  drawerEl.classList.contains('open') ? closeDrawer() : openDrawer();
});
$('#drawer-close').addEventListener('click', closeDrawer);
maskEl.addEventListener('click', closeDrawer);

// 抽屉内快捷按钮
document.querySelectorAll('.drawer-btn[data-goto]').forEach(btn => {
  btn.addEventListener('click', () => {
    switchView(btn.dataset.goto);
    closeDrawer();
  });
});
$('#d-reset').addEventListener('click', () => {
  closeDrawer();
  resetSession();
});

// ESC 关闭抽屉
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeDrawer();
});

/* ============================================================
   抽屉内容更新
   ============================================================ */
let sessionRounds = 0;

function updateDrawer() {
  loadRecentRecords();
  refreshDrawerStats();
}

let currentClassroom = '';
let sessionState = '待开始';

async function loadRecentRecords() {
  const box = $('#d-recent');
  try {
    const res = await fetch('/api/records');
    const data = await res.json();
    if (data.error || !data.records.length) {
      box.innerHTML = '<div class="recent-empty">暂无记录</div>';
      return;
    }

    const statusClass = { '未报修': 'pending', '已报修': 'reported', '已解决': 'resolved' };
    box.innerHTML = data.records.slice(0, 5).map(r => `
      <div class="recent-item ${statusClass[r['状态']] || ''}">
        <div class="ri-top">
          <span class="ri-id">${escapeHtml(r['记录编号'])}</span>
          <span class="ri-room">${escapeHtml(r['教室'])}</span>
        </div>
        <div class="ri-sym">${escapeHtml(r['故障现象'])}</div>
      </div>
    `).join('');
  } catch {
    box.innerHTML = '<div class="recent-empty">读取失败</div>';
  }
}

/* ============================================================
   落地页统计
   ============================================================ */
async function loadLandingStats() {
  try {
    const res = await fetch('/api/statistics');
    const d = await res.json();
    if (d.error) return;
    animateNumber($('#ls-total'), d.total);
    animateNumber($('#ls-pending'), d.by_status['未报修'] || 0);
    $('#ls-rate').textContent = d.resolve_rate + '%';
  } catch { /* 忽略 */ }
}

function animateNumber(el, target) {
  if (!el) return;
  const start = 0;
  const duration = 700;
  const t0 = performance.now();
  function step(now) {
    const p = Math.min((now - t0) / duration, 1);
    const eased = 1 - Math.pow(1 - p, 3);
    el.textContent = Math.round(start + (target - start) * eased);
    if (p < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

function animateNumbersReset() {
  ['#ls-total', '#ls-pending'].forEach(s => {
    const el = $(s);
    if (el) el.textContent = '0';
  });
}

// ---------------- 聊天（流式 + 历史累积）----------------
const messagesEl = $('#messages');
const inputEl = $('#input');
const sendBtn = $('#send');
const scrollBottomBtn = $('#scroll-bottom');

let busy = false;
let msgCount = 0;

// 当前时间字符串
function nowTime() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/**
 * 新增一条消息
 * @param {string} text 内容
 * @param {'bot'|'user'} who 发送方
 * @param {boolean} isConclusion 是否为诊断结论
 * @returns 正文 DOM 元素（供流式追加）
 */
function addTurn(text, who, isConclusion = false) {
  msgCount++;

  const wrap = document.createElement('div');
  wrap.className = 'turn ' + who + (isConclusion ? ' conclusion' : '');

  const head = document.createElement('div');
  head.className = 'turn-head';

  const name = document.createElement('span');
  name.className = 'turn-name';
  name.textContent = who === 'user' ? '我' : '机房运维助手';

  const time = document.createElement('span');
  time.className = 'turn-time';
  time.textContent = nowTime();

  head.appendChild(name);
  head.appendChild(time);

  const body = document.createElement('div');
  body.className = 'turn-body';
  body.textContent = text || '';

  wrap.appendChild(head);
  wrap.appendChild(body);
  messagesEl.appendChild(wrap);

  updateHistoryCount();
  return body;
}

function updateHistoryCount() {
  const el = $('#history-count');
  if (el) el.textContent = msgCount > 0 ? `共 ${msgCount} 条对话` : '';
}

/**
 * 智能滚动：只有当用户已经贴近底部时才自动跟随
 * 如果用户上滑在看历史，就不打断他
 */
function isNearBottom() {
  return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 120;
}

function scrollToBottom(smooth = true) {
  messagesEl.scrollTo({
    top: messagesEl.scrollHeight,
    behavior: smooth ? 'smooth' : 'auto',
  });
}

// 监听滚动：上滑看历史时显示「回到底部」
messagesEl.addEventListener('scroll', () => {
  const nearBottom = isNearBottom();
  scrollBottomBtn.classList.toggle('hidden', nearBottom);
});

scrollBottomBtn.addEventListener('click', () => scrollToBottom(true));

$('#scroll-top').addEventListener('click', () => {
  messagesEl.scrollTo({ top: 0, behavior: 'smooth' });
});

function setBusy(state) {
  busy = state;
  sendBtn.disabled = state;
}

/**
 * 发送消息（流式接收）
 */
async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text || busy) return;

  addTurn(text, 'user');
  inputEl.value = '';
  scrollToBottom();
  setBusy(true);

  // 先插入 AI 消息骨架，带思考动画
  const body = addTurn('', 'bot');
  const head = body.previousSibling;
  const dots = document.createElement('span');
  dots.className = 'thinking-dots';
  dots.innerHTML = '<span></span><span></span><span></span>';
  head.appendChild(dots);

  scrollToBottom();

  let fullText = '';
  let cursor = null;

  try {
    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        building: pickedBuilding,
        classroom: pickedRoom,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      body.textContent = '⚠️ ' + (err.error || '请求失败');
      dots.remove();
      setBusy(false);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // 按 SSE 分隔符切分
      const parts = buffer.split('\n\n');
      buffer = parts.pop();

      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith('data:')) continue;

        let evt;
        try { evt = JSON.parse(line.slice(5).trim()); } catch { continue; }

        // ---- 文本片段：逐字追加 ----
        if (evt.type === 'text') {
          if (dots.parentNode) dots.remove();

          // 首次收到内容时加上光标
          if (!cursor) {
            cursor = document.createElement('span');
            cursor.className = 'stream-cursor';
            body.appendChild(cursor);
          }

          fullText += evt.content;
          cursor.insertAdjacentText('beforebegin', evt.content);

          // 平滑跟随（用户没上滑时才跟随）
          if (isNearBottom()) scrollToBottom(false);
        }

        // ---- 结束 ----
        else if (evt.type === 'end') {
          if (cursor) cursor.remove();

          const finalText = (evt.reply || fullText).trim();
          body.textContent = finalText;

          if (evt.finished) {
            body.parentNode.classList.add('conclusion');
          }

          // 报修提示
          if (evt.need_repair && evt.record_id) {
            const note = document.createElement('div');
            note.className = 'repair-note';
            note.textContent =
              `已记入报修台账（编号 ${evt.record_id}，教室 ${evt.classroom || '未填写'}），可在「报修记录」中跟踪处理进度。`;
            body.parentNode.appendChild(note);
            loadRecentRecords();
          }

          // 知识库沉淀提示（体现"越用越聪明"）
          if (evt.finished && evt.case_saved) {
            const note = document.createElement('div');
            note.className = 'kb-note';
            note.textContent = `📚 本次诊断已沉淀为新案例，知识库可以复用这个经验了`;
            body.parentNode.appendChild(note);
          }

          // 更新抽屉状态
          sessionRounds++;
          if (evt.classroom) currentClassroom = evt.classroom;
          sessionState = evt.finished ? '已完成' : '排查中';
          updateDrawer();

          if (evt.finished) {
            setTimeout(() => {
              sessionRounds = 0;
              currentClassroom = '';
              sessionState = '待开始';
              updateDrawer();
              // 清空教室选择，准备下一次诊断
              pickedBuilding = '';
              pickedRoom = '';
              const bSel = $('#pick-building');
              const rSel = $('#pick-room');
              if (bSel) bSel.value = '';
              if (rSel) {
                rSel.innerHTML = '<option value="">选择教室</option>';
                rSel.disabled = true;
              }
              const rp = $('#room-picker');
              if (rp) rp.classList.remove('picked');
            }, 1500);
          }

          scrollToBottom();
        }

        // ---- 错误 ----
        else if (evt.type === 'error') {
          if (cursor) cursor.remove();
          if (dots.parentNode) dots.remove();
          body.textContent = '⚠️ ' + evt.message;
        }
      }
    }

  } catch (err) {
    if (cursor) cursor.remove();
    if (dots.parentNode) dots.remove();
    body.textContent = '⚠️ 网络错误：' + err.message;
  }

  setBusy(false);
}

sendBtn.addEventListener('click', sendMessage);
inputEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendMessage();
});

// 重置会话（供按钮和抽屉共用）
async function resetSession() {
  if (busy) return;
  setBusy(true);
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: 'reset' }),
    });
    const data = await res.json();

    // 清空界面，重新开始（历史由后端会话管理）
    messagesEl.innerHTML = '';
    msgCount = 0;
    addTurn(data.reply || '已重置，请重新描述故障', 'bot');
    updateHistoryCount();

    sessionRounds = 0;
    currentClassroom = '';
    sessionState = '待开始';
    updateDrawer();
  } catch (err) {
    addTurn('⚠️ 重置失败：' + err.message, 'bot');
  }
  setBusy(false);
}

$('#reset').addEventListener('click', resetSession);

// ---------------- 报修记录 ----------------
let currentStatus = '';

document.querySelectorAll('.chip').forEach(chip => {
  // 导出按钮不是筛选条件，跳过（它有自己的处理逻辑）
  if (chip.dataset.export) return;

  chip.addEventListener('click', () => {
    document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    currentStatus = chip.dataset.status;
    loadRecords();
  });
});

/**
 * 导出报修记录为 Excel
 *
 * 后端返回的是文件流，这里用一次性的 <a download> 触发浏览器下载。
 * 之所以不直接用 window.open：某些浏览器会拦截弹窗。
 */
(function bindExport() {
  const btn = document.getElementById('btn-export-repair');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = '正在生成…';

    try {
      const res = await fetch('/api/export/repair');

      if (!res.ok) {
        // 出错时后端返回 JSON，取出其中的 error 提示
        let msg = `导出失败（HTTP ${res.status}）`;
        try {
          const j = await res.json();
          if (j.error) msg = j.error;
        } catch (e) { /* 非 JSON，用默认提示 */ }
        alert(msg);
        return;
      }

      // 优先用后端给的文件名（含时间戳）
      let filename = '机房故障报表.xlsx';
      const cd = res.headers.get('Content-Disposition') || '';
      const m = cd.match(/filename\*=UTF-8''([^;]+)/i);
      if (m) {
        try { filename = decodeURIComponent(m[1]); } catch (e) { /* 保留默认名 */ }
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      // 释放对象 URL，避免内存泄漏
      setTimeout(() => URL.revokeObjectURL(url), 1000);

    } catch (e) {
      alert('导出失败：' + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  });
})();

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

/**
 * 编辑报修记录
 *
 * 用自定义弹窗而不是 prompt()，因为教室需要「教学楼 + 教室」两个下拉，
 * 这样能统一历史上格式不规范的记录。
 */
async function editRecordDialog(rec) {
  // 读取教室台账，供下拉使用
  let buildings = [];
  try {
    const res = await fetch('/api/classrooms');
    buildings = (await res.json()).buildings || [];
  } catch { /* 忽略 */ }

  const bSel = buildings.map(b =>
    `<option value="${escapeHtml(b.name)}"${b.name === rec['教学楼'] ? ' selected' : ''}>${escapeHtml(b.name)}</option>`
  ).join('');

  const overlay = document.createElement('div');
  overlay.className = 'modal-mask';
  overlay.innerHTML = `
    <div class="modal" style="max-width:560px">
      <div class="modal-head">
        <h3>编辑记录 ${escapeHtml(rec['记录编号'])}</h3>
        <button class="modal-close" id="er-close">✕</button>
      </div>
      <div class="modal-body">
        <div class="tf-grid">
          <div class="tf-field">
            <label>教学楼</label>
            <select id="er-building">
              <option value="">（不指定）</option>
              ${bSel}
            </select>
          </div>
          <div class="tf-field">
            <label>教室</label>
            <select id="er-room">
              <option value="">请先选教学楼</option>
            </select>
          </div>
          <div class="tf-field tf-wide">
            <label>故障现象</label>
            <input type="text" id="er-symptom" value="${escapeHtml(rec['故障现象'] || '')}">
          </div>
          <div class="tf-field tf-wide">
            <label>诊断结论</label>
            <textarea id="er-conclusion" rows="4"
              style="background:rgba(255,255,255,0.04);border:1px solid var(--border);
                     border-radius:9px;padding:9px 12px;color:var(--text);
                     font-family:inherit;font-size:13.5px;outline:none;resize:vertical"
            >${escapeHtml(rec['诊断结论'] || '')}</textarea>
          </div>
          <div class="tf-field tf-wide">
            <label>备注</label>
            <input type="text" id="er-note" value="${escapeHtml(rec['备注'] || '')}">
          </div>
        </div>
        <div class="tf-actions">
          <button class="btn-primary btn-sm" id="er-save">保存</button>
          <button class="btn-ghost" id="er-cancel">取消</button>
        </div>
      </div>
    </div>
  `;

  document.body.appendChild(overlay);

  const rSel = overlay.querySelector('#er-room');
  const bEl = overlay.querySelector('#er-building');

  // 填充教室下拉
  function fillRooms(keepValue) {
    const b = buildings.find(x => x.name === bEl.value);
    if (!b || !b.rooms.length) {
      rSel.innerHTML = '<option value="">（该楼暂无教室）</option>';
      return;
    }
    rSel.innerHTML = '<option value="">请选择</option>' +
      b.rooms.map(r =>
        `<option value="${escapeHtml(r.name)}"${r.name === keepValue ? ' selected' : ''}>${escapeHtml(r.name)}</option>`
      ).join('');
  }

  fillRooms(rec['教室']);

  bEl.addEventListener('change', () => fillRooms(''));

  function close() { overlay.remove(); }

  overlay.querySelector('#er-close').addEventListener('click', close);
  overlay.querySelector('#er-cancel').addEventListener('click', close);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

  overlay.querySelector('#er-save').addEventListener('click', async () => {
    const payload = {
      building: bEl.value,
      classroom: rSel.value,
      symptom: overlay.querySelector('#er-symptom').value,
      conclusion: overlay.querySelector('#er-conclusion').value,
      note: overlay.querySelector('#er-note').value,
    };

    if (!payload.classroom) { alert('请选择教室'); return; }

    const res = await fetch('/api/records/' + encodeURIComponent(rec['记录编号']), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const d = await res.json();
    if (!d.ok) { alert(d.message); return; }
    close();
  });
}

async function loadRecords() {
  const list = $('#record-list');
  list.innerHTML = '<div class="empty">加载中…</div>';

  try {
    const url = '/api/records' + (currentStatus ? '?status=' + encodeURIComponent(currentStatus) : '');
    const res = await fetch(url);
    const data = await res.json();

    if (data.error) {
      list.innerHTML = `<div class="empty">读取失败：${escapeHtml(data.error)}</div>`;
      return;
    }

    // 状态统计条（点击可快速筛选）
    const c = data.counts || {};
    $('#record-summary').innerHTML = `
      <div class="rs-item pending" data-jump="">
        <span class="rs-num">${c['未报修'] || 0}</span>
        <span class="rs-label">未报修（待处理）</span>
      </div>
      <div class="rs-item reported" data-jump="已报修">
        <span class="rs-num">${c['已报修'] || 0}</span>
        <span class="rs-label">已报修（等维修）</span>
      </div>
      <div class="rs-item resolved" data-jump="已解决">
        <span class="rs-num">${c['已解决'] || 0}</span>
        <span class="rs-label">已解决</span>
      </div>
    `;

    // 点击统计卡片 → 筛选对应状态
    document.querySelectorAll('#record-summary .rs-item').forEach(item => {
      item.addEventListener('click', () => {
        const st = item.dataset.jump;
        currentStatus = st;
        document.querySelectorAll('.chip[data-status]').forEach(ch => {
          ch.classList.toggle('active', ch.dataset.status === st);
        });
        loadRecords();
      });
    });

    if (!data.records.length) {
      list.innerHTML = `<div class="empty"><span class="icon">📋</span>暂无${
        currentStatus ? '「' + escapeHtml(currentStatus) + '」状态的' : ''
      }记录</div>`;
      return;
    }

    list.innerHTML = '';

    // 状态分组标题的文案与说明
    const GROUP_META = {
      '未报修': { text: '待处理', desc: '还没联系维修，需要尽快跟进' },
      '已报修': { text: '等维修', desc: '已报修，等待处理结果' },
      '已解决': { text: '已完成', desc: '故障已修复' },
    };

    let lastStatus = null;

    data.records.forEach(r => {
      // 状态切换时插入分组标题
      if (r['状态'] !== lastStatus) {
        lastStatus = r['状态'];
        const meta = GROUP_META[r['状态']] || { text: r['状态'], desc: '' };
        const head = document.createElement('div');
        head.className = `group-head ${escapeHtml(r['状态'])}`;
        head.innerHTML = `
          <span class="gh-dot"></span>
          <span class="gh-text">${escapeHtml(meta.text)}</span>
          <span class="gh-desc">${escapeHtml(meta.desc)}</span>
        `;
        list.appendChild(head);
      }

      const el = document.createElement('div');
      el.className = 'record';

      // 教室显示规范化：有教学楼 → "A栋 · 101"；没有 → 标注"未关联教学楼"
      let roomHtml;
      if (r['教学楼']) {
        roomHtml = `<span class="record-classroom">${escapeHtml(r['教学楼'])} · ${escapeHtml(r['教室'])}</span>`;
      } else if (r['教室'] && r['教室'] !== '未填写') {
        roomHtml = `<span class="record-classroom warn">${escapeHtml(r['教室'])}
          <span class="no-building">未关联教学楼</span></span>`;
      } else {
        roomHtml = `<span class="record-classroom warn">教室未填写</span>`;
      }

      el.innerHTML = `
        <div class="record-head">
          <span class="record-id">${escapeHtml(r['记录编号'])}</span>
          ${roomHtml}
          <span class="badge ${escapeHtml(r['状态'])}">${escapeHtml(r['状态'])}</span>
          <span class="record-time">${escapeHtml(r['时间'])}</span>
        </div>
        <div class="record-body">
          <div><span class="label">现象：</span>${escapeHtml(r['故障现象'])}</div>
          <div><span class="label">结论：</span>${escapeHtml(r['诊断结论']).replace(/\n/g, '<br>')}</div>
          ${r['备注'] ? `<div><span class="label">备注：</span>${escapeHtml(r['备注'])}</div>` : ''}
        </div>
        <div class="record-actions">
          <button data-id="${escapeHtml(r['记录编号'])}" data-status="已报修">标记已报修</button>
          <button data-id="${escapeHtml(r['记录编号'])}" data-status="已解决">标记已解决</button>
          <button data-id="${escapeHtml(r['记录编号'])}" data-status="未报修">重置为未报修</button>
          <button class="edit-btn" data-edit="${escapeHtml(r['记录编号'])}">编辑</button>
          <button class="del-btn" data-del="${escapeHtml(r['记录编号'])}">删除</button>
        </div>
      `;
      list.appendChild(el);
    });

    // 绑定状态按钮
    list.querySelectorAll('.record-actions button[data-status]').forEach(btn => {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        try {
          const res = await fetch('/api/records/' + encodeURIComponent(btn.dataset.id), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: btn.dataset.status }),
          });
          const d = await res.json();
          if (!d.ok) alert(d.message);
        } catch (e) {
          alert('更新失败：' + e.message);
        }
        loadRecords();
      });
    });

    // 编辑
    list.querySelectorAll('[data-edit]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const rid = btn.dataset.edit;
        const rec = data.records.find(x => x['记录编号'] === rid);
        if (!rec) return;
        await editRecordDialog(rec);
        loadRecords();
      });
    });

    // 删除
    list.querySelectorAll('[data-del]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const rid = btn.dataset.del;
        if (!confirm(`确定删除记录 ${rid}？此操作不可撤销。`)) return;
        await fetch('/api/records/' + encodeURIComponent(rid), { method: 'DELETE' });
        loadRecords();
        refreshDrawerStats();
      });
    });

  } catch (err) {
    list.innerHTML = `<div class="empty">读取失败：${escapeHtml(err.message)}</div>`;
  }
}

// ---------------- 数据看板（ECharts） ----------------
let chartStatus = null, chartClassroom = null, chartTrend = null;

// 图表通用主题
const CHART_BASE = {
  textStyle: { color: '#8b98a5', fontFamily: 'inherit' },
  grid: { left: 12, right: 20, top: 30, bottom: 12, containLabel: true },
  tooltip: {
    backgroundColor: '#1a2129',
    borderColor: '#2d3843',
    textStyle: { color: '#e6edf3' },
  },
};

function initChart(el, existing) {
  if (existing) existing.dispose();
  return echarts.init(el, null, { renderer: 'canvas' });
}

async function loadStats() {
  const emptyEl = $('#stats-empty');

  try {
    const res = await fetch('/api/statistics');
    const d = await res.json();

    if (d.error) {
      emptyEl.classList.remove('hidden');
      emptyEl.textContent = '读取失败：' + d.error;
      return;
    }

    // 无数据时显示空状态
    if (!d.total) {
      emptyEl.classList.remove('hidden');
      return;
    }
    emptyEl.classList.add('hidden');

    // ---- KPI ----
    $('#kpi-total').textContent = d.total;
    $('#kpi-pending').textContent = d.by_status['未报修'] || 0;
    $('#kpi-reported').textContent = d.by_status['已报修'] || 0;
    $('#kpi-resolved').textContent = d.by_status['已解决'] || 0;
    $('#kpi-rate').textContent = d.resolve_rate + '%';
    $('#dash-updated').textContent = '更新于 ' + new Date().toLocaleTimeString('zh-CN');

    // ---- 图表 1：状态分布（环形图） ----
    chartStatus = initChart($('#chart-status'), chartStatus);
    chartStatus.setOption({
      ...CHART_BASE,
      legend: {
        orient: 'vertical',
        right: 10,
        top: 'center',
        textStyle: { color: '#8b98a5' },
        itemWidth: 12,
        itemHeight: 12,
      },
      series: [{
        type: 'pie',
        radius: ['48%', '72%'],
        center: ['38%', '50%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: '#1a2129', borderWidth: 3 },
        label: { show: false },
        data: [
          { value: d.by_status['未报修'] || 0, name: '未报修', itemStyle: { color: '#ef4444' } },
          { value: d.by_status['已报修'] || 0, name: '已报修', itemStyle: { color: '#f59e0b' } },
          { value: d.by_status['已解决'] || 0, name: '已解决', itemStyle: { color: '#22c55e' } },
        ].filter(x => x.value > 0),
      }],
    });

    // ---- 图表 2：教室排行（横向柱状图） ----
    const rooms = d.top_classrooms.map(x => x[0]).reverse();
    const counts = d.top_classrooms.map(x => x[1]).reverse();

    chartClassroom = initChart($('#chart-classroom'), chartClassroom);
    chartClassroom.setOption({
      ...CHART_BASE,
      grid: { left: 12, right: 30, top: 20, bottom: 12, containLabel: true },
      xAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: '#222b35' } },
        axisLabel: { color: '#8b98a5' },
      },
      yAxis: {
        type: 'category',
        data: rooms,
        axisLine: { lineStyle: { color: '#2d3843' } },
        axisLabel: { color: '#8b98a5' },
      },
      series: [{
        type: 'bar',
        data: counts,
        barWidth: '55%',
        itemStyle: {
          borderRadius: [0, 4, 4, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
            { offset: 0, color: '#3b82f6' },
            { offset: 1, color: '#60a5fa' },
          ]),
        },
        label: { show: true, position: 'right', color: '#8b98a5' },
      }],
    });

    // ---- 图表 3：故障趋势（折线图） ----
    chartTrend = initChart($('#chart-trend'), chartTrend);
    chartTrend.setOption({
      ...CHART_BASE,
      grid: { left: 12, right: 24, top: 30, bottom: 12, containLabel: true },
      xAxis: {
        type: 'category',
        data: d.dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#2d3843' } },
        axisLabel: { color: '#8b98a5' },
      },
      yAxis: {
        type: 'value',
        minInterval: 1,
        splitLine: { lineStyle: { color: '#222b35' } },
        axisLabel: { color: '#8b98a5' },
      },
      series: [{
        type: 'line',
        data: d.date_counts,
        smooth: true,
        symbolSize: 7,
        lineStyle: { width: 2.5, color: '#3b82f6' },
        itemStyle: { color: '#3b82f6' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(59,130,246,0.35)' },
            { offset: 1, color: 'rgba(59,130,246,0.02)' },
          ]),
        },
      }],
    });

  } catch (err) {
    emptyEl.classList.remove('hidden');
    emptyEl.textContent = '读取失败：' + err.message;
  }
}

// 窗口尺寸变化时重绘图表
window.addEventListener('resize', () => {
  [chartStatus, chartClassroom, chartTrend].forEach(c => c && c.resize());
  if (roomChart) roomChart.resize();
});

/* ============================================================
   后台管理：教室与设备
   ============================================================ */
const adminModal = $('#admin-modal');
let roomChart = null;
let classroomCache = null;

// 打开 / 关闭
function openAdmin() {
  adminModal.classList.remove('hidden');
  showListView();
  loadClassrooms();
}
function closeAdmin() {
  adminModal.classList.add('hidden');
  if (roomChart) { roomChart.dispose(); roomChart = null; }
}

$('#gear-btn').addEventListener('click', openAdmin);
$('#admin-close').addEventListener('click', closeAdmin);
adminModal.addEventListener('click', (e) => {
  if (e.target === adminModal) closeAdmin();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !adminModal.classList.contains('hidden')) closeAdmin();
});

// 两个视图切换
function showListView() {
  $('#admin-list-view').classList.remove('hidden');
  $('#admin-room-view').classList.add('hidden');
  $('#admin-title').textContent = '教室与设备管理';
  if (roomChart) { roomChart.dispose(); roomChart = null; }
}

function showRoomView() {
  $('#admin-list-view').classList.add('hidden');
  $('#admin-room-view').classList.remove('hidden');
}

$('#back-to-list').addEventListener('click', () => {
  showListView();
  refreshDrawerStats();
});

// ---------- 加载教室列表 ----------
async function loadClassrooms() {
  const box = $('#building-list');
  box.innerHTML = '<div class="empty">加载中…</div>';

  try {
    const res = await fetch('/api/classrooms');
    const d = await res.json();
    classroomCache = d;

    if (!d.buildings.length) {
      box.innerHTML = `<div class="empty">
        <span class="icon">🏫</span>
        还没有教学楼，请在上方添加
      </div>`;
      return;
    }

    box.innerHTML = d.buildings.map(b => {
      const rooms = b.rooms.length
        ? b.rooms.map(r => roomRowHtml(b.name, r)).join('')
        : '<div class="empty" style="padding:22px;font-size:13px">该教学楼下还没有教室</div>';

      return `
        <div class="building-group">
          <div class="building-head">
            <span class="building-name">
              🏢 ${escapeHtml(b.name)}
              <span class="count">${b.rooms.length} 间</span>
            </span>
            <button class="icon-btn" data-del-building="${escapeHtml(b.name)}">删除</button>
          </div>
          ${rooms}
          <div class="admin-toolbar" style="padding:12px 16px;margin:0">
            <input type="text" placeholder="教室名，如 A101" data-room-name="${escapeHtml(b.name)}">
            <input type="number" placeholder="电脑数" style="max-width:100px" data-room-total="${escapeHtml(b.name)}">
            <input type="number" placeholder="损坏" style="max-width:90px" data-room-broken="${escapeHtml(b.name)}">
            <button class="btn-primary btn-sm" data-add-room="${escapeHtml(b.name)}">添加教室</button>
          </div>
        </div>
      `;
    }).join('');

    bindListEvents();

  } catch (err) {
    box.innerHTML = `<div class="empty">加载失败：${escapeHtml(err.message)}</div>`;
  }
}

function roomRowHtml(building, r) {
  const total = r.total || 0;
  const broken = r.broken || 0;
  const healthy = total - broken;
  const pct = total > 0 ? Math.round(healthy / total * 100) : 0;

  return `
    <div class="room-row" data-open-room="${escapeHtml(building)}" data-room="${escapeHtml(r.name)}">
      <span class="rname">${escapeHtml(r.name)}</span>
      <span class="rstat">
        <span>总数 <b>${total}</b></span>
        <span>正常 <b>${healthy}</b></span>
        <span class="rbroken">损坏 <b>${broken}</b></span>
      </span>
      <span class="health-bar"><span style="width:${pct}%"></span></span>
      <span class="arrow">›</span>
    </div>
  `;
}

function bindListEvents() {
  // 删除教学楼
  document.querySelectorAll('[data-del-building]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const name = btn.dataset.delBuilding;
      if (!confirm(`确定删除教学楼「${name}」及其下全部教室？`)) return;
      await fetch('/api/classrooms/building/' + encodeURIComponent(name), { method: 'DELETE' });
      loadClassrooms();
      refreshDrawerStats();
    });
  });

  // 添加教室
  document.querySelectorAll('[data-add-room]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const b = btn.dataset.addRoom;
      const nameEl = document.querySelector(`[data-room-name="${CSS.escape(b)}"]`);
      const totalEl = document.querySelector(`[data-room-total="${CSS.escape(b)}"]`);
      const brokenEl = document.querySelector(`[data-room-broken="${CSS.escape(b)}"]`);

      const res = await fetch('/api/classrooms/room', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          building: b,
          name: nameEl.value.trim(),
          total: totalEl.value || 0,
          broken: brokenEl.value || 0,
        }),
      });
      const d = await res.json();
      if (!d.ok) { alert(d.message); return; }
      loadClassrooms();
      refreshDrawerStats();
    });
  });

  // 点击教室行 → 详情
  document.querySelectorAll('[data-open-room]').forEach(row => {
    row.addEventListener('click', () => {
      openRoomDetail(row.dataset.openRoom, row.dataset.room);
    });
  });
}

// 添加教学楼
$('#add-building').addEventListener('click', async () => {
  const input = $('#new-building');
  const name = input.value.trim();
  if (!name) { alert('请输入教学楼名称'); return; }

  const res = await fetch('/api/classrooms/building', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  const d = await res.json();
  if (!d.ok) { alert(d.message); return; }

  input.value = '';
  loadClassrooms();
  refreshDrawerStats();
});

// ---------- 教室详情 ----------

/**
 * 「登记故障」弹窗
 *
 * 用表格一次填多条故障：每条 = 损坏原因 + 数量 + 状态。
 * 相比原来的 prompt() 逐条询问：
 *   · 能一次登记一批（如"第三排 5 台都开不了机"）
 *   · 损坏数量有独立字段，统计台数才准确
 *   · 可以选择状态（未报修 / 待自修）
 *
 * @param {string} building  教学楼
 * @param {string} roomName  教室
 * @param {Function} onDone  登记成功后的回调（刷新界面）
 */
function openFaultForm(building, roomName, onDone) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-mask';

  // 一行故障的 HTML
  const rowHtml = (idx) => `
    <tr class="ff-row">
      <td class="ff-idx">${idx}</td>
      <td>
        <input type="text" class="ff-reason" list="ff-common"
               placeholder="如：电源损坏 / 网线松动 / 显示器无信号">
      </td>
      <td class="ff-qty-cell">
        <input type="number" class="ff-qty" value="1" min="1" max="999">
      </td>
      <td>
        <select class="ff-status">
          <option value="未报修">未报修（硬件，需报修）</option>
          <option value="待自修">待自修（可自行修复）</option>
          <option value="已报修">已报修（已联系维修）</option>
          <option value="已解决">已解决</option>
        </select>
      </td>
      <td>
        <button class="ff-del" title="删除这一行">✕</button>
      </td>
    </tr>`;

  overlay.innerHTML = `
    <div class="modal" style="max-width:760px">
      <div class="modal-head">
        <h3>登记故障 · ${escapeHtml(building)} ${escapeHtml(roomName)}</h3>
        <button class="modal-close" id="ff-close">✕</button>
      </div>
      <div class="modal-body">
        <p class="ff-hint">
          每行一条故障原因，填写**损坏数量**。同一原因的多台机器填一行即可，
          不必逐台登记。
        </p>

        <!-- 常见原因，供输入框自动补全 -->
        <datalist id="ff-common">
          <option value="电源损坏"></option>
          <option value="主板故障"></option>
          <option value="内存条松动"></option>
          <option value="硬盘故障"></option>
          <option value="显示器损坏"></option>
          <option value="显卡故障"></option>
          <option value="网线松动"></option>
          <option value="网口损坏"></option>
          <option value="键盘失灵"></option>
          <option value="鼠标失灵"></option>
          <option value="系统故障需重装"></option>
          <option value="投影仪无信号"></option>
          <option value="插座无电"></option>
          <option value="教室总闸跳闸"></option>
        </datalist>

        <table class="fault-form-table">
          <thead>
            <tr>
              <th style="width:36px">#</th>
              <th>损坏原因</th>
              <th style="width:90px">数量</th>
              <th style="width:190px">状态</th>
              <th style="width:40px"></th>
            </tr>
          </thead>
          <tbody id="ff-body">${rowHtml(1)}</tbody>
        </table>

        <button class="btn-ghost btn-sm" id="ff-add" style="margin-top:10px">
          ＋ 添加一行
        </button>

        <div class="ff-summary" id="ff-summary"></div>

        <div class="tf-actions">
          <button class="btn-primary btn-sm" id="ff-save">登记</button>
          <button class="btn-ghost" id="ff-cancel">取消</button>
        </div>
      </div>
    </div>
  `;

  document.body.appendChild(overlay);

  const body = overlay.querySelector('#ff-body');
  const summaryEl = overlay.querySelector('#ff-summary');

  /** 重新编号（删除行之后） */
  function renumber() {
    body.querySelectorAll('.ff-row').forEach((tr, i) => {
      tr.querySelector('.ff-idx').textContent = i + 1;
    });
  }

  /** 汇总提示：共几行、合计几台 */
  function updateSummary() {
    const rows = body.querySelectorAll('.ff-row');
    let total = 0;
    let filled = 0;
    rows.forEach(tr => {
      const reason = tr.querySelector('.ff-reason').value.trim();
      const qty = parseInt(tr.querySelector('.ff-qty').value, 10) || 0;
      if (reason) { filled += 1; total += Math.max(qty, 0); }
    });
    summaryEl.innerHTML = filled
      ? `共 <b>${filled}</b> 条故障，合计 <b>${total}</b> 台设备`
      : '';
  }

  /** 绑定行内事件 */
  function bindRow(tr) {
    tr.querySelector('.ff-del').addEventListener('click', () => {
      // 至少保留一行，否则表单空了没法填
      if (body.querySelectorAll('.ff-row').length <= 1) {
        tr.querySelector('.ff-reason').value = '';
        tr.querySelector('.ff-qty').value = 1;
        updateSummary();
        return;
      }
      tr.remove();
      renumber();
      updateSummary();
    });
    tr.querySelector('.ff-reason').addEventListener('input', updateSummary);
    tr.querySelector('.ff-qty').addEventListener('input', updateSummary);
  }

  body.querySelectorAll('.ff-row').forEach(bindRow);

  overlay.querySelector('#ff-add').addEventListener('click', () => {
    const tmp = document.createElement('tbody');
    tmp.innerHTML = rowHtml(0);
    const tr = tmp.querySelector('.ff-row');
    body.appendChild(tr);
    bindRow(tr);
    renumber();
    tr.querySelector('.ff-reason').focus();
  });

  function close() { overlay.remove(); }

  overlay.querySelector('#ff-close').addEventListener('click', close);
  overlay.querySelector('#ff-cancel').addEventListener('click', close);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

  overlay.querySelector('#ff-save').addEventListener('click', async () => {
    const faults = [];
    body.querySelectorAll('.ff-row').forEach(tr => {
      const reason = tr.querySelector('.ff-reason').value.trim();
      if (!reason) return;   // 空行直接跳过
      faults.push({
        reason,
        quantity: parseInt(tr.querySelector('.ff-qty').value, 10) || 1,
        status: tr.querySelector('.ff-status').value,
      });
    });

    if (!faults.length) {
      alert('请至少填写一条故障原因');
      return;
    }

    const btn = overlay.querySelector('#ff-save');
    btn.disabled = true;
    btn.textContent = '登记中…';

    try {
      const res = await fetch('/api/records/manual', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ building, classroom: roomName, faults }),
      });
      const d = await res.json();
      if (!d.ok) {
        alert(d.message || '登记失败');
        return;
      }
      close();
      if (onDone) onDone();
    } catch (err) {
      alert('登记失败：' + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = '登记';
    }
  });

  updateSummary();
}

async function openRoomDetail(building, roomName) {
  showRoomView();
  $('#admin-title').textContent = `教室详情 · ${building}-${roomName}`;
  $('#room-detail').innerHTML = '<div class="empty">加载中…</div>';

  // 取教室台账 + 该教室的故障记录
  let d;
  try {
    const res = await fetch(
      `/api/classrooms/room-detail?building=${encodeURIComponent(building)}&room=${encodeURIComponent(roomName)}`
    );
    d = await res.json();
  } catch (err) {
    $('#room-detail').innerHTML = `<div class="empty">加载失败：${escapeHtml(err.message)}</div>`;
    return;
  }

  const info = d.info;
  if (!info) {
    $('#room-detail').innerHTML = '<div class="empty">未找到该教室</div>';
    return;
  }

  const total = info.total || 0;
  const c = d.counts;

  // 三种状态的台数（都来自报修台账，不再有"手动登记"这一路）
  const selfFix = c.self_fix || 0;          // 待自修（黄）
  const hardBroken = (c.pending || 0) + (c.reported || 0);  // 需报修（红）
  const brokenAll = c.unresolved || 0;      // 不能用合计
  const healthy = Math.max(total - brokenAll, 0);

  // 按状态给记录标颜色
  const STATUS_CLASS = {
    '未报修': 'pending',
    '待自修': 'selffix',
    '已报修': 'reported',
    '已解决': 'resolved',
  };

  // 故障明细（含已解决的，方便编辑）
  const causeHtml = d.records.length
    ? d.records.map(r => {
        const st = r['状态'] || '未报修';
        const done = st === '已解决';
        const qty = parseInt(r['数量'], 10) || 1;
        return `
        <div class="cause-item ${done ? 'resolved' : ''}">
          <div class="cause-top">
            <span class="cause-id">${escapeHtml(r['记录编号'])}</span>
            <span class="badge ${STATUS_CLASS[st] || 'pending'}">${escapeHtml(st)}</span>
            ${qty > 1 ? `<span class="qty-tag">${qty} 台</span>` : ''}
            <span class="cause-time">${escapeHtml(r['时间'])}</span>
          </div>
          <div class="cause-text">
            <b style="color:var(--text-dim)">现象：</b>${escapeHtml(r['故障现象'])}<br>
            <b style="color:var(--text-dim)">结论：</b>${escapeHtml(r['诊断结论'] || '—').replace(/\n/g, '<br>')}
            ${r['备注'] ? `<br><b style="color:var(--text-dim)">备注：</b>${escapeHtml(r['备注'])}` : ''}
          </div>
          <div class="cause-actions">
            ${done
              ? `<button data-set-status="${escapeHtml(r['记录编号'])}" data-to="未报修">↩ 恢复未报修</button>`
              : `<button data-set-status="${escapeHtml(r['记录编号'])}" data-to="待自修">🔧 改为待自修</button>
                 <button data-set-status="${escapeHtml(r['记录编号'])}" data-to="已报修">标记已报修</button>
                 <button data-set-status="${escapeHtml(r['记录编号'])}" data-to="已解决">✓ 标记已解决</button>`}
            <button data-edit-record="${escapeHtml(r['记录编号'])}">编辑</button>
            <button class="del-btn" data-del-record="${escapeHtml(r['记录编号'])}">删除</button>
          </div>
        </div>`;
      }).join('')
    : '<div class="cause-empty">该教室当前没有故障记录</div>';

  $('#room-detail').innerHTML = `
    <h4>${escapeHtml(building)} · ${escapeHtml(roomName)}</h4>
    <div class="sub-line">设备状态由报修台账自动统计，无需手工填写损坏数</div>

    <div class="detail-stats detail-stats-4">
      <div class="detail-stat tot">
        <div class="dv">${total}</div><div class="dl">电脑总数</div>
      </div>
      <div class="detail-stat ok">
        <div class="dv">${healthy}</div><div class="dl">正常</div>
      </div>
      <div class="detail-stat selffix">
        <div class="dv">${selfFix}</div><div class="dl">🔧 待自修</div>
      </div>
      <div class="detail-stat bad">
        <div class="dv">${hardBroken}</div><div class="dl">⚠ 需报修</div>
      </div>
    </div>

    <div id="room-chart"></div>

    <div class="cause-section">
      <div class="cause-head">
        <h5>损坏与故障明细</h5>
        <button class="btn-primary btn-sm" id="add-record">＋ 登记故障</button>
      </div>
      <div class="cause-summary">
        <span>未报修 <b>${c.pending}</b></span>
        <span class="sm-selffix">待自修 <b>${c.self_fix}</b></span>
        <span>已报修 <b>${c.reported}</b></span>
        <span>已解决 <b>${c.resolved}</b></span>
        <span style="margin-left:auto;color:var(--text-faint)">
          不能用合计 <b>${brokenAll}</b> 台
        </span>
      </div>
      <div class="cause-list">${causeHtml}</div>
    </div>

    <div class="edit-form">
      <div class="edit-field">
        <label>电脑总数</label>
        <input type="number" id="edit-total" value="${total}" min="0">
      </div>
      <div class="edit-field" style="grid-column:1/-1">
        <label>备注</label>
        <input type="text" id="edit-note" value="${escapeHtml(info.note || '')}"
               placeholder="如：第三排第 2 台频繁死机">
      </div>
      <div class="edit-actions">
        <button class="btn-primary btn-sm" id="save-room">保存修改</button>
        <button class="btn-danger" id="del-room">删除该教室</button>
      </div>
    </div>
  `;

  // 环形图：正常 / 待自修 / 需报修 三段
  roomChart = echarts.init($('#room-chart'));
  roomChart.setOption({
    textStyle: { color: '#8b98a5' },
    tooltip: { trigger: 'item', formatter: '{b}：{c} 台 ({d}%)' },
    legend: { bottom: 0, textStyle: { color: '#8b98a5' }, itemWidth: 12, itemHeight: 12 },
    series: [{
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['50%', '44%'],
      itemStyle: { borderColor: '#141a21', borderWidth: 3 },
      label: { show: false },
      data: [
        { value: healthy, name: '正常', itemStyle: { color: '#22c55e' } },
        { value: selfFix, name: '待自修', itemStyle: { color: '#eab308' } },
        { value: hardBroken, name: '需报修', itemStyle: { color: '#ef4444' } },
      ].filter(x => x.value > 0),
    }],
  });

  // 明细里直接改状态 → 损坏数随之变化
  document.querySelectorAll('[data-set-status]').forEach(btn => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      await fetch('/api/records/' + encodeURIComponent(btn.dataset.setStatus), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: btn.dataset.to }),
      });
      // 重新加载本页 + 刷新抽屉与列表
      openRoomDetail(building, roomName);
      refreshDrawerStats();
      if (classroomCache) loadClassrooms();
    });
  });

  // 编辑某条故障记录
  document.querySelectorAll('[data-edit-record]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const rid = btn.dataset.editRecord;
      const rec = d.records.find(x => x['记录编号'] === rid);
      if (!rec) return;

      const symptom = prompt('故障现象：', rec['故障现象'] || '');
      if (symptom === null) return;
      const conclusion = prompt('诊断结论：', rec['诊断结论'] || '');
      if (conclusion === null) return;
      const note = prompt('备注：', rec['备注'] || '');
      if (note === null) return;

      await fetch('/api/records/' + encodeURIComponent(rid), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symptom, conclusion, note }),
      });
      openRoomDetail(building, roomName);
      refreshDrawerStats();
    });
  });

  // 删除某条故障记录
  document.querySelectorAll('[data-del-record]').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!confirm(`确定删除记录 ${btn.dataset.delRecord}？`)) return;
      await fetch('/api/records/' + encodeURIComponent(btn.dataset.delRecord), {
        method: 'DELETE',
      });
      openRoomDetail(building, roomName);
      refreshDrawerStats();
      if (classroomCache) loadClassrooms();
    });
  });

  // 登记故障（弹窗表格：原因 + 数量，可一次填多行）
  $('#add-record').addEventListener('click', () => {
    openFaultForm(building, roomName, () => {
      openRoomDetail(building, roomName);
      refreshDrawerStats();
      if (classroomCache) loadClassrooms();
    });
  });

  // 保存（电脑总数 / 备注）—— 损坏台数由台账推导，不在这里填
  $('#save-room').addEventListener('click', async () => {
    const res2 = await fetch('/api/classrooms/room', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        building,
        name: roomName,
        total: $('#edit-total').value,
        note: $('#edit-note').value,
      }),
    });
    const d2 = await res2.json();
    if (!d2.ok) { alert(d2.message); return; }
    openRoomDetail(building, roomName);
    refreshDrawerStats();
    loadClassrooms();
  });

  // 删除
  $('#del-room').addEventListener('click', async () => {
    if (!confirm(`确定删除教室「${roomName}」？`)) return;
    await fetch('/api/classrooms/room', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ building, name: roomName }),
    });
    showListView();
    loadClassrooms();
    refreshDrawerStats();
  });
}

// ---------- 更新抽屉里的设备总览 ----------
async function refreshDrawerStats() {
  try {
    const res = await fetch('/api/classrooms/summary');
    const s = await res.json();
    $('#d-buildings').textContent = s.buildings ?? '—';
    $('#d-rooms').textContent = s.rooms ?? '—';
    $('#d-pcs').textContent = s.total_pcs ?? '—';
    $('#d-broken').textContent = s.broken_pcs ?? '—';
  } catch { /* 忽略 */ }
}

/* ============================================================
   诊断页：教室选择条
   ============================================================ */
let pickedBuilding = '';
let pickedRoom = '';

async function loadRoomPicker() {
  const bSel = $('#pick-building');
  const rSel = $('#pick-room');

  try {
    const res = await fetch('/api/classrooms');
    const d = await res.json();

    // 教学楼下拉
    bSel.innerHTML = '<option value="">选择教学楼</option>' +
      d.buildings.map(b =>
        `<option value="${escapeHtml(b.name)}">${escapeHtml(b.name)}（${b.rooms.length}间）</option>`
      ).join('');

    // 如果没有数据，给出提示
    if (!d.buildings.length) {
      bSel.innerHTML = '<option value="">（请先在后台添加教学楼）</option>';
    }

    // 恢复之前的选择
    if (pickedBuilding) {
      bSel.value = pickedBuilding;
      fillRooms(d, pickedBuilding);
    }
  } catch { /* 忽略 */ }
}

function fillRooms(data, building) {
  const rSel = $('#pick-room');
  const b = (data.buildings || []).find(x => x.name === building);

  if (!b || !b.rooms.length) {
    rSel.innerHTML = '<option value="">（该楼暂无教室）</option>';
    rSel.disabled = true;
    return;
  }

  rSel.innerHTML = '<option value="">选择教室</option>' +
    b.rooms.map(r =>
      `<option value="${escapeHtml(r.name)}">${escapeHtml(r.name)}（${r.total}台）</option>`
    ).join('');
  rSel.disabled = false;
}

// 切换教学楼
$('#pick-building').addEventListener('change', async (e) => {
  pickedBuilding = e.target.value;
  pickedRoom = '';
  $('#pick-room').value = '';

  if (!pickedBuilding) {
    $('#pick-room').innerHTML = '<option value="">选择教室</option>';
    $('#pick-room').disabled = true;
    $('#room-picker').classList.remove('picked');
    return;
  }

  const res = await fetch('/api/classrooms');
  fillRooms(await res.json(), pickedBuilding);
  $('#room-picker').classList.toggle('picked', !!pickedBuilding);
});

// 选择教室
$('#pick-room').addEventListener('change', (e) => {
  pickedRoom = e.target.value;
  $('#room-picker').classList.toggle('picked', !!pickedRoom);
});

// 清除选择
$('#rp-clear').addEventListener('click', () => {
  pickedBuilding = '';
  pickedRoom = '';
  $('#pick-building').value = '';
  $('#pick-room').innerHTML = '<option value="">选择教室</option>';
  $('#pick-room').disabled = true;
  $('#room-picker').classList.remove('picked');
});

/* ============================================================
   日常报备（待办清单）
   ============================================================ */
let taskFilter = '';
let taskMeta = null;

// 打开 / 关闭添加表单
$('#toggle-add-task').addEventListener('click', () => {
  const form = $('#task-form');
  const hidden = form.classList.toggle('hidden');
  if (!hidden) {
    form.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    $('#tf-teacher').focus();
  }
});
$('#tf-cancel').addEventListener('click', () => {
  $('#task-form').classList.add('hidden');
});

// 筛选
document.querySelectorAll('[data-task-filter]').forEach(chip => {
  chip.addEventListener('click', () => {
    document.querySelectorAll('[data-task-filter]').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    taskFilter = chip.dataset.taskFilter;
    loadTasks();
  });
});

// 教学楼 → 教室 联动
$('#tf-building').addEventListener('change', async (e) => {
  const roomSel = $('#tf-room');
  const building = e.target.value;

  if (!building) {
    roomSel.innerHTML = '<option value="">请先选教学楼</option>';
    roomSel.disabled = true;
    return;
  }

  try {
    const res = await fetch('/api/classrooms');
    const d = await res.json();
    const b = d.buildings.find(x => x.name === building);

    if (!b || !b.rooms.length) {
      roomSel.innerHTML = '<option value="">（该楼暂无教室）</option>';
      roomSel.disabled = true;
      return;
    }

    roomSel.innerHTML = '<option value="">请选择教室</option>' +
      b.rooms.map(r => `<option value="${escapeHtml(r.name)}">${escapeHtml(r.name)}</option>`).join('');
    roomSel.disabled = false;
  } catch { /* 忽略 */ }
});

// 提交
$('#tf-submit').addEventListener('click', async () => {
  const payload = {
    building: $('#tf-building').value,
    room: $('#tf-room').value,
    task_type: $('#tf-type').value,
    teacher: $('#tf-teacher').value,
    major: $('#tf-major').value,
    detail: $('#tf-detail').value,
    due: $('#tf-due').value,
    priority: $('#tf-priority').value,
  };

  if (!payload.room) { alert('请选择教室'); return; }
  if (!payload.task_type) { alert('请选择需求类型'); return; }

  const res = await fetch('/api/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const d = await res.json();
  if (!d.ok) { alert(d.message); return; }

  // 清空表单
  ['#tf-teacher', '#tf-major', '#tf-detail', '#tf-due'].forEach(s => { $(s).value = ''; });
  $('#tf-type').value = '';
  $('#task-form').classList.add('hidden');

  loadTasks();
});

// 加载清单
async function loadTasks() {
  const list = $('#task-list');
  list.innerHTML = '<div class="empty">加载中…</div>';

  try {
    const url = '/api/tasks' + (taskFilter ? '?status=' + encodeURIComponent(taskFilter) : '');
    const res = await fetch(url);
    const d = await res.json();
    taskMeta = d;

    // 汇总卡片
    const s = d.summary;
    $('#task-summary').innerHTML = `
      <div class="ts-card pending"><div class="tsv">${s.pending}</div><div class="tsl">待完成</div></div>
      <div class="ts-card done"><div class="tsv">${s.done}</div><div class="tsl">已完成</div></div>
      <div class="ts-card overdue"><div class="tsv">${s.overdue}</div><div class="tsl">已逾期</div></div>
      <div class="ts-card high"><div class="tsv">${s.high}</div><div class="tsl">高优先级</div></div>
    `;

    if (!d.tasks.length) {
      list.innerHTML = `<div class="empty">
        <span class="icon">📝</span>
        ${taskFilter ? '没有「' + escapeHtml(taskFilter) + '」的报备' : '还没有报备记录，点上面的「添加报备」开始'}
      </div>`;
      return;
    }

    const today = new Date().toISOString().slice(0, 10);

    list.innerHTML = d.tasks.map(t => {
      const isDone = t.status === '已完成';
      const isOverdue = !isDone && t.due && t.due.slice(0, 10) < today;
      const cls = (isDone ? 'done' : 'pending') + (isOverdue ? ' overdue' : '');

      return `
        <div class="task-item ${cls}">
          <div class="ti-head">
            <span class="ti-title">${escapeHtml(t.task_type)}</span>
            <span class="ti-badge ${isDone ? 'done' : 'pending'}">${escapeHtml(t.status)}</span>
            <span class="ti-prio ${escapeHtml(t.priority)}">${escapeHtml(t.priority)}</span>
            <span class="ti-id">${escapeHtml(t.id)}</span>
          </div>
          <div class="ti-body">
            <span class="kv">教室 <b>${escapeHtml(t.building ? t.building + ' · ' + t.room : t.room)}</b></span>
            ${t.teacher ? `<span class="kv">教师 <b>${escapeHtml(t.teacher)}</b></span>` : ''}
            ${t.major ? `<span class="kv">专业 <b>${escapeHtml(t.major)}</b></span>` : ''}
            ${t.due ? `<span class="kv">预计 <b class="ti-due">${escapeHtml(t.due)}</b>${isOverdue ? ' ⚠️ 已逾期' : ''}</span>` : ''}
            ${t.detail ? `<div style="margin-top:5px">${escapeHtml(t.detail)}</div>` : ''}
            <div style="margin-top:5px;font-size:12px;color:var(--text-faint)">
              提交于 ${escapeHtml(t.created)}${isDone && t.finished ? ' · 完成于 ' + escapeHtml(t.finished) : ''}
            </div>
          </div>
          <div class="ti-actions">
            <button class="${isDone ? '' : 'done-btn'}" data-toggle="${escapeHtml(t.id)}">
              ${isDone ? '↩ 标记待完成' : '✓ 标记已完成'}
            </button>
            <button data-edit="${escapeHtml(t.id)}">改预计时间</button>
            <button class="del-btn" data-del-task="${escapeHtml(t.id)}">删除</button>
          </div>
        </div>
      `;
    }).join('');

    // 绑定按钮
    list.querySelectorAll('[data-toggle]').forEach(btn => {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        await fetch('/api/tasks/' + encodeURIComponent(btn.dataset.toggle) + '/toggle', { method: 'POST' });
        loadTasks();
      });
    });

    list.querySelectorAll('[data-edit]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const cur = prompt('修改预计解决时间（格式 2026-10-25）：');
        if (cur === null) return;
        await fetch('/api/tasks/' + encodeURIComponent(btn.dataset.edit), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ due: cur }),
        });
        loadTasks();
      });
    });

    list.querySelectorAll('[data-del-task]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('确定删除这条报备？')) return;
        await fetch('/api/tasks/' + encodeURIComponent(btn.dataset.delTask), { method: 'DELETE' });
        loadTasks();
      });
    });

  } catch (err) {
    list.innerHTML = `<div class="empty">加载失败：${escapeHtml(err.message)}</div>`;
  }
}

// 初始化报备表单的选项
async function initTaskForm() {
  try {
    const res = await fetch('/api/tasks');
    const d = await res.json();

    $('#tf-type').innerHTML = '<option value="">请选择</option>' +
      d.types.map(t => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join('');

    $('#tf-priority').innerHTML = d.priorities.map(p =>
      `<option value="${escapeHtml(p)}"${p === '中' ? ' selected' : ''}>${escapeHtml(p)}</option>`
    ).join('');

    // 教学楼下拉
    const cres = await fetch('/api/classrooms');
    const cd = await cres.json();
    $('#tf-building').innerHTML = '<option value="">请选择</option>' +
      cd.buildings.map(b =>
        `<option value="${escapeHtml(b.name)}">${escapeHtml(b.name)}</option>`
      ).join('');
  } catch { /* 忽略 */ }
}

/* ============================================================
   初始化
   ============================================================ */
loadLandingStats();
loadRoomPicker();
initTaskForm();
