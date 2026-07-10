(function () {
  const state = {
    market: "ALL",
    tab: "list",
    data: { KR: null, US: null },
    selected: null, // { source, label }
    charts: { price: null, rsi: null },
  };

  const els = {
    updatedAt: document.getElementById("updatedAt"),
    marketToggle: document.getElementById("marketToggle"),
    tabBar: document.getElementById("tabBar"),
    panels: {
      list: document.getElementById("panel-list"),
      chart: document.getElementById("panel-chart"),
      profile: document.getElementById("panel-profile"),
    },
  };

  function fmtNumber(n, digits) {
    if (n === null || n === undefined || Number.isNaN(n)) return "-";
    return n.toLocaleString("ko-KR", { maximumFractionDigits: digits ?? 0 });
  }

  function fmtPrice(stock) {
    if (stock._source === "US") return `$${fmtNumber(stock.close, 2)}`;
    return `${fmtNumber(stock.close, 0)}원`;
  }

  async function fetchJson(path) {
    try {
      const res = await fetch(`${path}?_=${Date.now()}`);
      if (!res.ok) return null;
      return await res.json();
    } catch (err) {
      return null;
    }
  }

  async function loadData() {
    const [kr, us] = await Promise.all([fetchJson("./data/kr_latest.json"), fetchJson("./data/us_latest.json")]);
    state.data.KR = kr;
    state.data.US = us;

    const times = [kr, us]
      .filter((d) => d && d.generated_at)
      .map((d) => new Date(d.generated_at).getTime());
    if (times.length) {
      const latest = new Date(Math.max(...times));
      els.updatedAt.textContent = `최근 갱신: ${latest.toLocaleString("ko-KR", { hour12: false })}`;
    } else {
      els.updatedAt.textContent = "아직 데이터가 없어요";
    }

    render();
  }

  function allStocks() {
    const list = [];
    if ((state.market === "ALL" || state.market === "KR") && state.data.KR) {
      for (const s of state.data.KR.stocks) list.push({ ...s, _source: "KR" });
    }
    if ((state.market === "ALL" || state.market === "US") && state.data.US) {
      for (const s of state.data.US.stocks) list.push({ ...s, _source: "US" });
    }
    return list;
  }

  function groupByTheme(stocks) {
    const grouped = {};
    for (const s of stocks) {
      grouped[s.theme] = grouped[s.theme] || [];
      grouped[s.theme].push(s);
    }
    return grouped;
  }

  function emptyState(message1, message2) {
    return `<div class="empty-state"><span class="emoji">📭</span><p>${message1}</p><p>${message2 || ""}</p></div>`;
  }

  // ---------- 알림 종목 탭 ----------

  function renderList() {
    const stocks = allStocks();
    if (!stocks.length) {
      els.panels.list.innerHTML = emptyState(
        "아직 알림에 포함된 종목이 없어요.",
        "다음 RSI 과매도 알림이 오면 이곳에 표시됩니다."
      );
      return;
    }

    const grouped = groupByTheme(stocks);
    let html = "";
    for (const [theme, list] of Object.entries(grouped)) {
      html += `<div class="theme-group"><h2>${theme}</h2>`;
      for (const s of list) {
        const oversoldDaily = s.daily_rsi !== null && s.daily_rsi !== undefined && s.daily_rsi <= 30;
        const oversoldWeekly = s.weekly_rsi !== null && s.weekly_rsi !== undefined && s.weekly_rsi <= 30;
        html += `
          <div class="stock-card" data-source="${s._source}" data-label="${s.label}">
            <div class="stock-card-top">
              <div class="stock-name-block">
                <span class="stock-name">${s.name}</span>
                <span class="stock-meta">${s.code} · ${s.market_type || "시장 미확인"}</span>
              </div>
              <span class="stock-price">${fmtPrice(s)}</span>
            </div>
            <div class="rsi-badges">
              <span class="badge ${oversoldDaily ? "oversold" : ""}">일봉 RSI ${fmtNumber(s.daily_rsi, 1)}</span>
              <span class="badge ${oversoldWeekly ? "oversold" : ""}">주봉 RSI ${fmtNumber(s.weekly_rsi, 1)}</span>
              ${s.volume_summary ? '<span class="badge">매물대 요약 있음</span>' : ""}
            </div>
          </div>`;
      }
      html += `</div>`;
    }
    els.panels.list.innerHTML = html;

    els.panels.list.querySelectorAll(".stock-card").forEach((card) => {
      card.addEventListener("click", () => {
        state.selected = { source: card.dataset.source, label: card.dataset.label };
        setTab("chart");
      });
    });
  }

  // ---------- 차트 탭 ----------

  function findStock(source, label) {
    const list = source === "KR" ? state.data.KR && state.data.KR.stocks : state.data.US && state.data.US.stocks;
    return (list || []).find((s) => s.label === label) || null;
  }

  function renderChart() {
    const stocks = allStocks();
    if (!stocks.length) {
      els.panels.chart.innerHTML = emptyState("표시할 차트가 없어요.", "알림에 종목이 포함되면 차트가 나타납니다.");
      return;
    }

    const stillValid =
      state.selected && stocks.some((s) => s._source === state.selected.source && s.label === state.selected.label);
    if (!stillValid) {
      state.selected = { source: stocks[0]._source, label: stocks[0].label };
    }

    const chips = stocks
      .map((s) => {
        const active = s._source === state.selected.source && s.label === state.selected.label;
        return `<button class="chip ${active ? "active" : ""}" data-source="${s._source}" data-label="${s.label}">${s.name}</button>`;
      })
      .join("");

    els.panels.chart.innerHTML = `
      <div class="chip-row">${chips}</div>
      <div class="chart-card">
        <div class="chart-header-price" id="chartHeaderPrice"></div>
        <h3 id="priceChartTitle">가격</h3>
        <canvas id="priceCanvas" height="160"></canvas>
      </div>
      <div class="chart-card">
        <h3>RSI (14)</h3>
        <canvas id="rsiCanvas" height="140"></canvas>
      </div>
    `;

    els.panels.chart.querySelectorAll(".chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        state.selected = { source: chip.dataset.source, label: chip.dataset.label };
        renderChart();
      });
    });

    drawCharts();
  }

  function drawCharts() {
    const stock = findStock(state.selected.source, state.selected.label);
    if (!stock) return;

    const bars = stock.daily_bars || [];
    const labels = bars.map((b) => `${b.date.slice(4, 6)}/${b.date.slice(6, 8)}`);
    const closes = bars.map((b) => b.close);
    const rsis = bars.map((b) => b.rsi);

    const priceTitle = document.getElementById("priceChartTitle");
    if (priceTitle) priceTitle.textContent = `가격 (최근 ${bars.length}거래일)`;

    const first = closes.length ? closes[0] : null;
    const last = closes.length ? closes[closes.length - 1] : null;
    const changePct = first ? (((last - first) / first) * 100).toFixed(2) : "0.00";
    const isUp = first !== null && last >= first;

    const priceHeader = document.getElementById("chartHeaderPrice");
    if (priceHeader) {
      priceHeader.innerHTML = `
        <span class="big">${fmtPrice(stock)}</span>
        <span class="delta ${isUp ? "up-text" : "down-text"}">${isUp ? "+" : ""}${changePct}%</span>
      `;
    }

    if (state.charts.price) state.charts.price.destroy();
    if (state.charts.rsi) state.charts.rsi.destroy();

    const upColor = "#f04452";
    const downColor = "#3b82f6";
    const lineColor = isUp ? upColor : downColor;

    state.charts.price = new Chart(document.getElementById("priceCanvas"), {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            data: closes,
            borderColor: lineColor,
            backgroundColor: "transparent",
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.15,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { maxTicksLimit: 6, color: "#8b95a1", font: { size: 10 } }, grid: { display: false } },
          y: { ticks: { color: "#8b95a1", font: { size: 10 } }, grid: { color: "#f2f4f6" } },
        },
      },
    });

    state.charts.rsi = new Chart(document.getElementById("rsiCanvas"), {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "RSI",
            data: rsis,
            borderColor: "#3182f6",
            backgroundColor: "transparent",
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.15,
            spanGaps: true,
          },
          {
            label: "과매도(30)",
            data: labels.map(() => 30),
            borderColor: "#f04452",
            borderDash: [4, 4],
            borderWidth: 1,
            pointRadius: 0,
          },
          {
            label: "과매수(70)",
            data: labels.map(() => 70),
            borderColor: "#8b95a1",
            borderDash: [4, 4],
            borderWidth: 1,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { maxTicksLimit: 6, color: "#8b95a1", font: { size: 10 } }, grid: { display: false } },
          y: {
            min: 0,
            max: 100,
            ticks: { stepSize: 25, color: "#8b95a1", font: { size: 10 } },
            grid: { color: "#f2f4f6" },
          },
        },
      },
    });
  }

  // ---------- 매물대 요약 탭 ----------

  function renderProfile() {
    const stocks = allStocks().filter((s) => s.volume_summary);
    if (!stocks.length) {
      els.panels.profile.innerHTML = emptyState(
        "아직 매물대 요약 대상 종목이 없어요.",
        "20일 평균 거래량 기준을 통과한 종목이 있으면 표시됩니다."
      );
      return;
    }

    const grouped = groupByTheme(stocks);
    let html = "";
    for (const [theme, list] of Object.entries(grouped)) {
      html += `<div class="theme-group"><h2>${theme}</h2>`;
      for (const s of list) {
        const vs = s.volume_summary;
        const low = vs.support_price !== null && vs.support_price !== undefined ? vs.support_price : vs.poc_low * 0.9;
        const high =
          vs.resistance_price !== null && vs.resistance_price !== undefined ? vs.resistance_price : vs.poc_high * 1.1;
        const span = high - low || 1;
        const clamp = (v) => Math.min(100, Math.max(0, v));
        const pricePct = clamp(((s.close - low) / span) * 100);
        const pocPct = clamp((((vs.poc_low + vs.poc_high) / 2 - low) / span) * 100);

        html += `
          <div class="profile-card">
            <div class="profile-card-top">
              <span class="profile-name">${s.name}</span>
              <span class="profile-position">${vs.position}</span>
            </div>
            <div class="gauge">
              <div class="gauge-marker" style="left:${pocPct}%; background:#3182F6;" data-label="POC"></div>
              <div class="gauge-marker" style="left:${pricePct}%;" data-label="현재가"></div>
            </div>
            <div class="gauge-labels">
              <span>${vs.support_price ? "지지 " + fmtNumber(vs.support_price, 2) : "지지 없음"}</span>
              <span>${vs.resistance_price ? "저항 " + fmtNumber(vs.resistance_price, 2) : "저항 없음"}</span>
            </div>
            <div class="profile-grid">
              <div class="item"><span class="label">종가</span><span class="value">${fmtPrice(s)}</span></div>
              <div class="item"><span class="label">핵심 매물대</span><span class="value">${fmtNumber(vs.poc_low, 2)} ~ ${fmtNumber(vs.poc_high, 2)}</span></div>
              <div class="item"><span class="label">20일 평균 거래량</span><span class="value">${fmtNumber(vs.avg_volume)}</span></div>
              <div class="item"><span class="label">당일 거래량</span><span class="value">${fmtNumber(vs.today_volume)}</span></div>
              <div class="item"><span class="label">평균 대비</span><span class="value">${vs.volume_ratio ? vs.volume_ratio.toFixed(2) + "배" : "-"}</span></div>
              <div class="item"><span class="label">상단 저항 거리</span><span class="value">${vs.resistance_distance_pct ? "+" + vs.resistance_distance_pct.toFixed(1) + "%" : "-"}</span></div>
            </div>
          </div>`;
      }
      html += `</div>`;
    }
    els.panels.profile.innerHTML = html;
  }

  // ---------- 탭 / 시장 토글 ----------

  function setTab(tab) {
    state.tab = tab;
    els.tabBar.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === tab);
    });
    Object.entries(els.panels).forEach(([key, panel]) => {
      panel.classList.toggle("active", key === tab);
    });
    render();
  }

  function setMarket(market) {
    state.market = market;
    els.marketToggle.querySelectorAll(".pill-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.market === market);
    });
    render();
  }

  function render() {
    if (state.tab === "list") renderList();
    if (state.tab === "chart") renderChart();
    if (state.tab === "profile") renderProfile();
  }

  els.tabBar.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => setTab(btn.dataset.tab));
  });
  els.marketToggle.querySelectorAll(".pill-btn").forEach((btn) => {
    btn.addEventListener("click", () => setMarket(btn.dataset.market));
  });

  loadData();
})();
