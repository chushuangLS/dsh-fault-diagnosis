/* ============================================================
   机房故障智能诊断助手 - 前端逻辑
   ============================================================ */

const $ = (sel) => document.querySelector(sel);

/**
 * 内联 SVG 图标（供动态生成的 HTML 使用）
 *
 * 统一走这里，避免各处直接写 emoji ——
 * emoji 在不同系统渲染差异大，且无法用 CSS 控制大小与颜色。
 *
 * @param {string} name 图标 id（定义见 index.html 的 <symbol>）
 * @param {number} size 像素尺寸
 */
function icon(name, size = 16) {
  return `<svg class="icon" width="${size}" height="${size}" aria-hidden="true">`
       + `<use href="#${name}"/></svg>`;
}

/* ============================================================
   落地页 ↔ 主应用 切换
   ============================================================ */
const landingEl = $('#landing');
const appEl = $('#app');
let currentView = 'chat';

/**
 * 切换背景的动静程度
 *
 * 落地页用清晰的线条当视觉主体；进入应用后淡化一半，
 * 既能看出背景在动，又不干扰读表格与对话。
 * 透明度本身由 background.js 做渐变，这里只发指令。
 */
function setBgMode(mode) {
  if (window.BgField) window.BgField.setMode(mode);
}

function enterApp(view) {
  animateNumbersReset();
  setBgMode('app');
  initSettingsModal();
  landingEl.classList.add('exit');
  setTimeout(() => {
    landingEl.classList.add('hidden');
    appEl.classList.remove('hidden');
    switchView(view || 'chat');
    // 进入应用时侧边栏保持收起，鼠标靠近右侧再展开
    collapseRail();
    refreshRailStats();
    // 教室结构可能刚被改过（改名、增删），下拉必须重拉
    loadRoomPicker();
  }, 380);
}

function backToLanding() {
  setBgMode('landing');
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

// 侧边栏顶部按钮：返回首页
$('#rail-home').addEventListener('click', backToLanding);

/* ============================================================
   右侧伸缩侧边栏

   收起时只显示图标；鼠标靠近右侧热区、或悬停在栏上时展开。
   移开后延迟收起 —— 避免鼠标掠过时频繁弹动。
   ============================================================ */
const railEl = $('#rail');

/* 收起延迟（毫秒）
   留一点缓冲，鼠标从栏上划向内容区时不会立刻缩回去 */
const RAIL_HIDE_DELAY = 260;

let railHideTimer = null;

function expandRail() {
  if (railHideTimer) {
    clearTimeout(railHideTimer);
    railHideTimer = null;
  }
  railEl.classList.add('expanded');
}

function collapseRail() {
  railEl.classList.remove('expanded');
}

function scheduleCollapseRail() {
  if (railHideTimer) clearTimeout(railHideTimer);
  railHideTimer = setTimeout(() => {
    railHideTimer = null;
    collapseRail();
  }, RAIL_HIDE_DELAY);
}

// 鼠标靠近右侧边缘 → 展开
const railHotzone = $('#rail-hotzone');
if (railHotzone) {
  railHotzone.addEventListener('pointerenter', expandRail);
}

// 悬停在侧边栏上 → 保持展开；移开 → 延迟收起
railEl.addEventListener('pointerenter', expandRail);
railEl.addEventListener('pointerleave', scheduleCollapseRail);

// 键盘可达性：Tab 聚焦到侧边栏内的按钮时也展开
railEl.addEventListener('focusin', expandRail);
railEl.addEventListener('focusout', scheduleCollapseRail);

/* ============================================================
   侧边栏拖拽（按住栏内任意位置即可拖动）

   交互约定：
     按住不动再松开 → 正常点击按钮
     按住后移动     → 拖动侧边栏（跟随鼠标）
     双击           → 恢复默认位置（右侧居中）

   为什么不需要长按等待：
     浏览器只在"按下与松开在同一元素上、且中间没有明显移动"时才派发
     click。拖动时用户一直按着不放，松手的位置已经变了，
     那次 click 本来就不会触发按钮。
     所以按下即可进入拖动，不必等计时器，手感更跟手。

   仍然保留一个小的位移容差（3px）：
     纯粹为了兜住手抖——按下时轻微抖动不会把点击变成拖动。

   为什么用 pointer 事件而不是 mouse 事件：
     pointer 同时覆盖鼠标、触控笔和触摸屏，一套代码全平台可用。
    ============================================================ */
const RAIL_POS_KEY = 'rail-position';

/** 超出这个位移才算拖动（兜住按下瞬间的手抖） */
const RAIL_MOVE_TOLERANCE = 3;

/**
 * 决定展开方向：永远朝屏幕内侧生长
 *
 * 原因：侧边栏可以拖到任意位置，如果展开方向固定，
 *       靠左时向左长、靠右时向右长，都会冲出屏幕。
 *
 * 判定规则（按栏的中心点落在哪半屏）：
 *   中心在右半屏 → grow-left   固定右边，向左生长
 *   中心在左半屏 → grow-right  固定左边，向右生长
 *
 * 注意要在**收起状态**下测量，否则拿到的宽度是展开后的。
 */
function updateRailGrowDir() {
  const r = railEl.getBoundingClientRect();
  const centerX = r.left + r.width / 2;
  const toRight = centerX < window.innerWidth / 2;

  railEl.classList.toggle('grow-right', toRight);
  railEl.classList.toggle('grow-left', !toRight);
}

/** 把 left/top 换算成 CSS 值，并保证整个栏都在视口内 */
function clampRailPos(left, top) {
  const r = railEl.getBoundingClientRect();
  const maxLeft = window.innerWidth - r.width - 6;
  const maxTop = window.innerHeight - r.height - 6;
  return {
    left: Math.min(Math.max(left, 6), Math.max(maxLeft, 6)),
    top: Math.min(Math.max(top, 6), Math.max(maxTop, 6)),
  };
}

/**
 * 应用位置：切换为左上角定位
 *
 * 定位与展开方向的关系：
 *   栏靠左时用 left 锚定 → 宽度增加时向右长（grow-right）
 *   栏靠右时用 right 锚定 → 宽度增加时向左长（grow-left）
 * 因此这里不能一律写成 left，否则靠右的栏展开后会冲出屏幕。
 */
function applyRailPos(left, top) {
  const r = railEl.getBoundingClientRect();
  const anchorByRight = (left + r.width / 2) >= window.innerWidth / 2;

  if (anchorByRight) {
    // 用右边锚定：距右侧的距离 = 视口宽 - 左边缘 - 宽度
    const rightGap = Math.round(window.innerWidth - left - r.width);
    railEl.style.right = Math.max(rightGap, 6) + 'px';
    railEl.style.left = 'auto';
  } else {
    railEl.style.left = left + 'px';
    railEl.style.right = 'auto';
  }

  railEl.style.top = top + 'px';
  railEl.style.transform = 'none';
  railEl.classList.add('moved');
}

/** 恢复默认位置：右侧、垂直居中 */
function resetRailPos() {
  railEl.style.left = '';
  railEl.style.top = '';
  railEl.style.right = '';
  railEl.style.transform = '';
  railEl.classList.remove('moved', 'grow-right');
  railEl.classList.add('grow-left');
  try {
    localStorage.removeItem(RAIL_POS_KEY);
  } catch { /* 隐私模式下可能不可用 */ }
}

// 启动时恢复上次位置
(function restoreRailPos() {
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(RAIL_POS_KEY) || 'null');
  } catch { /* 忽略损坏的数据 */ }

  if (saved && typeof saved.left === 'number' && typeof saved.top === 'number') {
    // 等布局完成后再定位，否则拿到的尺寸是 0
    requestAnimationFrame(() => {
      const p = clampRailPos(saved.left, saved.top);
      applyRailPos(p.left, p.top);
      updateRailGrowDir();
    });
  } else {
    // 默认靠右：向左展开
    railEl.classList.add('grow-left');
  }
})();

// 窗口尺寸变化时，把栏重新约束回视口内，并重算展开方向
window.addEventListener('resize', () => {
  if (!railEl.classList.contains('moved')) {
    updateRailGrowDir();
    return;
  }
  const r = railEl.getBoundingClientRect();
  const p = clampRailPos(r.left, r.top);
  applyRailPos(p.left, p.top);
  updateRailGrowDir();
});

(function enableRailDrag() {
  let dragging = false;       // 是否已进入拖动
  let armed = false;          // 已按下、等待判断是"点击"还是"拖动"
  let startX = 0, startY = 0;
  let originLeft = 0, originTop = 0;

  /** 结束拖动，保存位置 */
  const endDrag = () => {
    armed = false;
    if (!dragging) return;

    dragging = false;
    railEl.classList.remove('dragging');

    // 拖动结束后重算展开方向：拖到左半屏就该向右长了
    updateRailGrowDir();

    const r = railEl.getBoundingClientRect();
    try {
      localStorage.setItem(RAIL_POS_KEY,
        JSON.stringify({ left: Math.round(r.left), top: Math.round(r.top) }));
    } catch { /* 存不下就算了，不影响使用 */ }
  };

  railEl.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;          // 只响应左键

    armed = true;
    dragging = false;
    startX = e.clientX;
    startY = e.clientY;

    const r = railEl.getBoundingClientRect();
    originLeft = r.left;
    originTop = r.top;
  });

  document.addEventListener('pointermove', (e) => {
    if (!armed) return;

    // 超过容差才算真的在拖 —— 这一步同时兜住按下瞬间的手抖，
    // 也保证"想点按钮"时不会被误判成拖动
    if (!dragging) {
      const dx = Math.abs(e.clientX - startX);
      const dy = Math.abs(e.clientY - startY);
      if (dx < RAIL_MOVE_TOLERANCE && dy < RAIL_MOVE_TOLERANCE) return;

      dragging = true;
      railEl.classList.add('dragging');
      expandRail();                      // 拖动时保持展开，方便看清整栏
    }

    e.preventDefault();                  // 阻止选中文字等默认行为

    const p = clampRailPos(
      originLeft + (e.clientX - startX),
      originTop + (e.clientY - startY),
    );
    applyRailPos(p.left, p.top);
  });

  document.addEventListener('pointerup', endDrag);
  document.addEventListener('pointercancel', endDrag);

  // 拖动中不应弹出右键菜单
  railEl.addEventListener('contextmenu', (e) => {
    if (dragging) e.preventDefault();
  });

  // 兜底：万一浏览器仍在拖动后派发了 click，这里拦掉
  // （正常情况下 click 不会触发，因为按下与松开已不在同一位置）
  railEl.addEventListener('click', (e) => {
    if (dragging) {
      e.preventDefault();
      e.stopPropagation();
    }
  }, true);

  // 双击恢复默认位置（拖到找不到的地方时用）
  railEl.addEventListener('dblclick', (e) => {
    e.preventDefault();
    resetRailPos();
  });
})();

/* ============================================================
   视图切换
   ============================================================ */
function switchView(view) {
  currentView = view;

  // 侧边栏导航项高亮
  document.querySelectorAll('.rail-item[data-view]').forEach(t => {
    t.classList.toggle('active', t.dataset.view === view);
  });

  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  const target = $('#view-' + view);
  if (target) target.classList.add('active');

  if (view === 'records') loadRecords();
  if (view === 'stats') loadStats();
  if (view === 'schedule') loadSchedulePage();
  if (view === 'tasks') loadTasks();
  if (view === 'chat') {
    const inp = $('#input');
    if (inp) setTimeout(() => inp.focus(), 100);
  }
  refreshRailStats();
}

// 侧边栏导航点击
document.querySelectorAll('.rail-item[data-view]').forEach(item => {
  item.addEventListener('click', () => switchView(item.dataset.view));
});

/* ============================================================
   侧边栏数据更新
   ============================================================ */
let sessionRounds = 0;
let currentClassroom = '';
let sessionState = '待开始';

