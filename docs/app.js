(function () {
  "use strict";
  /* GR 테마 RSI 대시보드
     데이터: data/kr_all.json (국내 전체 종목) · data/kr_latest.json (국내 과매도 알림 + 매물대) · data/us_latest.json (미국 과매도 알림 + 매물대) */

  const S = {
    market: "ALL",
    tab: "all",
    theme: "전체",
    sort: "rsi",
    q: "",
    sel: null,
    raw: { all: null, kr: null, us: null },
    stocks: [],
    view: null,
    cross: null,
  };
  const $ = (id) => document.getElementById(id);
  const P = { all: $("panel-all"), alert: $("panel-alert"), chart: $("panel-chart"), profile: $("panel-profile") };
  const UP = "#26a69a", DN = "#ef5350";

  const num = (n, d) => (n === null || n === undefined || Number.isNaN(n) ? "-" : Number(n).toLocaleString("ko-KR", { maximumFractionDigits: d ?? 0, minimumFractionDigits: d ?? 0 }));
  const pxStr = (s, v) => (v === null || v === undefined ? "-" : s.src === "US" ? "$" + num(v, v < 10 ? 3 : 2) : num(v, 0) + "원");
  const pct = (v) => (v === null || v === undefined || Number.isNaN(v) ? "-" : (v >= 0 ? "+" : "") + v.toFixed(2) + "%");
  const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  async function getJson(path) {
    try {
      const r = await fetch(`${path}?_=${Date.now()}`);
      return r.ok ? await r.json() : null;
    } catch (e) {
      return null;
    }
  }

  /* ───── 데이터 합치기 ───── */
  function build() {
    const out = [];
    const krAlert = new Map(((S.raw.kr && S.raw.kr.stocks) || []).map((s) => [s.code, s]));
    const seen = new Set();
    for (const s of (S.raw.all && S.raw.all.stocks) || []) {
      const a = krAlert.get(s.code);
      out.push(norm("KR", s, a));
      seen.add(s.code);
    }
    for (const s of krAlert.values()) if (!seen.has(s.code)) out.push(norm("KR", s, s));
    for (const s of (S.raw.us && S.raw.us.stocks) || []) out.push(norm("US", s, s));
    S.stocks = out;
  }
  function norm(src, s, alert) {
    const bars = (s.daily_bars && s.daily_bars.length ? s.daily_bars : (alert && alert.daily_bars) || []).filter((b) => b && b.close != null);
    const close = s.close ?? (bars.length ? bars[bars.length - 1].close : null);
    let ch = s.change_pct;
    if (ch == null && bars.length >= 2) ch = (bars[bars.length - 1].close / bars[bars.length - 2].close - 1) * 100;
    const themes = s.themes || [s.theme || "미분류"];
    const dr = s.daily_rsi ?? (alert && alert.daily_rsi), wr = s.weekly_rsi ?? (alert && alert.weekly_rsi);
    const os = (dr != null && dr <= 30) || (wr != null && wr <= 30);
    return { key: `${src}|${s.code || s.label}`, src, code: s.code || "", name: s.name || s.label, themes, close, ch, dr, wr, os, alert: !!alert, bars, vs: (alert && alert.volume_summary) || s.volume_summary || null, mkt: s.market_type || (alert && alert.market_type) || "" };
  }
  function visible() {
    return S.stocks.filter((s) => S.market === "ALL" || s.src === S.market);
  }
  function themeList(list) {
    const m = new Map();
    for (const s of list) for (const t of s.themes) m.set(t, (m.get(t) || 0) + 1);
    return [...m.entries()];
  }
  function sorted(list) {
    const k = S.sort,
      r = (s) => (s.dr == null ? 999 : s.dr);
    return list.slice().sort((a, b) => (k === "rsi" ? r(a) - r(b) : k === "chg" ? (b.ch ?? -999) - (a.ch ?? -999) : k === "chgd" ? (a.ch ?? 999) - (b.ch ?? 999) : a.name.localeCompare(b.name, "ko")));
  }

  /* ───── 공통: 종목 줄 ───── */
  function rsiTag(label, v) {
    if (v == null) return `<span class="tag">${label} -</span>`;
    const c = v <= 30 ? "os" : v >= 70 ? "hot" : "mid";
    const w = v <= 30 ? " 과매도" : v >= 70 ? " 과열" : "";
    return `<span class="tag ${c}">${label} ${v.toFixed(1)}${w}</span>`;
  }
  function row(s) {
    return `<div class="row ${s.os ? "os" : ""}" data-k="${esc(s.key)}">
      <div><div class="nm">${esc(s.name)}${s.src === "US" ? '<span class="tag us">미국</span>' : ""}${s.alert ? '<span class="tag os">🔔 알림</span>' : ""}</div>
        <div class="cd">${esc(s.code)}${s.mkt ? " · " + esc(s.mkt) : ""}</div></div>
      <canvas class="spark" data-k="${esc(s.key)}" width="148" height="60"></canvas>
      <div class="rt"><div class="px">${pxStr(s, s.close)}</div><div class="ch ${s.ch >= 0 ? "up" : "dn"}">${pct(s.ch)}</div></div>
      <div class="rsis">${rsiTag("일봉 RSI", s.dr)}${rsiTag("주봉 RSI", s.wr)}${s.vs ? '<span class="tag">📊 매물대</span>' : ""}</div>
    </div>`;
  }
  function bindRows(root) {
    root.querySelectorAll(".row").forEach((el) =>
      el.addEventListener("click", () => {
        S.sel = el.dataset.k;
        S.view = null;
        S.cross = null;
        setTab("chart");
      })
    );
    root.querySelectorAll("canvas.spark").forEach((cv) => {
      const s = S.stocks.find((x) => x.key === cv.dataset.k);
      if (s) spark(cv, s.bars.slice(-40).map((b) => b.close));
    });
  }
  function spark(cv, v) {
    const c = cv.getContext("2d"), w = cv.width, h = cv.height;
    c.clearRect(0, 0, w, h);
    if (v.length < 2) return;
    const lo = Math.min(...v), hi = Math.max(...v), sp = hi - lo || 1, col = v[v.length - 1] >= v[0] ? UP : DN;
    const X = (i) => (i / (v.length - 1)) * (w - 4) + 2, Y = (x) => h - 4 - ((x - lo) / sp) * (h - 8);
    const g = c.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, col + "55");
    g.addColorStop(1, col + "00");
    c.beginPath();
    v.forEach((x, i) => (i ? c.lineTo(X(i), Y(x)) : c.moveTo(X(i), Y(x))));
    c.lineTo(X(v.length - 1), h);
    c.lineTo(X(0), h);
    c.fillStyle = g;
    c.fill();
    c.beginPath();
    v.forEach((x, i) => (i ? c.lineTo(X(i), Y(x)) : c.moveTo(X(i), Y(x))));
    c.strokeStyle = col;
    c.lineWidth = 2.4;
    c.stroke();
  }
  const empty = (a, b) => `<div class="empty"><span class="e">📭</span>${a}<br>${b || ""}</div>`;

  /* ───── 전체 종목 ───── */
  function renderAll() {
    const base = visible();
    if (!base.length) {
      P.all.innerHTML = empty("아직 데이터가 없어요.", "평일 18:30 자동 실행 뒤에 채워져요.");
      return;
    }
    const themes = themeList(base);
    if (S.theme !== "전체" && !themes.some(([t]) => t === S.theme)) S.theme = "전체";
    const q = S.q.trim().toLowerCase();
    const list = base.filter((s) => (S.theme === "전체" || s.themes.includes(S.theme)) && (!q || s.name.toLowerCase().includes(q) || s.code.includes(q)));
    const nOs = list.filter((s) => s.os).length,
      rs = list.filter((s) => s.dr != null).map((s) => s.dr),
      avg = rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : null;
    const missAll = (S.market !== "US" && !S.raw.all) ? '<div class="info">ℹ️ 국내 <b>전체 종목</b> 데이터는 다음 자동 실행(평일 18:30) 뒤에 채워져요. 지금은 알림 종목만 보여요.</div>' : "";
    let html = `${missAll}<div class="summary"><div><div class="k">종목</div><div class="v">${list.length}</div></div><div><div class="k">과매도 (RSI 30↓)</div><div class="v dn">${nOs}</div></div><div><div class="k">평균 일봉 RSI</div><div class="v">${avg == null ? "-" : avg.toFixed(1)}</div></div></div>
      <div class="chips">${[["전체", base.length], ...themes].map(([t, n]) => `<button class="chip ${S.theme === t ? "on" : ""}" data-t="${esc(t)}">${esc(t)}<b>${n}</b></button>`).join("")}</div>
      <div class="toolbar"><input id="q" placeholder="종목 이름·코드 찾기" value="${esc(S.q)}"><select id="sort">
        <option value="rsi"${S.sort === "rsi" ? " selected" : ""}>RSI 낮은 순</option><option value="chg"${S.sort === "chg" ? " selected" : ""}>많이 오른 순</option><option value="chgd"${S.sort === "chgd" ? " selected" : ""}>많이 내린 순</option><option value="name"${S.sort === "name" ? " selected" : ""}>이름 순</option></select></div>`;
    if (S.theme === "전체" && !q) {
      for (const [t] of themes) {
        const g = sorted(list.filter((s) => s.themes.includes(t)));
        if (!g.length) continue;
        html += `<div class="theme-h">${esc(t)}<span>${g.length}종목 · 과매도 ${g.filter((s) => s.os).length}</span></div>` + g.map(row).join("");
      }
    } else html += sorted(list).map(row).join("") || empty("찾는 종목이 없어요.");
    P.all.innerHTML = html;
    P.all.querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => { S.theme = b.dataset.t; renderAll(); }));
    const qi = $("q");
    qi.addEventListener("input", () => { S.q = qi.value; const pos = qi.selectionStart; renderAll(); const n = $("q"); n.focus(); n.setSelectionRange(pos, pos); });
    $("sort").addEventListener("change", (e) => { S.sort = e.target.value; renderAll(); });
    bindRows(P.all);
  }

  /* ───── 과매도 알림 ───── */
  function renderAlert() {
    const list = sorted(visible().filter((s) => s.alert || s.os));
    if (!list.length) {
      P.alert.innerHTML = empty("지금은 과매도 종목이 없어요.", "일봉이나 주봉 RSI가 30 이하가 되면 여기에 떠요.");
      return;
    }
    const g = new Map();
    for (const s of list) for (const t of s.themes.slice(0, 1)) (g.get(t) || g.set(t, []).get(t)).push(s);
    P.alert.innerHTML = [...g.entries()].map(([t, l]) => `<div class="theme-h">${esc(t)}<span>${l.length}종목</span></div>` + l.map(row).join("")).join("");
    bindRows(P.alert);
  }

  /* ───── 차트 (GR 스타일) ───── */
  function curList() {
    const base = visible();
    return sorted(base.filter((s) => S.theme === "전체" || s.themes.includes(S.theme)));
  }
  function renderChart() {
    const list = curList().filter((s) => s.bars.length);
    if (!list.length) {
      P.chart.innerHTML = empty("차트를 그릴 데이터가 없어요.", "자동 실행 뒤에 채워져요.");
      return;
    }
    if (!S.sel || !list.some((s) => s.key === S.sel)) S.sel = list[0].key;
    const s = list.find((x) => x.key === S.sel);
    const last = s.bars[s.bars.length - 1];
    P.chart.innerHTML = `<div class="pick">${list.slice(0, 80).map((x) => `<button class="chip ${x.key === S.sel ? "on" : ""}" data-k="${esc(x.key)}">${esc(x.name)}${x.os ? " 🔻" : ""}</button>`).join("")}</div>
      <div class="chart-top"><div><div class="nm">${esc(s.name)}</div><div class="sub">${esc(s.code)} · ${esc(s.themes.join(" · "))} · 일봉</div></div>
        <div><div class="big">${pxStr(s, s.close ?? last.close)}</div><div class="ch ${s.ch >= 0 ? "up" : "dn"}">${pct(s.ch)}</div></div></div>
      <div class="chart-box" id="cbox"><canvas id="cv"></canvas></div>
      <div class="legend"><span><i style="background:#ffd740"></i>5일선</span><span><i style="background:#ff6d00"></i>20일선</span><span><i style="background:#5b8cff"></i>60일선</span><span><i style="background:#b388ff"></i>RSI(14)</span>${s.vs ? '<span><i style="background:#26a69a"></i>지지</span><span><i style="background:#ef5350"></i>저항</span>' : ""}</div>
      ${infoCard(s)}`;
    P.chart.querySelectorAll(".pick .chip").forEach((b) => b.addEventListener("click", () => { S.sel = b.dataset.k; S.view = null; S.cross = null; renderChart(); }));
    const on = P.chart.querySelector(".pick .chip.on");
    if (on) on.scrollIntoView({ inline: "center", block: "nearest" });
    setupChart(s);
  }
  function infoCard(s) {
    const st = (v) => (v == null ? "데이터 없음" : v <= 30 ? "<b class='dn'>과매도</b> (30 이하 · 많이 떨어진 상태)" : v >= 70 ? "<b style='color:#ff9100'>과열</b> (70 이상 · 많이 오른 상태)" : v < 45 ? "약한 편" : v > 55 ? "강한 편" : "중간");
    let h = `<div class="info">일봉 RSI <b>${s.dr == null ? "-" : s.dr.toFixed(1)}</b> · ${st(s.dr)}<br>주봉 RSI <b>${s.wr == null ? "-" : s.wr.toFixed(1)}</b> · ${st(s.wr)}`;
    if (s.vs) {
      const v = s.vs;
      h += `<br>📊 매물대: <b>${esc(v.position || "")}</b> · 핵심 ${num(v.poc_low, s.src === "US" ? 2 : 0)}~${num(v.poc_high, s.src === "US" ? 2 : 0)}`;
      if (v.support_price) h += ` · 지지 ${num(v.support_price, s.src === "US" ? 2 : 0)} (${v.support_distance_pct != null ? "-" + Math.abs(v.support_distance_pct).toFixed(1) + "%" : ""})`;
      if (v.resistance_price) h += ` · 저항 ${num(v.resistance_price, s.src === "US" ? 2 : 0)} (+${v.resistance_distance_pct != null ? v.resistance_distance_pct.toFixed(1) : "-"}%)`;
    }
    return h + `<br><span style="color:#8b949e;font-size:12px">끌어서 옮기기 · 두 손가락(또는 휠)으로 확대 · 누르면 십자선</span></div>`;
  }
  function ma(arr, n) {
    const o = new Array(arr.length).fill(null);
    let sum = 0;
    for (let i = 0; i < arr.length; i++) {
      sum += arr[i];
      if (i >= n) sum -= arr[i - n];
      if (i >= n - 1) o[i] = sum / n;
    }
    return o;
  }
  function setupChart(s) {
    const box = $("cbox"), cv = $("cv"), c = cv.getContext("2d");
    const bars = s.bars, n = bars.length, closes = bars.map((b) => b.close);
    const M5 = ma(closes, 5), M20 = ma(closes, 20), M60 = ma(closes, 60);
    if (!S.view) S.view = { end: n - 1 + 3, count: Math.min(n + 3, 70) };
    let W = 0, H = 0, dpr = 1;
    const AX = 62, mainH = () => H * 0.68, rsiTop = () => mainH() + 8, rsiH = () => H - mainH() - 30;
    function size() {
      dpr = Math.min(2, window.devicePixelRatio || 1);
      W = box.clientWidth;
      H = Math.round(Math.min(520, Math.max(380, W * 0.95)));
      cv.width = W * dpr;
      cv.height = H * dpr;
      cv.style.height = H + "px";
      c.setTransform(dpr, 0, 0, dpr, 0, 0);
      draw();
    }
    const plotW = () => W - AX;
    function clampView() {
      const v = S.view;
      v.count = Math.max(15, Math.min(n + 10, v.count));
      v.end = Math.max(v.count * 0.3, Math.min(n - 1 + v.count * 0.4, v.end));
    }
    function xOf(i) {
      const v = S.view, bw = plotW() / v.count;
      return plotW() - (v.end - i + 0.5) * bw;
    }
    function iOfX(x) {
      const v = S.view, bw = plotW() / v.count;
      return Math.round(v.end - (plotW() - x) / bw + 0.5 - 0.5);
    }
    function nice(lo, hi, cnt) {
      const raw = (hi - lo) / cnt, p = Math.pow(10, Math.floor(Math.log10(raw))), m = raw / p;
      return (m < 1.5 ? 1 : m < 3 ? 2 : m < 7 ? 5 : 10) * p;
    }
    function draw() {
      clampView();
      const v = S.view, bw = plotW() / v.count;
      const a = Math.max(0, Math.floor(v.end - v.count)), b = Math.min(n - 1, Math.ceil(v.end));
      c.fillStyle = "#131722";
      c.fillRect(0, 0, W, H);
      if (b < a) return;
      let lo = Infinity, hi = -Infinity;
      for (let i = a; i <= b; i++) {
        lo = Math.min(lo, bars[i].low);
        hi = Math.max(hi, bars[i].high);
        for (const L of [M5, M20, M60]) if (L[i] != null) { lo = Math.min(lo, L[i]); hi = Math.max(hi, L[i]); }
      }
      const pad = (hi - lo) * 0.08 || hi * 0.02;
      lo -= pad; hi += pad;
      const top = 10, mh = mainH() - 22;
      const yOf = (p) => top + ((hi - p) / (hi - lo)) * mh;
      // 격자 · 가격 눈금
      const st = nice(lo, hi, 5);
      c.font = "11px ui-monospace, monospace";
      c.textAlign = "left";
      for (let p = Math.ceil(lo / st) * st; p <= hi; p += st) {
        const y = yOf(p);
        c.fillStyle = "#1e2330";
        c.fillRect(0, Math.round(y), plotW(), 1);
        c.fillStyle = "#787b86";
        c.fillText(s.src === "US" ? p.toFixed(p < 10 ? 2 : 1) : num(p, 0), plotW() + 6, y + 4);
      }
      // 매물대 지지·저항 · 핵심 구간
      if (s.vs) {
        const vs = s.vs;
        if (vs.poc_low && vs.poc_high) {
          const y1 = yOf(vs.poc_high), y2 = yOf(vs.poc_low);
          c.fillStyle = "rgba(255,215,64,.08)";
          c.fillRect(0, y1, plotW(), y2 - y1);
        }
        for (const [p, col, t] of [[vs.support_price, UP, "지지"], [vs.resistance_price, DN, "저항"]]) {
          if (!p || p < lo || p > hi) continue;
          const y = yOf(p);
          c.strokeStyle = col; c.setLineDash([5, 4]); c.lineWidth = 1.2;
          c.beginPath(); c.moveTo(0, y); c.lineTo(plotW(), y); c.stroke(); c.setLineDash([]);
          c.fillStyle = col; c.font = "bold 11px sans-serif"; c.fillText(t, 6, y - 4);
        }
      }
      // 거래량 (가격 칸 아래쪽)
      let vmax = 0;
      for (let i = a; i <= b; i++) vmax = Math.max(vmax, bars[i].volume || 0);
      const vh = mh * 0.22;
      for (let i = a; i <= b; i++) {
        const x = xOf(i), bb = bars[i], up = bb.close >= bb.open, h = vmax ? ((bb.volume || 0) / vmax) * vh : 0;
        c.fillStyle = up ? "rgba(38,166,154,.35)" : "rgba(239,83,80,.35)";
        c.fillRect(x - bw * 0.35, top + mh - h, Math.max(1, bw * 0.7), h);
      }
      // 캔들
      for (let i = a; i <= b; i++) {
        const x = xOf(i), bb = bars[i], up = bb.close >= bb.open, col = up ? UP : DN;
        c.strokeStyle = col; c.lineWidth = 1;
        c.beginPath(); c.moveTo(Math.round(x) + 0.5, yOf(bb.high)); c.lineTo(Math.round(x) + 0.5, yOf(bb.low)); c.stroke();
        const y1 = yOf(Math.max(bb.open, bb.close)), y2 = yOf(Math.min(bb.open, bb.close));
        c.fillStyle = col;
        c.fillRect(x - bw * 0.36, y1, Math.max(1, bw * 0.72), Math.max(1, y2 - y1));
      }
      // 이동평균선
      for (const [L, col] of [[M60, "#5b8cff"], [M20, "#ff6d00"], [M5, "#ffd740"]]) {
        c.strokeStyle = col; c.lineWidth = 1.4; c.beginPath();
        let st0 = false;
        for (let i = a; i <= b; i++) { if (L[i] == null) continue; const x = xOf(i), y = yOf(L[i]); st0 ? c.lineTo(x, y) : c.moveTo(x, y); st0 = true; }
        c.stroke();
      }
      // 현재가 줄 · 태그
      const lb = bars[n - 1], lcol = lb.close >= lb.open ? UP : DN, yl = yOf(lb.close);
      if (yl > top && yl < top + mh) {
        c.strokeStyle = lcol; c.setLineDash([3, 3]); c.lineWidth = 1;
        c.beginPath(); c.moveTo(0, yl); c.lineTo(plotW(), yl); c.stroke(); c.setLineDash([]);
        tag(yl, s.src === "US" ? lb.close.toFixed(2) : num(lb.close, 0), lcol, "#fff");
      }
      // RSI 칸
      const rt = rsiTop(), rh = rsiH(), yR = (r) => rt + ((100 - r) / 100) * rh;
      c.fillStyle = "#0f131c"; c.fillRect(0, rt - 4, W, rh + 8);
      c.fillStyle = "rgba(179,136,255,.07)"; c.fillRect(0, yR(70), plotW(), yR(30) - yR(70));
      c.strokeStyle = "#3a3f4b"; c.setLineDash([4, 4]); c.lineWidth = 1;
      for (const r of [30, 70]) { c.beginPath(); c.moveTo(0, yR(r)); c.lineTo(plotW(), yR(r)); c.stroke(); }
      c.setLineDash([]);
      c.fillStyle = "#787b86"; c.font = "10.5px ui-monospace, monospace";
      c.fillText("70", plotW() + 6, yR(70) + 4); c.fillText("30", plotW() + 6, yR(30) + 4);
      c.fillStyle = "#b388ff"; c.font = "bold 11px sans-serif"; c.fillText("RSI 14", 6, rt + 10);
      // 30 아래 빨갛게
      c.strokeStyle = "#b388ff"; c.lineWidth = 1.6; c.beginPath();
      let s0 = false;
      for (let i = a; i <= b; i++) { const r = bars[i].rsi; if (r == null) { s0 = false; continue; } const x = xOf(i), y = yR(r); s0 ? c.lineTo(x, y) : c.moveTo(x, y); s0 = true; }
      c.stroke();
      for (let i = a; i <= b; i++) { const r = bars[i].rsi; if (r != null && r <= 30) { c.fillStyle = "rgba(239,83,80,.75)"; c.beginPath(); c.arc(xOf(i), yR(r), 2.2, 0, 7); c.fill(); } }
      const lr = [...bars].reverse().find((x) => x.rsi != null);
      if (lr) tag(yR(lr.rsi), lr.rsi.toFixed(1), lr.rsi <= 30 ? DN : lr.rsi >= 70 ? "#ff9100" : "#7c4dff", "#fff");
      // 날짜
      c.fillStyle = "#787b86"; c.font = "10.5px ui-monospace, monospace"; c.textAlign = "center";
      const stepI = Math.max(1, Math.round(v.count / 5));
      for (let i = Math.ceil(a / stepI) * stepI; i <= b; i += stepI) { const d = bars[i].date; c.fillText(`${d.slice(4, 6)}/${d.slice(6, 8)}`, xOf(i), H - 8); }
      c.textAlign = "left";
      // 십자선 · 정보
      const ci = S.cross != null ? Math.max(a, Math.min(b, S.cross.i)) : n - 1, cb = bars[ci];
      if (S.cross != null) {
        const x = xOf(ci);
        c.strokeStyle = "rgba(200,200,200,.45)"; c.setLineDash([4, 4]); c.lineWidth = 1;
        c.beginPath(); c.moveTo(x, 0); c.lineTo(x, H - 18); c.stroke();
        if (S.cross.y < top + mh) { c.beginPath(); c.moveTo(0, S.cross.y); c.lineTo(plotW(), S.cross.y); c.stroke(); const p = hi - ((S.cross.y - top) / mh) * (hi - lo); c.setLineDash([]); tag(S.cross.y, s.src === "US" ? p.toFixed(2) : num(p, 0), "#363a45", "#fff"); }
        c.setLineDash([]);
        const d = cb.date; c.fillStyle = "#363a45"; c.fillRect(x - 30, H - 20, 60, 16); c.fillStyle = "#fff"; c.textAlign = "center"; c.fillText(`${d.slice(2, 4)}.${d.slice(4, 6)}.${d.slice(6, 8)}`, x, H - 8); c.textAlign = "left";
      }
      const pv = ci > 0 ? bars[ci - 1].close : cb.open, chg = (cb.close / pv - 1) * 100, f = (p) => (s.src === "US" ? p.toFixed(2) : num(p, 0));
      const t1 = `${cb.date.slice(4, 6)}/${cb.date.slice(6, 8)}  시 ${f(cb.open)}  고 ${f(cb.high)}  저 ${f(cb.low)}  종 ${f(cb.close)}`;
      c.font = "11px ui-monospace, monospace";
      const tw = Math.min(plotW() - 8, c.measureText(t1).width + 70);
      c.fillStyle = "rgba(19,23,34,.85)"; c.fillRect(4, 4, tw, 32);
      c.fillStyle = "#d1d4dc"; c.fillText(t1, 8, 17);
      c.fillStyle = chg >= 0 ? UP : DN; c.fillText(pct(chg), 8, 31);
      c.fillStyle = "#8b949e"; c.fillText(`거래량 ${num(cb.volume, 0)}${cb.rsi != null ? "  RSI " + cb.rsi.toFixed(1) : ""}`, 70, 31);
    }
    function tag(y, t, bg, fg) {
      c.font = "bold 11px ui-monospace, monospace";
      c.fillStyle = bg; c.fillRect(plotW() + 1, y - 9, AX - 2, 18);
      c.fillStyle = fg; c.textAlign = "left"; c.fillText(t, plotW() + 5, y + 4);
    }
    // 조작: 끌기(옮기기) · 두 손가락/휠(확대) · 누르기(십자선)
    const pts = new Map();
    let drag = null, pinch = null, moved = false;
    cv.addEventListener("pointerdown", (e) => {
      cv.setPointerCapture(e.pointerId);
      pts.set(e.pointerId, { x: e.offsetX, y: e.offsetY });
      moved = false;
      if (pts.size === 1) drag = { x: e.offsetX, end: S.view.end };
      if (pts.size === 2) { const [p1, p2] = [...pts.values()]; pinch = { d: Math.abs(p1.x - p2.x) || 1, count: S.view.count }; drag = null; }
    });
    cv.addEventListener("pointermove", (e) => {
      if (!pts.has(e.pointerId)) {
        if (e.pointerType === "mouse") { S.cross = { i: iOfX(e.offsetX), y: e.offsetY }; draw(); }
        return;
      }
      pts.set(e.pointerId, { x: e.offsetX, y: e.offsetY });
      if (pinch && pts.size === 2) { const [p1, p2] = [...pts.values()]; const d = Math.abs(p1.x - p2.x) || 1; S.view.count = pinch.count * (pinch.d / d); moved = true; draw(); }
      else if (drag) { const dx = e.offsetX - drag.x; if (Math.abs(dx) > 4) moved = true; S.view.end = drag.end - dx / (plotW() / S.view.count); if (e.pointerType === "mouse") S.cross = null; draw(); }
    });
    const up = (e) => {
      const wasTap = pts.size === 1 && !moved;
      pts.delete(e.pointerId);
      if (pts.size < 2) pinch = null;
      if (!pts.size) drag = null;
      if (wasTap && e.pointerType !== "mouse") { S.cross = S.cross && Math.abs(S.cross.i - iOfX(e.offsetX)) < 1 ? null : { i: iOfX(e.offsetX), y: e.offsetY }; draw(); }
    };
    cv.addEventListener("pointerup", up);
    cv.addEventListener("pointercancel", up);
    cv.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse" && !pts.size) { S.cross = null; draw(); } });
    cv.addEventListener("wheel", (e) => { e.preventDefault(); S.view.count *= e.deltaY > 0 ? 1.12 : 0.89; draw(); }, { passive: false });
    window.onresize = size;
    size();
  }

  /* ───── 매물대 ───── */
  function renderProfile() {
    const list = visible().filter((s) => s.vs);
    if (!list.length) {
      P.profile.innerHTML = empty("아직 매물대 요약 종목이 없어요.", "과매도 알림 종목 중 거래량 기준을 넘은 종목이 생기면 보여요.");
      return;
    }
    const cl = (v) => Math.min(100, Math.max(0, v));
    P.profile.innerHTML = list.map((s) => {
      const v = s.vs, d = s.src === "US" ? 2 : 0;
      const lo = v.support_price ?? v.poc_low * 0.9, hi = v.resistance_price ?? v.poc_high * 1.1, sp = hi - lo || 1;
      return `<div class="pcard" data-k="${esc(s.key)}"><div class="top"><b>${esc(s.name)} <span class="tag">${esc(s.themes[0])}</span></b><span class="pos">${esc(v.position || "")}</span></div>
        <div class="gauge"><i style="left:${cl((((v.poc_low + v.poc_high) / 2 - lo) / sp) * 100)}%;background:#ffd740;color:#ffd740" data-l="핵심"></i><i style="left:${cl(((s.close - lo) / sp) * 100)}%;background:#fff;color:#fff" data-l="현재가"></i></div>
        <div class="glab"><span class="up">${v.support_price ? "지지 " + num(v.support_price, d) : "지지 없음"}</span><span class="dn">${v.resistance_price ? "저항 " + num(v.resistance_price, d) : "저항 없음"}</span></div>
        <div class="grid2"><span class="k">종가</span><span class="v">${pxStr(s, s.close)}</span><span class="k">핵심 매물대</span><span class="v">${num(v.poc_low, d)} ~ ${num(v.poc_high, d)}</span>
        <span class="k">20일 평균 거래량</span><span class="v">${num(v.avg_volume)}</span><span class="k">오늘 거래량</span><span class="v">${num(v.today_volume)} (${v.volume_ratio ? v.volume_ratio.toFixed(2) + "배" : "-"})</span>
        <span class="k">위 저항까지</span><span class="v dn">${v.resistance_distance_pct != null ? "+" + v.resistance_distance_pct.toFixed(1) + "%" : "-"}</span><span class="k">아래 지지까지</span><span class="v up">${v.support_distance_pct != null ? "-" + Math.abs(v.support_distance_pct).toFixed(1) + "%" : "-"}</span></div></div>`;
    }).join("");
    P.profile.querySelectorAll(".pcard").forEach((el) => el.addEventListener("click", () => { S.sel = el.dataset.k; S.view = null; setTab("chart"); }));
  }

  /* ───── 탭 ───── */
  function setTab(t) {
    S.tab = t;
    $("tabBar").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.tab === t));
    Object.entries(P).forEach(([k, el]) => el.classList.toggle("on", k === t));
    render();
    window.scrollTo(0, 0);
  }
  function render() {
    ({ all: renderAll, alert: renderAlert, chart: renderChart, profile: renderProfile })[S.tab]();
  }
  $("tabBar").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
  $("marketToggle").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      S.market = b.dataset.market;
      $("marketToggle").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
      S.theme = "전체";
      render();
    })
  );

  (async function load() {
    const [all, kr, us] = await Promise.all([getJson("./data/kr_all.json"), getJson("./data/kr_latest.json"), getJson("./data/us_latest.json")]);
    S.raw = { all, kr, us };
    build();
    const ts = [all, kr, us].filter((d) => d && d.generated_at).map((d) => new Date(d.generated_at).getTime());
    $("updatedAt").textContent = ts.length ? "갱신 " + new Date(Math.max(...ts)).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) : "아직 데이터 없음";
    render();
  })();
})();
