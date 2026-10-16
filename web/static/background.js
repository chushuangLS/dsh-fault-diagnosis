/* ============================================================
   机房故障智能诊断助手 - 动态线条背景

   效果：
     细密平行线被一个平滑噪声场扰动，形成缓慢起伏的"布料/水波"感。
     鼠标是额外的扰动源 —— 光标移到哪，哪里的线条就被轻轻拨开，
     移开后平滑回位。

   两种模式：
     landing —— 落地页：线条清晰（透明度 0.28），是页面的视觉主体
     app     —— 应用页：线条变淡（透明度 0.14），
                其余参数完全相同，所以切换时不会"跳变"，只是安静下来。
                目标是「能看出背景在动，但不干扰读表格与对话」。

   实现：Canvas 2D + 自写的值噪声（value noise）。
        不依赖任何第三方库 —— 项目前端保持零依赖。

   性能：
     · 只在需要时绘制（页面隐藏时暂停）
     · 限制 DPR ≤ 2，避免高分屏上过度绘制
     · 逐条线一次性 path 画出，不做逐点 stroke

   作者：liyishuo1
   ============================================================ */

(function () {
  'use strict';

  /* ------------------------------------------------------------
     参数（由预览页调参确定）
     ------------------------------------------------------------ */
  const BASE = {
    count: 76,          // 线条数量
    amp: 43,            // 波浪幅度
    speed: 1.2,         // 演化速度
    width: 0.8,         // 线条粗细
    radius: 83,         // 鼠标影响半径
    force: 15,          // 鼠标影响力度
    color: [59, 130, 246],   // 主题蓝
  };

  const ALPHA = {
    landing: 0.28,      // 落地页：清晰，是页面的视觉主体
    // 应用页：大幅淡化。
    // 应用页布满文字、表格与卡片，背景一旦显眼就会干扰阅读，
    // 因此这里降到落地页的 1/4 —— 静止时几乎察觉不到，
    // 只有余光或刻意观察时才看得出线条在缓慢流动。
    app: 0.07,
  };

  /* ------------------------------------------------------------
     值噪声
     在整数格点放随机值，格点之间用 smoothstep 插值 ——
     这样起伏是连续平滑的，不会出现随机跳变。
     ------------------------------------------------------------ */
  function makeNoise(seed) {
    let s = seed >>> 0;
    const rand = () => {
      s = (s * 1664525 + 1013904223) >>> 0;
      return s / 4294967296;
    };

    const table = new Float32Array(256 * 256);
    for (let i = 0; i < table.length; i++) table[i] = rand() * 2 - 1;

    const at = (x, y) => table[((y & 255) << 8) + (x & 255)];
    const fade = (t) => t * t * (3 - 2 * t);   // smoothstep

    return function noise2d(x, y) {
      const xi = Math.floor(x), yi = Math.floor(y);
      const xf = x - xi, yf = y - yi;

      const v00 = at(xi, yi);
      const v10 = at(xi + 1, yi);
      const v01 = at(xi, yi + 1);
      const v11 = at(xi + 1, yi + 1);

      const u = fade(xf), v = fade(yf);
      const a = v00 + (v10 - v00) * u;
      const b = v01 + (v11 - v01) * u;
      return a + (b - a) * v;
    };
  }

  const noise = makeNoise(7);

  /* ------------------------------------------------------------
     初始化
     ------------------------------------------------------------ */
  const canvas = document.getElementById('bg-canvas');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  let W = 0, H = 0, DPR = 1;

  function resize() {
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    W = window.innerWidth;
    H = window.innerHeight;
    canvas.width = Math.floor(W * DPR);
    canvas.height = Math.floor(H * DPR);
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }

  window.addEventListener('resize', resize, { passive: true });
  resize();

  /* ------------------------------------------------------------
     状态
     ------------------------------------------------------------ */
  let mode = 'landing';

  // 当前透明度：切换模式时做渐变，避免颜色"啪"地跳一下
  let alpha = ALPHA.landing;
  let alphaTarget = ALPHA.landing;

  // 鼠标
  let mx = -9999, my = -9999;      // 原始位置
  let tx = -9999, ty = -9999;      // 缓动后的位置
  let influence = 0;               // 0~1，鼠标离开后衰减
  let pointerInside = false;

  // 是否正在前台（切到别的标签页就暂停绘制，省电）
  let visible = true;

  let t = 0;
  let rafId = null;

  /* ------------------------------------------------------------
     用户是否偏好减少动态效果
     尊重系统设置：这类人可能对持续动画不适
     ------------------------------------------------------------ */
  const reduceMotion = window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ------------------------------------------------------------
     事件
     ------------------------------------------------------------ */
  window.addEventListener('pointermove', (e) => {
    mx = e.clientX;
    my = e.clientY;
    if (!pointerInside) {
      // 刚进入页面：直接落位，避免线条从左上角"飞"过来
      tx = mx;
      ty = my;
    }
    pointerInside = true;
  }, { passive: true });

  document.addEventListener('pointerleave', () => { pointerInside = false; });
  window.addEventListener('blur', () => { pointerInside = false; });

  document.addEventListener('visibilitychange', () => {
    visible = !document.hidden;
    if (visible && rafId === null) {
      lastTime = performance.now();
      rafId = requestAnimationFrame(draw);
    }
  });

  /* ------------------------------------------------------------
     绘制
     ------------------------------------------------------------ */
  let lastTime = performance.now();

  function draw(now) {
    rafId = null;
    if (!visible) return;

    const dt = Math.min((now - lastTime) / 1000, 0.05);
    lastTime = now;

    // 「减少动态」时几乎静止，只保留极缓慢的变化
    t += dt * BASE.speed * (reduceMotion ? 0.12 : 1);

    // 透明度渐变（约 0.5 秒过渡完）
    alpha += (alphaTarget - alpha) * 0.10;

    // 鼠标缓动跟随：系数小一点，线条"黏"着光标走
    tx += (mx - tx) * 0.12;
    ty += (my - ty) * 0.12;

    // 影响强度：进入页面时升起，离开后缓慢衰减
    const targetInf = pointerInside ? 1 : 0;
    influence += (targetInf - influence) * (pointerInside ? 0.10 : 0.03);

    ctx.clearRect(0, 0, W, H);

    const count = BASE.count;
    const gap = H / (count + 1);
    const [cr, cg, cb] = BASE.color;

    // 采样步长：越大越省，但曲线会变糙
    const step = Math.max(6, W / 220);

    ctx.lineWidth = BASE.width;
    ctx.lineCap = 'round';

    // 鼠标扰动参数（循环外算一次）
    const useForce = BASE.force > 0 && influence > 0.01 && BASE.radius > 0;
    const gaussK = 2 * (BASE.radius * 0.42) ** 2;

    for (let i = 0; i < count; i++) {
      const baseY = gap * (i + 1);
      const linePhase = i * 0.28;   // 逐条错开相位，避免整体平移感

      ctx.beginPath();

      for (let x = -step; x <= W + step; x += step) {
        // 基础起伏：噪声场 + 低频正弦
        let y = baseY
          + noise(x * 0.0016, baseY * 0.004 + t * 0.16 + linePhase) * BASE.amp
          + Math.sin(x * 0.0032 + t * 0.5 + linePhase) * BASE.amp * 0.42;

        // 鼠标扰动：以光标为中心的高斯衰减
        if (useForce) {
          const dx = x - tx;
          const dy = baseY - ty;
          const distSq = dx * dx + dy * dy;

          if (distSq < BASE.radius * BASE.radius) {
            const w = Math.exp(-distSq / gaussK);
            // 用噪声决定推开方向，比固定方向更像流体
            const dir = noise(dx * 0.01 + t * 0.6, dy * 0.01);
            y += dir * w * BASE.force * influence;
          }
        }

        if (x <= -step) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }

      // 上下边缘略淡，中间稍亮，避免整片死板
      const edge = 1 - Math.abs((i / (count - 1 || 1)) - 0.5) * 0.75;
      ctx.strokeStyle = `rgba(${cr},${cg},${cb},${(alpha * edge).toFixed(3)})`;
      ctx.stroke();
    }

    rafId = requestAnimationFrame(draw);
  }

  rafId = requestAnimationFrame(draw);

  /* ------------------------------------------------------------
     对外接口：切换模式
     ------------------------------------------------------------ */
  window.BgField = {
    /**
     * 切换模式
     * @param {'landing'|'app'} m
     */
    setMode(m) {
      if (!ALPHA[m]) return;
      mode = m;
      alphaTarget = ALPHA[m];
    },
    getMode() { return mode; },
  };
})();