/**
 * 侧边栏上的角标与统计
 *
 * 上报「待处理」数量：未报修 + 可自修 + 已报修。
 * 收起状态下角标会缩成一个小红点，展开时显示具体数字。
 */
async function refreshRailStats() {
  let pending = 0;

  try {
    const res = await fetch('/api/records');
    const d = await res.json();
    const records = d.records || [];
    pending = records.filter(r => r['状态'] !== '已解决')
                     .reduce((n, r) => n + (parseInt(r['数量'], 10) || 1), 0);
  } catch { /* 忽略，角标保持原样 */ }

  const badge = $('#rail-badge-records');
  if (badge) {
    badge.textContent = pending > 99 ? '99+' : pending;
    badge.classList.toggle('show', pending > 0);
  }

  try {
    const res = await fetch('/api/classrooms/summary');
    const s = await res.json();
    const set = (id, v) => {
      const el = $(id);
      if (el) el.textContent = (v ?? '—');
    };
    set('#d-rooms', s.rooms);
    set('#d-pcs', s.total_pcs);
    set('#d-broken', s.broken_pcs);
  } catch { /* 忽略 */ }
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
      body.innerHTML = `<span class="inline-warn">${icon('i-alert', 15)} `
                     + escapeHtml(err.error || '请求失败') + '</span>';
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
                      }

          // 知识库沉淀提示（体现"越用越聪明"）
          if (evt.finished && evt.case_saved) {
            const note = document.createElement('div');
            note.className = 'kb-note';
            note.textContent = '本次诊断已沉淀为新案例，知识库可以复用这个经验了';
            body.parentNode.appendChild(note);
          }

          // 更新抽屉状态
          sessionRounds++;
          if (evt.classroom) currentClassroom = evt.classroom;
          sessionState = evt.finished ? '已完成' : '排查中';
          refreshRailStats();

          if (evt.finished) {
            setTimeout(() => {
              sessionRounds = 0;
              currentClassroom = '';
              sessionState = '待开始';
              refreshRailStats();
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
          body.innerHTML = `<span class="inline-warn">${icon('i-alert', 15)} `
                         + escapeHtml(evt.message) + '</span>';
        }
      }
    }

  } catch (err) {
    if (cursor) cursor.remove();
    if (dots.parentNode) dots.remove();
    body.innerHTML = `<span class="inline-warn">${icon('i-alert', 15)} 网络错误：`
                   + escapeHtml(err.message) + '</span>';
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
    refreshRailStats();
  } catch (err) {
    addTurn('重置失败：' + err.message, 'bot');
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

  // 桌面窗口（pywebview）里没有浏览器下载通道：
  // winforms 后端没有实现 WebView2 的 DownloadStarting，
  // a.click() 触发的下载会被静默丢弃 —— 用户看到的就是"没反应"。
  // 所以窗口里改成"服务端存盘 + 显示路径"，浏览器里仍走下载。
  //
  // 这个判断必须放在点击时做：pywebview 是在页面加载之后才注入
  // window.pywebview 的，脚本加载时就判断会永远是 false。
  function inDesktop() {
    return !!window.pywebview;
  }

  function showResult(html) {
    const box = document.getElementById('export-result');
    if (!box) return;
    box.innerHTML = html;
    box.classList.remove('hidden');
  }

  btn.addEventListener('click', async () => {
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = '正在生成…';

    try {
      if (inDesktop()) {
        await exportToDisk();
        return;
      }

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

  /** 桌面窗口版：让后端直接写文件，然后把路径显示出来 */
  async function exportToDisk() {
    const res = await fetch('/api/export/repair/save', { method: 'POST' });
    const d = await res.json();

    if (!d.ok) {
      showResult(`<span class="er-bad">导出失败：${escapeHtml(d.message || '未知原因')}</span>`);
      return;
    }

    const kb = d.size ? ` · ${Math.round(d.size / 1024)} KB` : '';
    showResult(`
      <span class="er-ok">已导出 ${escapeHtml(d.filename)}${kb}</span>
      <span class="er-path">${escapeHtml(d.path)}</span>
      <button class="btn-ghost btn-sm er-open">打开所在文件夹</button>`);

    const openBtn = document.querySelector('#export-result .er-open');
    if (openBtn) {
      openBtn.addEventListener('click', () => {
        fetch('/api/export/open-folder', { method: 'POST' }).catch(() => {});
      });
    }
  }
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
        <button class="modal-close" id="er-close" title="关闭">${icon('i-close', 16)}</button>
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

/**
 * 骨架屏 HTML（加载占位）
 *
 * 为什么用骨架屏而不是"加载中…"：
 *   骨架屏提前展示最终布局的轮廓，视觉上更接近"马上就出来"，
 *   感知等待时间明显更短；纯文字会让人觉得页面卡住了。
 */
function skeletonCards(n = 3, height = 96) {
  return Array.from({ length: n })
    .map(() => `<div class="skeleton skeleton-card" style="height:${height}px"></div>`)
    .join('');
}

function skeletonLines(n = 3) {
  return Array.from({ length: n })
    .map(() => '<div class="skeleton skeleton-line"></div>')
    .join('');
}

/**
 * 状态 → CSS 类名
 *
 * 用英文类名（st-*）而不是中文，避免中文选择器在不同环境下的编码问题。
 * 必须与 CSS 中的 .badge.st-* / .cause-item.st-* 保持一致。
 *
 * 四处状态配色（徽章 / 条目左边框 / 统计卡 / 图表）都以此为准，
 * 避免同一个状态在不同位置显示成不同颜色。
 */
const STATUS_CLASS = {
  '未报修': 'st-pending',
  '可自修': 'st-selffix',
  '已报修': 'st-reported',
  '已解决': 'st-resolved',
};

/** 状态 → 分组标题文案 */
const GROUP_META = {
  '未报修': { text: '待处理', desc: '硬件故障，还没联系维修，需要尽快跟进' },
  '可自修': { text: '可自修', desc: '非硬件问题，可以自己动手解决，不必报修' },
  '已报修': { text: '等维修', desc: '已报修，等待处理结果' },
  '已解决': { text: '已完成', desc: '故障已修复' },
};

function statusClass(status) {
  return STATUS_CLASS[status] || 'st-pending';
}

/* ============================================================
   列表分页

   所有会越堆越长的列表都走这里：超过 PAGE_SIZE 条就分页。
   起因是几个列表用久了会变成几十上百条，一路往下滚很难找东西。

   约定：
     · 每个列表用唯一的 key 记住自己停在第几页
     · 只有一页时不显示分页条（不占地方）
   ============================================================ */

const PAGE_SIZE = 10;
const pageState = {};   // 列表 key → 当前页（从 0 开始）

/**
 * 按页切分
 *
 * 返回 {slice, page, pages, total}。
 * 页码越界时自动回到最后一页 —— 删除记录后总数变少会碰到这种情况。
 */
function paginate(key, items, size) {
  const ps = size || PAGE_SIZE;
  const total = items.length;
  const pages = Math.max(Math.ceil(total / ps), 1);

  let page = pageState[key] || 0;
  if (page >= pages) page = pages - 1;
  if (page < 0) page = 0;
  pageState[key] = page;

  return {
    slice: items.slice(page * ps, (page + 1) * ps),
    page,
    pages,
    total,
  };
}

/** 分页条 HTML（只有一页时返回空串） */
function pagerHtml(key, page, pages, total) {
  if (pages <= 1) return '';
  return `
    <div class="pager">
      <button class="pager-btn" data-pager-page="${page - 1}"
        ${page === 0 ? 'disabled' : ''}>‹ 上一页</button>
      <span class="pager-info">第 ${page + 1} / ${pages} 页 · 共 ${total} 条</span>
      <button class="pager-btn" data-pager-page="${page + 1}"
        ${page === pages - 1 ? 'disabled' : ''}>下一页 ›</button>
    </div>`;
}

/**
 * 绑定分页按钮
 *
 * onGo(page) 由调用方负责"换页并重渲染"。
 */
function bindPager(container, key, onGo) {
  container.querySelectorAll('[data-pager-page]').forEach(btn => {
    if (btn.disabled) return;
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      pageState[key] = parseInt(btn.dataset.pagerPage, 10) || 0;
      onGo();
    });
  });
}

async function loadRecords() {
  const list = $('#record-list');
  list.innerHTML = skeletonCards(4);

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
      list.innerHTML = `<div class="empty">
        <svg class="icon empty-icon" width="40" height="40"><use href="#i-inbox"/></svg>
        <p>暂无${currentStatus ? '「' + escapeHtml(currentStatus) + '」状态的' : ''}记录</p>
        <span class="empty-hint">去「诊断」页描述一个故障，这里会自动记录</span>
      </div>`;
      return;
    }

    list.innerHTML = '';

    // 分页：一页 10 条。分组标题在当前页内照常出现，
    // 跨页的同一个状态会在新一页顶部再出现一次，不碍事。
    const pg = paginate('records', data.records);

    let lastStatus = null;

    pg.slice.forEach(r => {
      // 状态切换时插入分组标题
      if (r['状态'] !== lastStatus) {
        lastStatus = r['状态'];
        const meta = GROUP_META[r['状态']] || { text: r['状态'], desc: '' };
        const head = document.createElement('div');
        head.className = `group-head ${statusClass(r['状态'])}`;
        head.innerHTML = `
          <span class="gh-dot"></span>
          <span class="gh-text">${escapeHtml(meta.text)}</span>
          <span class="gh-desc">${escapeHtml(meta.desc)}</span>
        `;
        list.appendChild(head);
      }

      const el = document.createElement('div');
      el.className = 'record';

      // 位置显示：用「教学楼 · 教室」代替记录编号作为标题
      // 教室是运维人员最关心的信息，编号对使用者没有意义（仅在内部用于接口调用）
      let roomHtml;
      if (r['教学楼'] && r['教学楼'] !== '未标注教学楼') {
        roomHtml = `<span class="record-classroom">
            <span class="rc-building">${escapeHtml(r['教学楼'])}</span>
            <span class="rc-sep">·</span>
            <span class="rc-room">${escapeHtml(r['教室'])}</span>
          </span>`;
      } else if (r['教室'] && r['教室'] !== '未填写') {
        roomHtml = `<span class="record-classroom">
            <span class="rc-room">${escapeHtml(r['教室'])}</span>
            <span class="no-building">未关联教学楼</span>
          </span>`;
      } else {
        roomHtml = `<span class="record-classroom warn">
            <span class="rc-room">教室未填写</span>
          </span>`;
      }

      // 数量标签（一条记录可能代表多台设备）
      const qty = parseInt(r['数量'], 10) || 1;
      const qtyHtml = qty > 1 ? `<span class="qty-tag">${qty} 台</span>` : '';

      el.innerHTML = `
        <div class="record-head">
          ${roomHtml}
          ${qtyHtml}
          <span class="badge ${statusClass(r['状态'])}">${escapeHtml(r['状态'])}</span>
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
        refreshRailStats();
      });
    });

    // 分页条追加在最后
    const pagerBox = document.createElement('div');
    pagerBox.innerHTML = pagerHtml('records', pg.page, pg.pages, pg.total);
    if (pagerBox.firstElementChild) {
      list.appendChild(pagerBox.firstElementChild);
      bindPager(list, 'records', () => loadRecords());
    }

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
  const btn = $('#ov-refresh');

  // 刷新时按钮转圈、禁用 —— 否则点下去没有任何反应，
  // 用户会以为"刷新是假的"（实际上它之前连事件都没绑）
  if (btn) {
    btn.disabled = true;
    btn.classList.add('spinning');
  }

  let d;
  try {
    const res = await fetch('/api/overview', { cache: 'no-store' });
    d = await res.json();
    if (d.error) throw new Error(d.error);
  } catch (err) {
    emptyEl.classList.remove('hidden');
    emptyEl.textContent = '读取失败：' + err.message;
    if (btn) { btn.disabled = false; btn.classList.remove('spinning'); }
    return;
  }

  if (btn) {
    btn.disabled = false;
    btn.classList.remove('spinning');
  }

  if (!d.rooms || !d.rooms.length) {
    emptyEl.classList.remove('hidden');
    return;
  }
  emptyEl.classList.add('hidden');

  const kpi = d.kpi || {};

  // ---- KPI ----
  $('#kpi-rate').textContent = (kpi.available_rate ?? 100) + '%';
  $('#kpi-broken').textContent = kpi.broken_pcs ?? 0;
  $('#kpi-pending-records').textContent = kpi.pending_records ?? 0;
  $('#kpi-repeat').textContent = kpi.repeat_count ?? 0;
  $('#kpi-rooms').textContent = kpi.room_count ?? 0;

  $('#dash-updated').textContent =
    '第 ' + (d.week || '—') + ' 周 · '
    + new Date().toLocaleTimeString('zh-CN');

  renderOverviewWarnings(d.warnings || [], d);
  renderOverviewGrid(d.rooms || []);
  renderOverviewCategories(d.categories || []);
  renderOverviewTrend(d.trend || {});

  bindOverviewJumps();
  bindOverviewRefresh();

  // 反复故障单独取，逻辑在 loadRepeatedFaults 里
  loadRepeatedFaults();
}

/**
 * 今天受影响的课
 *
 * 每条 = 一节课（教室 × 节次 × 课程）。
 * 分成「进行中 / 待开始 / 已结束」三态，进行中最急。
 *
 * 没有受影响时整块隐藏 —— 不显示"一切正常"，那只是占地方。
 */
function renderOverviewWarnings(list, d) {
  const card = $('#ov-warn');
  const box = $('#ov-warn-list');
  const more = $('#ov-warn-more');
  const note = $('#ov-warn-note');
  if (!card || !box) return;

  if (!list.length) {
    card.classList.add('hidden');
    return;
  }
  card.classList.remove('hidden');

  const ongoing = list.filter(x => x.state === 'ongoing').length;
  const rooms = list.length;
  const classes = list.reduce((s, x) => s + (x.class_count || 1), 0);
  note.textContent = `${rooms} 间教室 · ${classes} 节课`
    + (ongoing ? ` · 其中 ${ongoing} 间正在进行` : '');

  // 分页：一页 10 条，不再用「展开全部」那种一铺到底的做法
  const pg = paginate('warnings', list);

  box.innerHTML = pg.slice.map(x => {
    const cls = x.state === 'ongoing' ? 'warn-ongoing'
      : x.state === 'upcoming' ? 'warn-upcoming'
      : x.state === 'past' ? 'warn-past' : 'warn-unknown';

    const tag = x.state === 'ongoing' ? '进行中'
      : x.state === 'upcoming' ? '待开始'
      : x.state === 'past' ? '已结束' : '未知';

    // 节次范围：只有一节时写"第 3 节"，多节时写"第 1–12 节"
    const from = x.period_from != null ? x.period_from : x.period;
    const to = x.period_to != null ? x.period_to : from;
    const periodText = from === to ? `第 ${from} 节` : `第 ${from}–${to} 节`;

    const count = x.class_count || 1;
    const c = x.course || {};
    const names = x.course_names || (c.name ? [c.name] : []);

    // 多节课时不要只写"第一门课 等"，那样读着断句不对
    let title;
    if (count > 1) {
      title = names.length > 1
        ? `${names[0]} 等 ${names.length} 门课`
        : (names[0] || '');
    } else {
      title = names[0] || c.name || '';
    }

    const badge = count > 1 ? `<span class="warn-count-badge">${count} 节课</span>` : '';

    const suggest = (x.suggest || []).length
      ? x.suggest.map(s =>
          `${escapeHtml(s.building)}-${escapeHtml(s.room)}（${s.seats} 座）`
        ).join(' · ')
      : '本时段无空闲教室';

    const suggestNote = count > 1
      ? `<span class="warn-suggest-note">（以第 ${x.suggest_period} 节为例）</span>`
      : '';

    return `
      <div class="warn-item ${cls}">
        <div class="warn-main">
          <span class="warn-tag">${tag}</span>
          <span class="warn-day">${escapeHtml(x.day_label || '')}</span>
          <span class="warn-when">${periodText}</span>
          <span class="warn-room">${escapeHtml(x.building)}-${escapeHtml(x.room)}</span>
          ${badge}
        </div>
        <div class="warn-course">
          ${escapeHtml(title)}
          <span class="warn-meta">最多 ${x.students || 0} 人</span>
        </div>
        <div class="warn-reason">${escapeHtml((x.reasons || []).join('；'))}</div>
        <div class="warn-suggest">→ 可调课到 ${suggest}${suggestNote}</div>
      </div>`;
  }).join('') + pagerHtml('warnings', pg.page, pg.pages, pg.total);

  // 旧的「展开全部」不再需要，统一交给分页
  if (more) more.classList.add('hidden');

  bindPager(box, 'warnings', () => {
    // 直接用缓存的数据重渲染，不重新请求
    renderOverviewWarnings(list, d);
  });
}

/**
 * 教室状态网格
 *
 * 判定的是「还能不能上课」，不是「坏了几台」——
 * 78 人的课坏 2 台照样能上；教师机坏了却一台不缺也上不了。
 * 坏几台放在底部小灰字里，不抢视线。
 */
// 哪些楼栋被展开了（按楼栋记，互不影响）
let ovExpanded = new Set();
// 最近一次渲染用的教室列表 —— 展开/收起时用它原位重渲染
let ovRooms = [];

function renderOverviewGrid(rooms) {
  const box = $('#ov-grid');
  if (!box) return;

  ovRooms = rooms || [];

  // 按教学楼分组，保持原顺序
  const byBuilding = new Map();
  rooms.forEach(r => {
    if (!byBuilding.has(r.building)) byBuilding.set(r.building, []);
    byBuilding.get(r.building).push(r);
  });

  const LIMIT = 8;

  box.innerHTML = [...byBuilding.entries()].map(([building, list]) => {
    // 折叠时优先显示「影响上课」的，其次有损坏的，最后正常的
    const rank = (x) => (x.impact ? 0 : (x.broken || x.facility) ? 1 : 2);
    const sorted = [...list].sort((a, b) => rank(a) - rank(b));

    // 展开状态按楼栋记，不影响其它楼栋，也不重排数组 ——
    // 之前是"把展开的楼栋挪到末尾再整份重渲染"，
    // 结果一展开，这栋楼就跑到另一栋下面去了
    const expanded = ovExpanded.has(building);
    const shown = expanded ? sorted : sorted.slice(0, LIMIT);
    const rest = sorted.length - shown.length;

    const cells = shown.map(r => {
      const classes = ['ov-cell'];
      if (r.impact) classes.push('ov-cell-bad');
      else classes.push('ov-cell-ok');

      // 底部小灰字：坏几台 / 设施故障 / 未导课表
      const notes = [];
      if (r.broken) notes.push(`坏 ${r.broken} 台`);
      if (r.facility) notes.push('设施故障');
      if (!r.has_schedule) notes.push('无课表');

      // 这节课的状态
      let classLine;
      if (r.class) {
        classLine = `<span class="oc-class">课中 · ${r.class.students || 0} 人</span>`;
      } else if (!r.has_schedule) {
        classLine = '';
      } else {
        classLine = '<span class="oc-idle">没课</span>';
      }

      const reason = r.impact
        ? `<span class="oc-reason">${escapeHtml((r.reasons || []).join('；'))}</span>`
        : '';

      return `
        <div class="${classes.join(' ')}"
             data-building="${escapeHtml(r.building)}"
             data-room="${escapeHtml(r.room)}">
          <span class="oc-name">${escapeHtml(r.room)}</span>
          <span class="oc-state">${r.impact ? '⚠ 影响上课' : '● 正常'}</span>
          ${reason}
          ${classLine}
          ${notes.length ? `<span class="oc-note">${notes.join(' · ')}</span>` : ''}
        </div>`;
    }).join('');

    const more = sorted.length > LIMIT
      ? `<button class="ov-more-btn" data-expand="${escapeHtml(building)}">
           ${expanded ? '收起' : `展开全部 ${sorted.length} 间`}
         </button>`
      : '';

    return `
      <div class="ov-building">
        <div class="ov-building-head">
          ${escapeHtml(building)}
          <span class="ov-building-count">${list.length} 间</span>
        </div>
        <div class="ov-cells">${cells}</div>
        ${more}
      </div>`;
  }).join('');

  // 点格子 → 教室详情（故障视角）
  box.querySelectorAll('.ov-cell').forEach(el => {
    el.addEventListener('click', (e) => {
      // 点"课中"那一小块 → 看课表，不是看故障
      if (e.target.closest('.oc-class')) {
        openRoomSchedule(el.dataset.building, el.dataset.room);
        return;
      }
      gotoRoomDetail(el.dataset.room);
    });
  });

  // 展开/收起：只改这一栋楼显示几格，不改顺序
  box.querySelectorAll('.ov-more-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const b = btn.dataset.expand;
      if (ovExpanded.has(b)) ovExpanded.delete(b);
      else ovExpanded.add(b);
      renderOverviewGrid(ovRooms);
    });
  });
}

/**
 * 故障类型分布
 *
 * 用 CSS 横条而不是图表库 —— 这里只有几个分类，
 * 用 ECharts 反而更重，而且要处理 resize。
 */
function renderOverviewCategories(items) {
  const box = $('#ov-cats');
  if (!box) return;

  if (!items.length) {
    box.innerHTML = '<div class="ov-none">暂无数据</div>';
    return;
  }

  // 显示前 6 类，其余合并成「其他 N 类」
  const TOP = 6;
  const top = items.slice(0, TOP);
  const rest = items.slice(TOP);
  const restCount = rest.reduce((s, x) => s + x.count, 0);

  const max = Math.max(...top.map(x => x.count), 1);

  const row = (name, count, isRest) => `
    <div class="ov-cat ${isRest ? 'ov-cat-rest' : ''}" data-cat="${escapeHtml(name)}">
      <span class="ov-cat-name">${escapeHtml(name)}</span>
      <span class="ov-cat-bar">
        <i style="width:${Math.round(count / max * 100)}%"></i>
      </span>
      <span class="ov-cat-count">${count}</span>
    </div>`;

  box.innerHTML = top.map(x => row(x.category, x.count, false)).join('')
    + (rest.length
      ? row(`其他 ${rest.length} 类`, restCount, true)
      : '');

  // 点某一类 → 跳报修记录（按该类筛选需要后端支持，这里先跳到台账）
  box.querySelectorAll('.ov-cat').forEach(el => {
    el.addEventListener('click', () => {
      if (el.classList.contains('ov-cat-rest')) return;
      switchView('records');
    });
  });
}

/** 近 14 天趋势：新增 vs 解决 */
function renderOverviewTrend(t) {
  const el = $('#chart-trend');
  if (!el) return;

  // 数据太少时不画假线 —— 只有 2 天数据画出来的折线没有意义，
  // 看起来还会像"故障在骤降"，是误导。
  // 但也不能留一块空白，所以给一句说明。
  if ((t.active_days || 0) < 3) {
    if (chartTrend) { chartTrend.dispose(); chartTrend = null; }
    el.innerHTML = `
      <div class="ov-none ov-trend-none">
        数据积累中
        <span>已有 ${t.active_days || 0} 天记录，满 3 天才显示趋势</span>
      </div>`;
    return;
  }

  // 之前若有占位文字，先清掉再初始化图表
  if (el.querySelector('.ov-none')) el.innerHTML = '';
  chartTrend = initChart(el, chartTrend);

  chartTrend.setOption({
    ...CHART_BASE,
    tooltip: { trigger: 'axis' },
    legend: {
      right: 6, top: 0,
      textStyle: { color: '#8b98a5' },
      itemWidth: 12, itemHeight: 12,
    },
    grid: { left: 12, right: 18, top: 34, bottom: 10, containLabel: true },
    xAxis: {
      type: 'category',
      data: (t.dates || []).map(x => x.slice(5)),
      boundaryGap: false,
      axisLine: { lineStyle: { color: '#2d3843' } },
      axisLabel: { color: '#8b98a5', fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: '#222b35' } },
      axisLabel: { color: '#8b98a5', fontSize: 10 },
    },
    series: [
      {
        name: '新增',
        type: 'line',
        data: t.new || [],
        smooth: true,
        symbolSize: 6,
        lineStyle: { width: 2.4, color: '#3b82f6' },
        itemStyle: { color: '#3b82f6' },
      },
      {
        name: '解决',
        type: 'line',
        data: t.resolved || [],
        smooth: true,
        symbolSize: 6,
        lineStyle: { width: 2.4, color: '#22c55e' },
        itemStyle: { color: '#22c55e' },
      },
    ],
  }, true);
}

/**
 * 刷新按钮
 *
 * 这个按钮以前是纯装饰 —— HTML 里有，但从没绑过事件，
 * 点下去毫无反应。在台账里把故障标成已解决之后回到总览点刷新，
 * 数据当然不会变，看起来就像"假刷新"。
 */
function bindOverviewRefresh() {
  const btn = $('#ov-refresh');
  if (!btn || btn.dataset.bound) return;
  btn.dataset.bound = '1';
  btn.addEventListener('click', () => loadStats());
}

/** KPI 与图表卡片的点击跳转 */
function bindOverviewJumps() {
  document.querySelectorAll('[data-ov-go]').forEach(el => {
    if (el.dataset.bound) return;
    el.dataset.bound = '1';
    el.addEventListener('click', () => {
      const go = el.dataset.ovGo;
      if (go === 'rooms') {
        openAdmin();
      } else if (go === 'pending') {
        gotoRecordsWithStatus('未报修');
      } else if (go === 'repeat') {
        const card = $('#repeat-list');
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    });
  });
}

async function loadRepeatedFaults() {
  const box = $('#repeat-list');
  if (!box) return;

  box.innerHTML = '<div class="repeat-empty">读取中…</div>';

  let data;
  try {
    const res = await fetch('/api/analytics/repeated-faults');
    data = await res.json();
    if (data.error) throw new Error(data.error);
  } catch (err) {
    box.innerHTML = `<div class="repeat-empty">读取失败：${escapeHtml(err.message)}</div>`;
    return;
  }

  const hint = $('#repeat-hint');
  if (hint) {
    hint.textContent =
      `同一教室同一原因累计 ≥${data.min_count} 次 · ` +
      `复发指修好后又出现 ≥${data.min_recur} 次`;
  }

  if (!data.items.length) {
    box.innerHTML = `
      <div class="repeat-empty">
        暂无反复故障
        <span>同一间教室同一类故障累计 ${data.min_count} 次以上才会列在这里</span>
      </div>`;
    return;
  }

  const pg = paginate('repeat', data.items);

  box.innerHTML = pg.slice.map(x => {
    const span = x.span_days > 0 ? `${x.span_days} 天` : '当天';
    const recur = x.recurring
      ? `<span class="repeat-recur">⚠ 复发 ${x.recur} 次</span>`
      : (x.recur ? `<span class="repeat-recur-weak">复发 ${x.recur} 次</span>` : '');

    return `
      <div class="repeat-item" data-room="${escapeHtml(x.room)}"
           data-building="${escapeHtml(x.building)}">
        <span class="repeat-where">
          ${escapeHtml(x.building)}-${escapeHtml(x.room)}
        </span>
        <span class="repeat-cat">${escapeHtml(x.category)}</span>
        <span class="repeat-count"><b>${x.count}</b> 次 / ${span}</span>
        ${recur}
      </div>`;
  }).join('') + pagerHtml('repeat', pg.page, pg.pages, pg.total);

  // 点条目 → 打开该教室详情
  box.querySelectorAll('.repeat-item').forEach(el => {
    el.addEventListener('click', () => {
      gotoRoomDetail(el.dataset.room);
    });
  });

  bindPager(box, 'repeat', () => loadRepeatedFaults());
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

/* ============================================================
   从数据看板跳到明细

   看板上看到"某状态有 N 条"或"某间教室故障最多"之后，
   下一步一定是要看具体是哪些记录/哪间教室。
   让图表可以直接点，省掉"切页 → 再筛选"这两步。
   ============================================================ */

/**
 * 跳到报修台账，并筛成指定状态
 * 数据看板的「状态分布」饼图点击时调用
 */
function gotoRecordsWithStatus(status) {
  if (!status) return;

  // 先设好筛选条件再切页 —— switchView 内部会调 loadRecords()，
  // 它按 currentStatus 拼接口参数
  currentStatus = status;
  switchView('records');

  // 同步顶部筛选按钮的高亮（loadRecords 不负责这个）
  document.querySelectorAll('.chip[data-status]').forEach(ch => {
    ch.classList.toggle('active', ch.dataset.status === status);
  });
}

/**
 * 打开某间教室的详情
 * 数据看板的「故障教室排行」柱状图点击时调用
 *
 * 图表里只有教室号（如 101），而打开详情需要「教学楼 + 教室」。
 * 所以先查一遍教室台账把教学楼补出来；查不到就退化成打开管理弹窗，
 * 让用户自己在列表里找，至少不会点了没反应。
 */
async function gotoRoomDetail(roomName) {
  if (!roomName) return;

  let hit = null;
  try {
    const res = await fetch('/api/classrooms');
    const d = await res.json();
    hit = (d.flat || []).find(x => x.name === roomName);
  } catch { /* 取不到就退化处理 */ }

  openAdmin();

  if (!hit) return;   // 已经打开了管理弹窗，用户可自行从列表进入

  // 等弹窗渲染一帧再切到详情视图，避免和 loadClassrooms 抢 DOM
  setTimeout(() => openRoomDetail(hit.building, hit.name), 60);
}function closeAdmin() {
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

/* ============================================================
   设置弹窗（API Key / 数据目录）

   原来这两项是桌面窗口的原生菜单，但 pywebview 用的是 WinForms
   MenuStrip，浅色默认样式在深色界面里很突兀，而且改样式要动它的内部实现。
   改成侧边栏按钮 + 网页弹窗，样式统一，Web 版也能用。

   安全上后端做了限制：写 Key 的接口只接受来自 127.0.0.1 的请求，
   所以就算有人把服务开到局域网，别人也改不了你的 Key。
   ============================================================ */

const settingsModal = $('#settings-modal');

const KEY_SOURCE_TEXT = {
  env: '进程环境变量',
  file: '配置文件',
  windows: 'Windows 用户环境变量',
  disabled: '已手动清除，忽略所有来源',
  none: '未找到',
};

async function openSettings() {
  if (!settingsModal) return;
  settingsModal.classList.remove('hidden');
  $('#set-key-input').value = '';
  setKeyHint('');
  await refreshSettings();
}

function closeSettings() {
  if (settingsModal) settingsModal.classList.add('hidden');
}

function setKeyHint(text, kind) {
  const el = $('#set-key-hint');
  if (!el) return;
  el.textContent = text || '';
  el.className = 'set-hint' + (kind ? ' ' + kind : '');
}

async function refreshSettings() {
  const box = $('#set-key-status');
  if (!box) return;

  let d;
  try {
    const res = await fetch('/api/settings/api-key');
    d = await res.json();
  } catch (err) {
    box.className = 'set-status missing';
    box.textContent = '读取失败：' + err.message;
    return;
  }

  if (!d.editable) {
    // 不是本机在访问 —— 后端会拒绝写入，这里先说清楚
    box.className = 'set-status remote';
    box.textContent = '当前不是从本机访问，不能修改 API Key。';
  } else if (d.configured) {
    box.className = 'set-status ok';
    const from = KEY_SOURCE_TEXT[d.source] || d.source;
    box.textContent = `已配置：${d.masked}（来源：${from}）`;
  } else if (d.disabled) {
    // 光写"未配置"会让人困惑：系统里明明有环境变量啊
    box.className = 'set-status missing';
    box.textContent = '已清除。此时不会使用任何来源的 Key（环境变量也会被忽略）。'
      + '重新填入一个 Key 即可恢复。';
  } else {
    box.className = 'set-status missing';
    box.textContent = '还没配置。诊断功能不可用，台账和课表不受影响。';
  }

  // 不可编辑时把输入区禁用掉
  const disabled = !d.editable;
  ['#set-key-input', '#set-key-save', '#set-key-clear'].forEach(sel => {
    const el = $(sel);
    if (el) el.disabled = disabled;
  });

  const fileEl = $('#set-key-file');
  if (fileEl) {
    fileEl.textContent = d.config_file
      ? '保存位置：' + d.config_file
      : '';
  }
}

async function saveApiKey() {
  const input = $('#set-key-input');
  const key = (input.value || '').trim();
  if (!key) {
    setKeyHint('请先粘贴 Key', 'err');
    input.focus();
    return;
  }

  const btn = $('#set-key-save');
  btn.disabled = true;
  setKeyHint('保存中…');
  try {
    const res = await fetch('/api/settings/api-key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    });
    const d = await res.json();
    if (!d.ok) {
      setKeyHint(d.message || '保存失败', 'err');
    } else {
      input.value = '';
      setKeyHint('已保存，诊断立刻可用', 'ok');
      await refreshSettings();
    }
  } catch (err) {
    setKeyHint('保存失败：' + err.message, 'err');
  }
  btn.disabled = false;
}

async function clearApiKey() {
  if (!confirm('确定清除已保存的 API Key？\n清除后诊断功能不可用。')) return;

  const btn = $('#set-key-clear');
  btn.disabled = true;
  try {
    const res = await fetch('/api/settings/api-key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: '' }),
    });
    const d = await res.json();
    setKeyHint(d.ok ? '已清除' : (d.message || '清除失败'),
               d.ok ? 'ok' : 'err');
    await refreshSettings();
  } catch (err) {
    setKeyHint('清除失败：' + err.message, 'err');
  }
  btn.disabled = false;
}

async function openDataDir() {
  const hint = $('#set-dir-path');
  try {
    const res = await fetch('/api/settings/open-data-dir', { method: 'POST' });
    const d = await res.json();
    if (hint) {
      hint.textContent = d.path ? '数据目录：' + d.path : '';
    }
    if (!d.ok && d.message) alert(d.message);
  } catch (err) {
    if (hint) hint.textContent = '打开失败：' + err.message;
  }
}

function initSettingsModal() {
  if (!settingsModal || settingsModal.dataset.inited) return;
  settingsModal.dataset.inited = '1';

  const btn = $('#settings-btn');
  if (btn) btn.addEventListener('click', openSettings);
  $('#settings-close').addEventListener('click', closeSettings);
  settingsModal.addEventListener('click', (e) => {
    if (e.target === settingsModal) closeSettings();
  });

  $('#set-key-save').addEventListener('click', saveApiKey);
  $('#set-key-clear').addEventListener('click', clearApiKey);
  $('#set-open-dir').addEventListener('click', openDataDir);

  // 回车直接保存，不用去点按钮
  $('#set-key-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      saveApiKey();
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !settingsModal.classList.contains('hidden')) {
      closeSettings();
    }
  });
}

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
  refreshRailStats();
});

// ---------- 加载教室列表 ----------
async function loadClassrooms() {
  const box = $('#building-list');
  box.innerHTML = skeletonCards(3, 72);

  try {
    const res = await fetch('/api/classrooms');
    const d = await res.json();
    classroomCache = d;

    if (!d.buildings.length) {
      box.innerHTML = `<div class="empty">
        ${icon('i-building', 40).replace('class="icon"', 'class="icon empty-icon"')}
        <p>还没有教学楼</p>
        <span class="empty-hint">点击上方「添加教学楼」开始建立台账</span>
      </div>`;
      return;
    }

    box.innerHTML = d.buildings.map(b => {
      const rooms = b.rooms.length
        ? b.rooms.map(r => roomRowHtml(b.name, r)).join('')
        : `<div class="empty" style="padding:22px">
             <span class="empty-hint">该教学楼下还没有教室</span>
           </div>`;

      return `
        <div class="building-group">
          <div class="building-head">
            <span class="building-name">
              ${icon('i-building', 15)} ${escapeHtml(b.name)}
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
  // 教室设施故障（总闸、交换机等）：电脑没坏，但教室不能正常用
  const facilities = r.facility_count || 0;

  return `
    <div class="room-row" data-open-room="${escapeHtml(building)}" data-room="${escapeHtml(r.name)}">
      <span class="rname">${escapeHtml(r.name)}</span>
      <span class="rstat">
        <span>总数 <b>${total}</b></span>
        <span>正常 <b>${healthy}</b></span>
        <span class="rbroken">损坏 <b>${broken}</b></span>
        ${facilities ? `<span class="rfacility" title="总闸/交换机等教室设备故障，不计入电脑损坏台数">设施故障 ${facilities}</span>` : ''}
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
      refreshRailStats();
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
      refreshRailStats();
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
  refreshRailStats();
});

// ---------- 教室详情 ----------

/**
 * 「登记故障」弹窗
 *
 * 用表格一次填多条故障：每条 = 损坏原因 + 数量 + 状态。
 * 相比原来的 prompt() 逐条询问：
 *   · 能一次登记一批（如"第三排 5 台都开不了机"）
 *   · 损坏数量有独立字段，统计台数才准确
 *   · 可以选择状态（未报修 / 可自修）
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
      <td>
        <select class="ff-target" title="坏的是电脑，还是教室的设备？">
          <option value="电脑">电脑</option>
          <option value="教室设施">教室设施</option>
        </select>
      </td>
      <td class="ff-qty-cell">
        <input type="number" class="ff-qty" value="1" min="1" max="999">
      </td>
      <td>
        <select class="ff-status">
          <option value="未报修">未报修（硬件，需报修）</option>
          <option value="可自修">可自修（可自行修复）</option>
          <option value="已报修">已报修（已联系维修）</option>
          <option value="已解决">已解决</option>
        </select>
      </td>
      <td>
        <button class="ff-del" title="删除这一行">${icon('i-close', 14)}</button>
      </td>
    </tr>`;

  overlay.innerHTML = `
    <div class="modal" style="max-width:760px">
      <div class="modal-head">
        <h3>登记故障 · ${escapeHtml(building)} ${escapeHtml(roomName)}</h3>
        <button class="modal-close" id="ff-close" title="关闭">${icon('i-close', 16)}</button>
      </div>
      <div class="modal-body">
        <p class="ff-hint">
          每行一条故障原因。同一原因的多台机器填一行即可，不必逐台登记。<br>
          <b>故障对象</b>：坏的是电脑就选「电脑」（按台统计）；
          坏的是总闸、交换机、投影这类教室设备就选「教室设施」——
          后者会让整间教室不能用，但电脑本身没坏，不计入损坏台数。
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
          <option value="交换机故障"></option>
          <option value="教室空调故障"></option>
        </datalist>

        <table class="fault-form-table">
          <thead>
            <tr>
              <th style="width:36px">#</th>
              <th>损坏原因</th>
              <th style="width:110px">故障对象</th>
              <th style="width:80px">数量</th>
              <th style="width:180px">状态</th>
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

  /** 汇总提示：共几行、合计几台（设施故障不计台数） */
  function updateSummary() {
    const rows = body.querySelectorAll('.ff-row');
    let total = 0;
    let filled = 0;
    let facilities = 0;
    rows.forEach(tr => {
      const reason = tr.querySelector('.ff-reason').value.trim();
      const qty = parseInt(tr.querySelector('.ff-qty').value, 10) || 0;
      const target = tr.querySelector('.ff-target').value;
      if (!reason) return;
      filled += 1;
      if (target === '教室设施') {
        facilities += 1;
      } else {
        total += Math.max(qty, 0);
      }
    });

    const parts = [];
    if (filled) parts.push(`共 <b>${filled}</b> 条故障`);
    if (total) parts.push(`电脑损坏 <b>${total}</b> 台`);
    if (facilities) parts.push(`教室设施 <b>${facilities}</b> 项`);
    summaryEl.innerHTML = parts.join('，');
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
    tr.querySelector('.ff-target').addEventListener('change', (e) => {
      // 设施故障不是按台算的，数量输入框置灰
      const isFacility = e.target.value === '教室设施';
      const qty = tr.querySelector('.ff-qty');
      qty.disabled = isFacility;
      qty.title = isFacility ? '教室设施故障不按台计' : '';
      updateSummary();
    });
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
        target: tr.querySelector('.ff-target').value,
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
  $('#room-detail').innerHTML =
    skeletonCards(1, 90) + '<div style="height:14px"></div>' + skeletonLines(4);

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

  // 设备分两类，四张卡片按「总数 → 正常 → 损坏」的层级展示
  //
  //   电脑总数
  //   ├─ 正常        （已解决 = 修好了）
  //   └─ 损坏        ← 红色，表示"这台是坏的"，与报没报修无关
  //        ├─ 未报修    （还没安排）
  //        ├─ 可自修    （自己能修）
  //        └─ 已报修    （已送修）
  //
  // 关键：「损坏」= 未报修 + 可自修 + 已报修，
  //       所以 正常 + 损坏 = 电脑总数，账目能直接对上。
  //       之前这里叫「需报修」，但已报修的那几台并不需要再报修，
  //       名称与实际含义不符。
  const broken = c.unresolved || 0;         // 损坏合计（红色）
  const healthy = Math.max(total - broken, 0);
  const selfFix = c.self_fix || 0;          // 其中"可自修"的台数（黄色）

  // 状态类名统一由全局 statusClass() 提供，避免两处定义不一致

  // 故障明细（含已解决的，方便编辑）
  const causeHtml = d.records.length
    ? d.records.map(r => {
        const st = r['状态'] || '未报修';
        const cls = statusClass(st);
        const done = st === '已解决';     // 已完成的不再提供"标记"按钮
        const qty = parseInt(r['数量'], 10) || 1;
        return `
        <div class="cause-item ${cls}">
          <div class="cause-top">
            <span class="cause-qty">${qty} 台</span>
            <span class="badge ${cls}">${escapeHtml(st)}</span>
            <span class="cause-time">${escapeHtml(r['时间'])}</span>
          </div>
          <div class="cause-text">
            <b style="color:var(--text-dim)">现象：</b>${escapeHtml(r['故障现象'])}<br>
            <b style="color:var(--text-dim)">结论：</b>${escapeHtml(r['诊断结论'] || '—').replace(/\n/g, '<br>')}
            ${r['备注'] ? `<br><b style="color:var(--text-dim)">备注：</b>${escapeHtml(r['备注'])}` : ''}
          </div>
          <div class="cause-actions">
            ${done
              ? `<button data-set-status="${escapeHtml(r['记录编号'])}" data-to="未报修">恢复未报修</button>`
              : `<button data-set-status="${escapeHtml(r['记录编号'])}" data-to="可自修">${icon('i-wrench', 13)} 改为可自修</button>
                 <button data-set-status="${escapeHtml(r['记录编号'])}" data-to="已报修">标记已报修</button>
                 <button data-set-status="${escapeHtml(r['记录编号'])}" data-to="已解决">${icon('i-check', 13)} 标记已解决</button>`}
            <button data-edit-record="${escapeHtml(r['记录编号'])}">编辑</button>
            <button class="del-btn" data-del-record="${escapeHtml(r['记录编号'])}">删除</button>
          </div>
        </div>`;
      }).join('')
    : '<div class="cause-empty">该教室当前没有故障记录</div>';

  // 教室设施故障提示（总闸、交换机等）
  //
  // 这类故障会让整间教室不能用，但电脑本身没坏 ——
  // 所以它不出现在上面的"损坏台数"里，必须单独提示，
  // 否则管理员会以为电脑都好好的，实际教室根本没法上课。
  const facilityList = (d.facility_issues || []).filter(
    r => r['状态'] !== '已解决');
  const facilityHtml = facilityList.length
    ? `<div class="facility-notice">
         <div class="fn-head">
           ${icon('i-alert', 14)}
           教室设施故障 ${facilityList.length} 项 —— 电脑本身未损坏，但整间教室受影响
         </div>
         <ul class="fn-list">
           ${facilityList.map(r => `
             <li>
               <b>${escapeHtml(r['故障现象'] || '设施故障')}</b>
               <span class="fn-time">${escapeHtml(r['时间'] || '')}</span>
               <span class="fn-status">${escapeHtml(r['状态'] || '')}</span>
             </li>`).join('')}
         </ul>
       </div>`
    : '';

  $('#room-detail').innerHTML = `
    <h4>${escapeHtml(building)} · ${escapeHtml(roomName)}</h4>
    <div class="sub-line">设备状态由报修台账自动统计，无需手工填写损坏数</div>

    <div class="detail-stats detail-stats-4">
      <div class="detail-stat tot">
        <div class="dv">${total}</div>
        <div class="dl">${icon('i-monitor', 13)} 电脑总数</div>
      </div>
      <div class="detail-stat ok">
        <div class="dv">${healthy}</div>
        <div class="dl">${icon('i-check', 13)} 正常</div>
      </div>
      <div class="detail-stat selffix">
        <div class="dv">${selfFix}</div>
        <div class="dl">${icon('i-wrench', 13)} 可自修</div>
      </div>
      <div class="detail-stat bad">
        <div class="dv">${broken}</div>
        <div class="dl">${icon('i-alert', 13)} 损坏</div>
      </div>
    </div>

    ${facilityHtml}

    <div id="room-chart"></div>

    <div class="cause-section">
      <div class="cause-head">
        <h5>损坏与故障明细</h5>
        <button class="btn-primary btn-sm" id="add-record">＋ 登记故障</button>
      </div>
      <div class="cause-summary">
        <span>未报修 <b>${c.pending}</b></span>
        <span class="sm-selffix">可自修 <b>${c.self_fix}</b></span>
        <span>已报修 <b>${c.reported}</b></span>
        <span>已解决 <b>${c.resolved}</b></span>
        <span style="margin-left:auto;color:var(--text-faint)">
          损坏合计 <b>${broken}</b> 台
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

  // 环形图：正常 / 可自修 / 损坏 三段（加起来等于电脑总数）
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
        { value: selfFix, name: '可自修', itemStyle: { color: '#eab308' } },
        // 剩下的是"坏了且需要送修"的部分（未报修 + 已报修）
        {
          value: Math.max(broken - selfFix, 0),
          name: '损坏',
          itemStyle: { color: '#ef4444' },
        },
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
      // 重新加载本页 + 刷新侧边栏与教室列表
      openRoomDetail(building, roomName);
      refreshRailStats();
      loadClassrooms();
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
      refreshRailStats();
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
      refreshRailStats();
      loadClassrooms();
    });
  });

  // 登记故障（弹窗表格：原因 + 数量，可一次填多行）
  $('#add-record').addEventListener('click', () => {
    openFaultForm(building, roomName, () => {
      openRoomDetail(building, roomName);
      refreshRailStats();
      // 教室列表也要刷新：损坏台数变了，列表上的数字必须同步
      loadClassrooms();
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
    refreshRailStats();
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
    refreshRailStats();
  });
}

/* ============================================================
   诊断页：教室选择条
   ============================================================ */
let pickedBuilding = '';
let pickedRoom = '';

async function loadRoomPicker() {
  const bSel = $('#pick-building');
  const rSel = $('#pick-room');
  if (!bSel) return;

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
      pickedBuilding = '';
      rSel.innerHTML = '<option value="">请先选教学楼</option>';
      rSel.disabled = true;
      return;
    }

    // 之前选的教学楼可能已经被改名或删掉了 —— 这时候不能直接用它去查教室，
    // 否则会一直显示"该楼暂无教室"，看起来像选不了东西
    const stillThere = pickedBuilding &&
      d.buildings.some(b => b.name === pickedBuilding);
    if (pickedBuilding && !stillThere) {
      pickedBuilding = '';
      pickedRoom = '';
    }

    if (stillThere) {
      bSel.value = pickedBuilding;
      fillRooms(d, pickedBuilding);
    } else {
      bSel.value = '';
      rSel.innerHTML = '<option value="">请先选教学楼</option>';
      rSel.disabled = true;
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
    // 打开时重新拉一次教学楼 —— 教室结构可能刚被改过，
    // 只在页面加载时拉一次的话，下拉里会留着已经不存在的旧名字，
    // 选完查不到教室，看起来就是"选不了东西"
    refreshTaskOptions();
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
  list.innerHTML = skeletonCards(3, 76);

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
        ${icon('i-note', 40).replace('class="icon"', 'class="icon empty-icon"')}
        <p>${taskFilter ? '没有「' + escapeHtml(taskFilter) + '」的报备' : '还没有报备记录'}</p>
        <span class="empty-hint">${
          taskFilter ? '换个筛选条件看看' : '点上方「添加报备」记录老师的日常需求'
        }</span>
      </div>`;
      return;
    }

    const today = new Date().toISOString().slice(0, 10);

    // 分页：一页 10 条
    const pg = paginate('tasks', d.tasks);

    list.innerHTML = pg.slice.map(t => {
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
            ${t.due ? `<span class="kv">预计 <b class="ti-due">${escapeHtml(t.due)}</b>${
              isOverdue ? ` <span class="overdue-tag">${icon('i-alert', 12)} 已逾期</span>` : ''
            }</span>` : ''}
            ${t.detail ? `<div style="margin-top:5px">${escapeHtml(t.detail)}</div>` : ''}
            <div style="margin-top:5px;font-size:12px;color:var(--text-faint)">
              提交于 ${escapeHtml(t.created)}${isDone && t.finished ? ' · 完成于 ' + escapeHtml(t.finished) : ''}
            </div>
          </div>
          <div class="ti-actions">
            <button class="${isDone ? '' : 'done-btn'}" data-toggle="${escapeHtml(t.id)}">
              ${isDone ? '标记待完成' : `${icon('i-check', 13)} 标记已完成`}
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

    // 分页条
    if (pg.pages > 1) {
      const box = document.createElement('div');
      box.innerHTML = pagerHtml('tasks', pg.page, pg.pages, pg.total);
      list.appendChild(box.firstElementChild);
      bindPager(list, 'tasks', () => loadTasks());
    }

  } catch (err) {
    list.innerHTML = `<div class="empty">加载失败：${escapeHtml(err.message)}</div>`;
  }
}

// 初始化报备表单的选项
async function initTaskForm() {
  await refreshTaskOptions();
}

/**
 * 重新拉取报备表单的下拉选项
 *
 * 为什么单独抽出来：教学楼和教室随时可能被改动（改名、增删），
 * 而下拉框是"一次性填好"的 —— 页面开着不动，数据改了，
 * 下拉里还是旧名字，选完查不到教室，用户看到的就是"选不了东西"。
 * 所以每次打开表单都重拉一遍。
 */
async function refreshTaskOptions() {
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

    const prev = $('#tf-building').value;
    $('#tf-building').innerHTML = '<option value="">请选择</option>' +
      cd.buildings.map(b =>
        `<option value="${escapeHtml(b.name)}">${escapeHtml(b.name)}</option>`
      ).join('');

    const stillThere = prev && cd.buildings.some(b => b.name === prev);
    if (stillThere) {
      $('#tf-building').value = prev;
      $('#tf-building').dispatchEvent(new Event('change'));
    } else {
      // 之前选的教学楼已经不在了，把教室框也重置，
      // 免得留一个禁用的空下拉让人以为坏了
      $('#tf-building').value = '';
      $('#tf-room').innerHTML = '<option value="">请先选教学楼</option>';
      $('#tf-room').disabled = true;
    }
  } catch { /* 忽略 */ }
}

/* ============================================================
   课表与调课

   这一页的核心问题：**教室坏了，这节课能挪到哪？**

   设计上的关键改变：不再"选条件 → 点查询"。
   打开就摊开一整天的课表（教室 × 节次），空格子就是空闲。
   点一门课 → 直接给能挪过去的教室；
   点一个空格 → 看这一节还有哪些教室空着。

   为什么不用查询条：
   日常调课要一眼看到全天的排布，逼用户先选教学楼/教室/星期/节次
   再点一次查询，等于把找东西的活儿又推回给他。
   ============================================================ */

const SCHED_DAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
const SCHED_PERIODS = 12;

// 作息设置里把 12 节分成三段展示，和 schedule.PERIOD_SECTIONS 保持一致
const PERIOD_SECTIONS = [
  { name: '上午', periods: [1, 2, 3, 4] },
  { name: '下午', periods: [5, 6, 7, 8] },
  { name: '晚上', periods: [9, 10, 11, 12] },
];

// 当前查看的日期与周次
let schedDay = 0;          // 0 表示还没初始化
let schedWeek = 0;
let schedMatrix = null;    // 最近一次拉到的整张表
let schedInited = false;
let schedPeriods = {};     // 作息时间（用于算连排/连空）
let schedPicked = false;   // 用户是否手动选过日期
let schedAutoJumped = false;  // 是否因为"今天没课"被自动跳过
let schedTerm = {};

/** 教室号 → 楼层（去掉字母后第一位数字：C104 → 1，402 → 4） */
function schedFloor(room) {
  const m = String(room || '').match(/\d+/);
  return m ? parseInt(m[0][0], 10) : null;
}

/** 某间教室某一节的课（同格可能有多门不同周次的课，接口已按周次筛过） */
function schedCourseAt(building, room, period) {
  const list = (schedMatrix && schedMatrix.courses) || [];
  const hit = list.filter(c =>
    c.building === building && c.room === room &&
    c.p <= period && period <= c.p_end);
  return hit.length ? hit[0] : null;
}

/** 这节课实际连排几节（同一门课、同一老师连续排） */
function schedSpan(building, room, period) {
  const c0 = schedCourseAt(building, room, period);
  if (!c0) return 0;
  let n = 1;
  for (let p = period + 1; p <= SCHED_PERIODS; p++) {
    const c = schedCourseAt(building, room, p);
    if (!c || c.name !== c0.name || c.teacher !== c0.teacher) break;
    n++;
  }
  return n;
}

/** 从 period 起连续空闲几节 */
function schedFreeRun(building, room, period) {
  let n = 0;
  for (let p = period; p <= SCHED_PERIODS; p++) {
    if (schedCourseAt(building, room, p)) break;
    n++;
  }
  return n;
}

/** 这段区间是否全空 */
function schedFreeSpan(building, room, p0, span) {
  for (let p = p0; p < p0 + span; p++) {
    if (schedCourseAt(building, room, p)) return false;
  }
  return true;
}

/** 进入课表页 */
async function loadSchedulePage() {
  initScheduleControls();

  // 首次进入：定位到「现在」
  if (!schedDay) {
    schedDay = _nowWeekday();
    schedWeek = 0;
  }

  await fetchMatrix();

  // 今天没课（周末、假期）时自动跳到下一个有课的日子。
  // 打开看到一张全空的表没有意义，直接给最近的上课日更有用。
  if (schedMatrix && (schedMatrix.courses || []).length === 0 && !schedPicked) {
    for (let k = 1; k <= 7; k++) {
      const d = ((schedDay - 1 + k) % 7) + 1;
      const data = await getMatrix(d, schedWeek);
      if (data && (data.courses || []).length) {
        schedDay = d;
        schedAutoJumped = true;
        applyMatrix(data);
        break;
      }
    }
  }
}

/** 只取数据，不动界面 */
async function getMatrix(day, week) {
  try {
    const params = new URLSearchParams({ day });
    if (week) params.set('week', week);
    const res = await fetch('/api/schedule/matrix?' + params);
    const d = await res.json();
    return d.error ? null : d;
  } catch {
    return null;
  }
}

/** 把数据装进状态并渲染 */
function applyMatrix(d) {
  schedMatrix = d;
  schedWeek = d.week;
  schedPeriods = d.periods || {};
  schedTerm = d.term || {};

  const hasAny = (d.rooms || []).length > 0;
  $('#sched-empty').classList.toggle('hidden', hasAny);
  $('#sched-main').classList.toggle('hidden', !hasAny);
  if (!hasAny) return;

  renderSchedTermLine();
  renderSchedDayBar();
  renderSchedTable();

  $('#sched-detail').innerHTML = '';
}

function _nowWeekday() {
  const d = new Date().getDay();
  return d === 0 ? 7 : d;
}

async function fetchMatrix() {
  const emptyEl = $('#sched-empty');
  const main = $('#sched-main');

  const d = await getMatrix(schedDay, schedWeek);

  if (!d) {
    if (main) main.classList.add('hidden');
    emptyEl.classList.remove('hidden');
    const p = emptyEl.querySelector('p');
    if (p) p.textContent = '读取失败，请刷新重试';
    return;
  }

  applyMatrix(d);
}

function initScheduleControls() {
  if (schedInited) return;
  schedInited = true;

  initImportModal();
  initPeriodModal();
  initRoomModal();

  const imp = $('#sched-import-btn');
  if (imp) imp.addEventListener('click', openImportModal);
  const per = $('#sched-period-btn');
  if (per) per.addEventListener('click', openPeriodModal);
}

function renderSchedTermLine() {
  const el = $('#sched-term-line');
  if (!el) return;

  const t = schedTerm || {};
  const rooms = (schedMatrix.rooms || []).length;

  if (!t.start) {
    el.textContent = '还没配置学期 —— 去「作息设置」补上';
    return;
  }

  const now = schedMatrix.now || {};
  el.textContent = `${t.start} 起 ${t.weeks || 0} 周 · 第 ${schedWeek} 周`
    + ` · 已导入 ${rooms} 间`
    + (now.week ? ` · 本周是第 ${now.week} 周` : '');
}

function renderSchedDayBar() {
  const bar = $('#sched-daybar');
  if (!bar) return;

  const now = (schedMatrix && schedMatrix.now) || {};
  const today = now.day;

  const chips = SCHED_DAYS.map((name, i) => {
    const day = i + 1;
    const isToday = day === today;
    const active = day === schedDay;
    return `
      <button class="sday${active ? ' active' : ''}" data-sday="${day}">
        ${name}${isToday ? '<span class="sday-tag">今天</span>' : ''}
      </button>`;
  }).join('');

  const weeks = Math.max(parseInt((schedTerm || {}).weeks, 10) || 20, 1);
  const opts = Array.from({ length: weeks }, (_, i) => {
    const w = i + 1;
    return `<option value="${w}"${w === schedWeek ? ' selected' : ''}>第 ${w} 周</option>`;
  }).join('');

  const jumpNote = schedAutoJumped
    ? `<span class="sjump">今天没课，已跳到 ${SCHED_DAYS[schedDay - 1]}</span>`
    : '';

  bar.innerHTML = chips + jumpNote + `
    <span class="sweek">周次 <select id="sched-week">${opts}</select></span>`;

  bar.querySelectorAll('[data-sday]').forEach(btn => {
    btn.addEventListener('click', () => {
      schedDay = parseInt(btn.dataset.sday, 10);
      schedPicked = true;
      schedAutoJumped = false;
      fetchMatrix();
    });
  });

  const sel = $('#sched-week');
  if (sel) {
    sel.addEventListener('change', () => {
      schedWeek = parseInt(sel.value, 10) || schedWeek;
      fetchMatrix();
    });
  }
}

function renderSchedTable() {
  const thead = $('#sched-thead');
  const tbody = $('#sched-tbody');
  if (!thead || !tbody) return;

  const now = (schedMatrix && schedMatrix.now) || {};
  const isToday = schedDay === now.day;

  // 表头：第 N 节 + 时间
  thead.innerHTML = '<th></th>' + Array.from({ length: SCHED_PERIODS }, (_, i) => {
    const p = i + 1;
    const t = schedPeriods[String(p)] || {};
    const cls = (isToday && p === now.period) ? ' class="now"' : '';
    return `<th${cls}><span class="pno">第 ${p} 节</span>${escapeHtml(t.start || '')}</th>`;
  }).join('');

  // 按教学楼分组
  const byBuilding = new Map();
  (schedMatrix.rooms || []).forEach(r => {
    if (!byBuilding.has(r.building)) byBuilding.set(r.building, []);
    byBuilding.get(r.building).push(r);
  });

  // 有「影响上课」级故障的教室 —— 接口已按 整间跳闸 / 整间断网 / 教师机 判好。
  // 这些教室整行染红：本来就不能用，空着也不该被当成调课候选。
  const faultSet = new Set(
    (schedMatrix.rooms || [])
      .filter(r => r.fault)
      .map(r => r.building + '|' + r.name)
  );

  let html = '';
  for (const [building, list] of byBuilding) {
    html += `<tr class="shead"><td colspan="${SCHED_PERIODS + 1}">${escapeHtml(building)}</td></tr>`;

    for (const r of list) {
      const key = building + '|' + r.name;
      const fault = faultSet.has(key);

      html += `<tr class="${fault ? 'sfault' : ''}">`;
      html += `<th class="sroom">${escapeHtml(r.name)}`
            + `<span class="sr-seats"> ${r.total}座</span></th>`;

      // 先把每一节有没有课算出来，再把连续的同一门课合并成格
      const slots = [];
      for (let p = 1; p <= SCHED_PERIODS; p++) {
        slots.push(schedCourseAt(building, r.name, p));
      }

      let i = 0;
      while (i < SCHED_PERIODS) {
        const cur = slots[i];
        let span = 1;
        while (i + span < SCHED_PERIODS && cur && slots[i + span] &&
               slots[i + span].name === cur.name &&
               slots[i + span].teacher === cur.teacher) {
          span++;
        }
        const p = i + 1;

        if (cur) {
          html += `<td class="scell busy" colspan="${span}"
                       data-building="${escapeHtml(building)}"
                       data-room="${escapeHtml(r.name)}"
                       data-p="${p}" data-busy="1">
                     <div class="scn">${escapeHtml(cur.name)}</div>
                     <div class="scm">${cur.students}人</div>
                   </td>`;
        } else {
          html += `<td class="scell free" colspan="${span}" data-p="${p}"></td>`;
        }
        i += span;
      }
      html += '</tr>';
    }
  }
  tbody.innerHTML = html;

  // 点表头 → 看这一节的空闲教室
  thead.querySelectorAll('th').forEach((th, idx) => {
    if (!idx) return;
    th.style.cursor = 'pointer';
    th.addEventListener('click', () => showSchedPeriod(idx));
  });

  // 点格子 → 有课给调课建议，空闲看该节全貌
  tbody.querySelectorAll('.scell').forEach(td => {
    td.addEventListener('click', () => {
      if (td.dataset.busy) {
        showSchedMove(td.dataset.building, td.dataset.room,
                      parseInt(td.dataset.p, 10));
      } else {
        showSchedPeriod(parseInt(td.dataset.p, 10));
      }
    });
  });
}

/* -------- 调课建议 -------- */

function showSchedMove(building, room, period) {
  const c = schedCourseAt(building, room, period);
  if (!c) return;

  const source = (schedMatrix.rooms || []).find(
    r => r.building === building && r.name === room) || {};
  const span = schedSpan(building, room, period) || 1;

  renderSchedMove(building, room, period, c, span, source.total || 0);
}

function renderSchedMove(building, room, period, course, span, total) {
  const box = $('#sched-detail');
  if (!box) return;

  const floor = schedFloor(room);

  const rows = [];
  const reasons = { seats: 0, busy: 0, fault: 0, other: 0 };

  (schedMatrix.rooms || []).forEach(r => {
    if (r.building === building && r.name === room) return;   // 跳过自己

    if (r.total < course.students) { reasons.seats++; return; }
    if (!schedFreeSpan(r.building, r.name, period, span)) { reasons.busy++; return; }

    const rf = schedFloor(r.name);
    let where, tier;
    if (r.building !== building) { where = '另一栋楼'; tier = 2; }
    else if (rf === floor) { where = '同层'; tier = 0; }
    else if (rf !== null && floor !== null) {
      where = rf > floor ? '楼上' : '楼下'; tier = 1;
    } else { where = '同楼'; tier = 1; }

    rows.push({
      name: r.name, seats: r.total,
      run: schedFreeRun(r.building, r.name, period),
      where, tier,
    });
  });

  // 同层优先 → 座位最接近 → 连续空闲最多
  rows.sort((a, b) => a.tier - b.tier
    || (a.seats - course.students) - (b.seats - course.students)
    || b.run - a.run);

  const list = rows.length
    ? `<div class="scand">${rows.slice(0, 8).map((r, i) => `
        <div class="sc${i === 0 ? ' best' : ''}">
          <span class="crank">${i === 0 ? '★' : ''}</span>
          <span class="cname">${escapeHtml(r.name)}</span>
          <span class="cseats"><b>${r.seats}</b> 座</span>
          <span class="cfree">第 ${period}–${period + span - 1} 节全空 · 连空 ${r.run} 节</span>
          <span class="cwhere">${r.where}</span>
        </div>`).join('')}</div>`
    : '<div class="sched-none">没有符合条件的教室</div>';

  const ex = [];
  if (reasons.seats) ex.push(`${reasons.seats} 间座位不足 ${course.students} 人`);
  if (reasons.busy) ex.push(`${reasons.busy} 间目标时段有课`);

  const t0 = schedPeriods[String(period)] || {};
  const t1 = schedPeriods[String(period + span - 1)] || {};

  box.innerHTML = `
    <div class="sdetail">
      <div class="sdetail-head">
        调课建议
        <span class="sdetail-sub">${SCHED_DAYS[schedDay - 1]}</span>
        <button class="sdetail-close" id="sched-detail-close">✕</button>
      </div>

      <div class="starget">
        <div class="tname">${escapeHtml(course.name)}</div>
        <div class="tmeta">
          ${escapeHtml(building)}-${escapeHtml(room)} ·
          第 ${period}–${period + span - 1} 节 · ${escapeHtml(course.teacher)} ·
          ${course.students} 人
        </div>
      </div>

      <div class="sask">
        挪到哪一节
        <select class="psel" id="sched-move-period">
          ${Array.from({ length: SCHED_PERIODS }, (_, i) => {
            const p = i + 1;
            const t = schedPeriods[String(p)] || {};
            return `<option value="${p}"${p === period ? ' selected' : ''}>
              第 ${p} 节 ${escapeHtml(t.start || '')}–${escapeHtml(t.end || '')}</option>`;
          }).join('')}
        </select>
        <span class="sask-note">需要 ${span} 节连排 · 座位 ≥ ${course.students}</span>
      </div>

      <div class="ssec">可以挪到（${escapeHtml(t0.start || '')}–${escapeHtml(t1.end || '')}）</div>
      ${list}

      ${ex.length ? `<div class="sexcluded">已排除：<b>${ex.join(' · ')}</b></div>` : ''}
    </div>`;

  const close = $('#sched-detail-close');
  if (close) close.addEventListener('click', () => { box.innerHTML = ''; });

  const sel = $('#sched-move-period');
  if (sel) {
    sel.addEventListener('change', () => {
      const p = parseInt(sel.value, 10);
      // 换目标节次后，源课程还是同一门，连排长度不变
      renderSchedMove(building, room, p, course, span, total);
    });
  }
}

/* -------- 单节全貌（点空格子） -------- */

function showSchedPeriod(p) {
  const box = $('#sched-detail');
  if (!box) return;

  const all = (schedMatrix.rooms || []);
  const busy = (schedMatrix.courses || []).filter(
    c => c.p <= p && p <= c.p_end);

  const busyKeys = new Set(busy.map(c => c.building + '|' + c.room));

  const free = all.filter(r => !busyKeys.has(r.building + '|' + r.name));
  free.sort((a, b) => a.total - b.total);

  const t = schedPeriods[String(p)] || {};

  box.innerHTML = `
    <div class="sdetail">
      <div class="sdetail-head">
        第 ${p} 节 ${escapeHtml(t.start || '')}–${escapeHtml(t.end || '')}
        <span class="sdetail-sub">
          ${SCHED_DAYS[schedDay - 1]} · 空闲 ${free.length} 间 / 上课 ${busyKeys.size} 间
        </span>
        <button class="sdetail-close" id="sched-detail-close">✕</button>
      </div>

      <div class="ssec">空闲教室（按座位数升序）</div>
      ${free.length ? `<div class="sfreegrid">${free.map(r => `
        <div class="sfree">
          <div class="fn">${escapeHtml(r.name)}</div>
          <div class="fs">${r.total}<span class="fu"> 座</span></div>
          <div class="fu">${escapeHtml(r.building)}</div>
        </div>`).join('')}</div>`
        : '<div class="sched-none">本时段没有空闲教室</div>'}

      <div class="ssec">正在上课</div>
      ${busy.length ? `<div class="sbusylist">${busy.map(c => `
        <div class="sbrow">
          <span class="broom">${escapeHtml(c.room)}</span>
          <span class="bcourse">${escapeHtml(c.name)}</span>
          <span class="bmeta">${escapeHtml(c.teacher)} · ${c.students} 人</span>
        </div>`).join('')}</div>`
        : '<div class="sched-none">本时段没有课</div>'}
    </div>`;

  const close = $('#sched-detail-close');
  if (close) close.addEventListener('click', () => { box.innerHTML = ''; });
}

/* -------- 导入课表 -------- */

let parsedFiles = [];      // 最近一次解析结果
let classroomsFlat = [];   // 系统里的教室列表

function initImportModal() {
  const modal = $('#sched-import-modal');
  const input = $('#sched-files');
  const drop = $('#sched-drop');

  if (!modal) return;

  $('#sched-import-close').addEventListener('click', closeImportModal);
  $('#sched-import-cancel').addEventListener('click', closeImportModal);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeImportModal();
  });

  drop.addEventListener('click', () => input.click());

  // 拖拽
  drop.addEventListener('dragover', (e) => {
    e.preventDefault();
    drop.classList.add('drag');
  });
  drop.addEventListener('dragleave', () => drop.classList.remove('drag'));
  drop.addEventListener('drop', (e) => {
    e.preventDefault();
    drop.classList.remove('drag');
    if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
  });

  input.addEventListener('change', () => {
    if (input.files.length) handleFiles(input.files);
    input.value = '';   // 允许重复选同一个文件
  });

  $('#sched-import-apply').addEventListener('click', applyImport);
}

function openImportModal() {
  parsedFiles = [];
  $('#sched-parse-result').classList.add('hidden');
  $('#sched-parse-result').innerHTML = '';
  $('#sched-term-note').classList.add('hidden');
  $('#sched-import-apply').disabled = true;
  $('#sched-import-apply').textContent = '导入';
  $('#sched-import-modal').classList.remove('hidden');
}

function closeImportModal() {
  $('#sched-import-modal').classList.add('hidden');
}

/** 上传并解析（不落盘） */
async function handleFiles(fileList) {
  const box = $('#sched-parse-result');
  const applyBtn = $('#sched-import-apply');

  box.classList.remove('hidden');
  box.innerHTML = '<div class="sched-parse-loading">解析中…</div>';
  applyBtn.disabled = true;

  const fd = new FormData();
  [...fileList].forEach(f => fd.append('files', f));

  let d;
  try {
    const res = await fetch('/api/schedule/parse', { method: 'POST', body: fd });
    d = await res.json();
    if (!d.ok) throw new Error(d.message || '解析失败');
  } catch (err) {
    box.innerHTML = `<div class="sched-parse-loading">解析失败：${escapeHtml(err.message)}</div>`;
    return;
  }

  parsedFiles = d.files || [];

  // 教室清单（用于映射下拉）
  try {
    const res = await fetch('/api/classrooms');
    const cd = await res.json();
    classroomsFlat = (cd.flat || []);
  } catch {
    classroomsFlat = [];
  }

  renderParseResult();

  if (d.term) {
    const note = $('#sched-term-note');
    note.classList.remove('hidden');
    note.innerHTML =
      `识别到学期：<b>${escapeHtml(d.term.start || '')}</b> 起，`
      + `共 <b>${d.term.weeks || 0}</b> 周`
      + `<span class="tn-hint">（导入后可在「作息设置」里调整）</span>`;
  }
}

/** 渲染解析结果，每行带一个教室映射下拉 */
function renderParseResult() {
  const box = $('#sched-parse-result');
  const applyBtn = $('#sched-import-apply');

  const buildings = [...new Set(classroomsFlat.map(r => r.building))];

  const rows = parsedFiles.map((f, i) => {
    if (!f.ok) {
      return `
        <div class="parse-row parse-bad">
          <div class="pr-file">${escapeHtml(f.filename)}</div>
          <div class="pr-error">✗ ${escapeHtml(f.error || '解析失败')}</div>
        </div>`;
    }

    const guess = f.guess || {};
    const buildingOpts = buildings.map(b =>
      `<option value="${escapeHtml(b)}"${b === guess.building ? ' selected' : ''}>`
      + `${escapeHtml(b)}</option>`).join('');

    return `
      <div class="parse-row" data-idx="${i}">
        <div class="pr-file">${escapeHtml(f.filename)}</div>
        <div class="pr-room">
          课表教室 <b>${escapeHtml(f.room_label || '（未识别）')}</b>
          <span class="pr-meta">
            座位 ${f.seats || '未知'} · ${f.course_count} 条课程
          </span>
        </div>
        <div class="pr-map">
          <span class="pr-map-label">对应系统教室</span>
          <select class="pr-building">
            <option value="">请选择</option>${buildingOpts}
          </select>
          <select class="pr-room-name"></select>
        </div>
      </div>`;
  }).join('');

  box.innerHTML = rows;

  // 教学楼 → 教室 联动
  box.querySelectorAll('.parse-row[data-idx]').forEach(row => {
    const f = parsedFiles[parseInt(row.dataset.idx, 10)];
    const bSel = row.querySelector('.pr-building');
    const rSel = row.querySelector('.pr-room-name');
    const guess = (f && f.guess) || {};

    const fillRooms = () => {
      const b = bSel.value;
      const rooms = classroomsFlat.filter(x => x.building === b);
      rSel.innerHTML = '<option value="">请选择</option>' + rooms.map(x =>
        `<option value="${escapeHtml(x.name)}"`
        + `${(b === guess.building && x.name === guess.room) ? ' selected' : ''}>`
        + `${escapeHtml(x.name)}（${x.total || 0} 台）</option>`).join('');
      if (b === guess.building && guess.room) rSel.value = guess.room;
      updateApplyState();
    };

    bSel.addEventListener('change', fillRooms);
    rSel.addEventListener('change', updateApplyState);
    fillRooms();
  });

  updateApplyState();
}

/** 所有解析成功的行都选好映射，才能点导入 */
function updateApplyState() {
  const box = $('#sched-parse-result');
  const btn = $('#sched-import-apply');

  const rows = [...box.querySelectorAll('.parse-row[data-idx]')];
  const okCount = parsedFiles.filter(f => f.ok).length;

  const allMapped = rows.length > 0 && rows.every(row => {
    const b = row.querySelector('.pr-building');
    const r = row.querySelector('.pr-room-name');
    return b && b.value && r && r.value;
  });

  btn.disabled = !allMapped;
  btn.textContent = allMapped
    ? `导入 ${okCount} 个`
    : '请先选好对应教室';
}

/** 确认后落盘 */
async function applyImport() {
  const box = $('#sched-parse-result');
  const btn = $('#sched-import-apply');

  const items = [];
  box.querySelectorAll('.parse-row[data-idx]').forEach(row => {
    const f = parsedFiles[parseInt(row.dataset.idx, 10)];
    if (!f || !f.ok) return;
    items.push({
      filename: f.filename,
      building: row.querySelector('.pr-building').value,
      room: row.querySelector('.pr-room-name').value,
    });
  });

  if (!items.length) return;

  btn.disabled = true;
  btn.textContent = '导入中…';

  let d;
  try {
    const res = await fetch('/api/schedule/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    });
    d = await res.json();
  } catch (err) {
    alert('导入失败：' + err.message);
    btn.disabled = false;
    btn.textContent = '重试';
    return;
  }

  if (d.failed && d.failed.length) {
    alert('部分导入失败：\n' + d.failed.map(x =>
      `${x.filename}：${x.error}`).join('\n'));
  }

  if (d.done && d.done.length) {
    closeImportModal();
    loadSchedulePage();
  } else {
    btn.disabled = false;
    btn.textContent = '导入';
  }
}

/* -------- 作息设置 -------- */

function initPeriodModal() {
  const modal = $('#sched-period-modal');
  if (!modal) return;

  $('#sched-period-close').addEventListener('click', closePeriodModal);
  $('#sched-period-cancel').addEventListener('click', closePeriodModal);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) closePeriodModal();
  });

  $('#sched-generate').addEventListener('click', generatePeriods);
  $('#sched-period-save').addEventListener('click', savePeriods);
}

async function openPeriodModal() {
  try {
    const res = await fetch('/api/schedule/periods');
    const d = await res.json();
    schedPeriods = d.periods || {};
    schedTerm = d.term || {};
  } catch { /* 用空值 */ }

  $('#sched-term-start').value = schedTerm.start || '';
  $('#sched-term-weeks').value = schedTerm.weeks || 20;

  renderPeriodInputs(schedPeriods);
  $('#sched-period-modal').classList.remove('hidden');
}

function closePeriodModal() {
  $('#sched-period-modal').classList.add('hidden');
}

/** 把 periods 对象渲染成 12 行时间输入 */
function renderPeriodInputs(periods) {
  const box = $('#sched-period-list');

  box.innerHTML = PERIOD_SECTIONS.map(sec => `
    <div class="pl-section">
      <div class="pl-section-head">${sec.name}</div>
      ${sec.periods.map(p => {
        const t = periods[String(p)] || {};
        return `
          <div class="pl-row" data-period="${p}">
            <span class="pl-idx">第 ${p} 节</span>
            <input type="time" class="pl-start" value="${escapeHtml(t.start || '')}">
            <span class="pl-dash">–</span>
            <input type="time" class="pl-end" value="${escapeHtml(t.end || '')}">
          </div>`;
      }).join('')}
    </div>`).join('');
}

/** 按 3 个锚点 + 时长 + 课间，生成 12 节时间 */
function generatePeriods() {
  const duration = parseInt($('#sched-duration').value, 10) || 45;
  const gap = parseInt($('#sched-break').value, 10) || 0;

  const anchors = {
    1: $('#sched-anchor-am').value || '08:00',
    5: $('#sched-anchor-pm').value || '14:00',
    9: $('#sched-anchor-eve').value || '19:00',
  };

  const toMin = (s) => {
    const [h, m] = s.split(':').map(Number);
    return h * 60 + m;
  };
  const toHHMM = (n) => {
    const h = Math.floor(n / 60) % 24;
    const m = n % 60;
    return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
  };

  const periods = {};
  PERIOD_SECTIONS.forEach(sec => {
    const start = toMin(anchors[sec.periods[0]]);
    sec.periods.forEach((p, i) => {
      const s = start + i * (duration + gap);
      periods[String(p)] = { start: toHHMM(s), end: toHHMM(s + duration) };
    });
  });

  renderPeriodInputs(periods);
}

/** 保存作息 */
async function savePeriods() {
  const btn = $('#sched-period-save');

  const periods = {};
  $('#sched-period-list').querySelectorAll('.pl-row').forEach(row => {
    const p = row.dataset.period;
    const s = row.querySelector('.pl-start').value;
    const e = row.querySelector('.pl-end').value;
    if (s && e) periods[p] = { start: s, end: e };
  });

  if (!Object.keys(periods).length) {
    alert('请先生成或填写节次时间');
    return;
  }

  btn.disabled = true;
  btn.textContent = '保存中…';

  try {
    const res = await fetch('/api/schedule/periods', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        term: {
          start: $('#sched-term-start').value,
          weeks: parseInt($('#sched-term-weeks').value, 10) || 20,
        },
        periods,
      }),
    });
    const d = await res.json();
    if (!d.ok) throw new Error(d.message || '保存失败');

    closePeriodModal();
    loadSchedulePage();
  } catch (err) {
    alert('保存失败：' + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '保存';
  }
}

/* -------- 单间教室周课表 -------- */

function initRoomModal() {
  const modal = $('#sched-room-modal');
  if (!modal) return;

  $('#sched-room-close').addEventListener('click', () =>
    modal.classList.add('hidden'));
  modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.classList.add('hidden');
  });
}

async function openRoomSchedule(building, room) {
  const modal = $('#sched-room-modal');
  const body = $('#sched-room-body');

  $('#sched-room-title').textContent = `${building}-${room} 本周课表`;
  body.innerHTML = '<div class="sched-loading">读取中…</div>';
  modal.classList.remove('hidden');

  const params = new URLSearchParams({ building, room });

  let d;
  try {
    const res = await fetch('/api/schedule/room?' + params);
    d = await res.json();
    if (!d.ok) throw new Error(d.message || '读取失败');
  } catch (err) {
    body.innerHTML = `<div class="sched-room-empty">
        这间教室还没有导入课表
        <span>导入后就能看到它一周的安排了</span>
      </div>`;
    return;
  }

  // 当前周由后端给（/api/schedule/room 现在返回 week）
  const week = d.week || 1;

  const byCell = {};
  (d.courses || []).forEach(c => {
    // 只显示当前周有课的（同一格可能有两门不同周次的课）
    if (week < c.week_start || week > c.week_end) return;
    const key = c.day + '-' + c.period_start;
    byCell[key] = byCell[key] || [];
    byCell[key].push(c);
  });

  const rows = [];
  for (let p = 1; p <= 12; p++) {
    const cells = [];
    for (let day = 1; day <= 7; day++) {
      const list = byCell[day + '-' + p];
      cells.push(list && list.length
        ? `<td class="cell-busy">${list.map(c =>
            `<div class="cc-name">${escapeHtml(c.name)}</div>
             <div class="cc-meta">${escapeHtml(c.teacher || '')}
             · ${c.students || 0}人</div>`).join('')}</td>`
        : '<td></td>');
    }
    rows.push(`<tr><th>第 ${p} 节</th>${cells.join('')}</tr>`);
  }

  const weekNote = week ? `第 ${week} 周` : '当前周';

  try {
  body.innerHTML = `
    <div class="sched-room-head">
      <span>${escapeHtml(d.label || '')}</span>
      <span class="srh-meta">座位 ${d.seats || 0} · ${weekNote}</span>
    </div>
    <div class="sched-grid-wrap">
      <table class="sched-grid">
        <thead>
          <tr><th></th>${SCHED_DAYS.map(w => `<th>${w.slice(-1)}</th>`).join('')}</tr>
        </thead>
        <tbody>${rows.join('')}</tbody>
      </table>
    </div>`;
  } catch (err) {
    // 宁可把错误摆出来，也不要停在"读取中…"上让人以为卡死了
    console.error('渲染教室课表失败', err);
    body.innerHTML = `<div class="sched-room-empty">
        课表渲染失败
        <span>${escapeHtml(err.message)}</span>
      </div>`;
  }
}

/* ============================================================
   初始化
   ============================================================ */
loadLandingStats();
loadRoomPicker();
initTaskForm();


