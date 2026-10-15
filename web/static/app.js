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

  document.querySelectorAll('.tab').forEach(t => {
    t.classList.toggle('active', t.dataset.view === view);
  });

  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  const target = $('#view-' + view);
  if (target) target.classList.add('active');

  if (view === 'records') loadRecords();
  if (view === 'stats') loadStats();
  if (view === 'chat') {
    const inp = $('#input');
    if (inp) setTimeout(() => inp.focus(), 100);
  }
  updateDrawer();
}

document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => switchView(tab.dataset.view));
});

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
  $('#d-classroom').textContent = currentClassroom || '—';
  $('#d-rounds').textContent = sessionRounds;
  $('#d-state').textContent = sessionState;
  loadRecentRecords();
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
      body: JSON.stringify({ message: text }),
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
  chip.addEventListener('click', () => {
    document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    currentStatus = chip.dataset.status;
    loadRecords();
  });
});

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
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

    if (!data.records.length) {
      list.innerHTML = `<div class="empty"><span class="icon">📋</span>暂无${
        currentStatus ? '「' + escapeHtml(currentStatus) + '」状态的' : ''
      }记录</div>`;
      return;
    }

    list.innerHTML = '';
    data.records.forEach(r => {
      const el = document.createElement('div');
      el.className = 'record';
      el.innerHTML = `
        <div class="record-head">
          <span class="record-id">${escapeHtml(r['记录编号'])}</span>
          <span class="record-classroom">教室 ${escapeHtml(r['教室'])}</span>
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
        </div>
      `;
      list.appendChild(el);
    });

    // 绑定按钮
    list.querySelectorAll('.record-actions button').forEach(btn => {
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
});

/* ============================================================
   初始化
   ============================================================ */
loadLandingStats();
