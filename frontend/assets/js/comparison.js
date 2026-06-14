(() => {
  const state = {
    data: null,
    charts: [],
    method: "thiessen",
    requestToken: 0,
    mapRenderToken: 0,
    mapResizeObserver: null,
    tablePages: {
      observed: 1,
      trend: 1
    }
  };

  const monthNames = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
  ];
  const faNumber = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 2 });
  const zeroTolerance = 0.005;
  const comparisonPageSize = 7;
  const MAP_MAX_ZOOM = 14;
  const BASEMAP_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
  const BASEMAP_ATTRIBUTION =
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

  function escapeHtml(value) {
    const element = document.createElement("div");
    element.textContent = String(value ?? "");
    return element.innerHTML;
  }

  function persianDate(year, month) {
    const value = `${monthNames[month - 1]} ${year}`;
    return value.replace(/\d/g, digit => "۰۱۲۳۴۵۶۷۸۹"[Number(digit)]);
  }

  function formatSigned(value, suffix = "") {
    if (value === null || value === undefined || !Number.isFinite(value)) return "بدون داده";
    const sign = value > 0 ? "+" : value < 0 ? "−" : "";
    return `${sign}${faNumber.format(Math.abs(value))}${suffix}`;
  }

  function formatNumber(value, suffix = "") {
    if (value === null || value === undefined || !Number.isFinite(value)) return "بدون داده";
    return `${faNumber.format(value)}${suffix}`;
  }

  function quantile(sortedValues, probability) {
    if (!sortedValues.length) return null;
    const position = (sortedValues.length - 1) * probability;
    const lower = Math.floor(position);
    const upper = Math.ceil(position);
    if (lower === upper) return sortedValues[lower];
    const ratio = position - lower;
    return sortedValues[lower] * (1 - ratio) + sortedValues[upper] * ratio;
  }

  function classPieces(values) {
    const finiteValues = values.filter(Number.isFinite);
    const negativeValues = finiteValues
      .filter(value => value < -zeroTolerance)
      .sort((first, second) => first - second);
    const positiveValues = finiteValues
      .filter(value => value > zeroTolerance)
      .sort((first, second) => first - second);
    const negativeThreshold = negativeValues.length
      ? quantile(negativeValues, 0.5)
      : -zeroTolerance;
    const positiveThresholds = positiveValues.length
      ? [0.2, 0.4, 0.6, 0.8].map(probability => quantile(positiveValues, probability))
      : [zeroTolerance, zeroTolerance, zeroTolerance, zeroTolerance];

    return [
      { max: negativeThreshold, label: "افزایش زیاد", color: "#1D4ED8" },
      { gt: negativeThreshold, max: -zeroTolerance, label: "افزایش کم", color: "#93C5FD" },
      { gt: -zeroTolerance, lte: zeroTolerance, label: "بدون تغییر", color: "#FFFFFF" },
      { gt: zeroTolerance, lte: positiveThresholds[0], label: "افت خیلی کم", color: "#FEE2E2" },
      { gt: positiveThresholds[0], lte: positiveThresholds[1], label: "افت کم", color: "#FCA5A5" },
      { gt: positiveThresholds[1], lte: positiveThresholds[2], label: "افت متوسط", color: "#F87171" },
      { gt: positiveThresholds[2], lte: positiveThresholds[3], label: "افت زیاد", color: "#EF4444" },
      { gt: positiveThresholds[3], label: "افت خیلی زیاد", color: "#B91C1C" }
    ];
  }

  function pieceForValue(pieces, value) {
    if (!Number.isFinite(value)) return null;
    return pieces.find(piece => (
      (piece.gt === undefined || value > piece.gt)
      && (piece.lte === undefined || value <= piece.lte)
      && (piece.max === undefined || value <= piece.max)
    )) || pieces.at(-1);
  }

  function pieceRange(piece) {
    if (piece.label === "بدون تغییر") return "۰";
    if (piece.gt === undefined) return `تا ${formatSigned(piece.max)}`;
    if (piece.lte === undefined && piece.max === undefined) {
      return `بیش از ${formatSigned(piece.gt)}`;
    }
    const maximum = piece.lte ?? piece.max;
    if (piece.gt <= -zeroTolerance && maximum >= -zeroTolerance) {
      return `${formatSigned(piece.gt)} تا ۰`;
    }
    return `${formatSigned(piece.gt)} تا ${formatSigned(maximum)}`;
  }

  function renderLegend(elementId, pieces) {
    document.getElementById(elementId).innerHTML = [
      ...pieces.map(piece => `
        <span class="inline-flex items-center gap-1.5 rounded-md bg-white px-2 py-1 text-slate-600 shadow-sm ring-1 ring-slate-100">
          <i class="h-2.5 w-2.5 rounded-sm ring-1 ring-slate-200" style="background:${piece.color}"></i>
          ${piece.label} <b dir="ltr">${pieceRange(piece)}</b>
        </span>
      `),
      `<span class="inline-flex items-center gap-1.5 rounded-md bg-white px-2 py-1 text-slate-600 shadow-sm ring-1 ring-slate-100">
        <i class="h-2.5 w-2.5 rounded-sm bg-slate-300"></i> بدون داده
      </span>`
    ].join("");
  }

  function dateIndex(year, month, monthsPerYear) {
    return year * monthsPerYear + month;
  }

  function renderYearOptions(select, minimumYear, maximumYear, selectedYear) {
    select.innerHTML = Array.from(
      { length: maximumYear - minimumYear + 1 },
      (_, index) => minimumYear + index
    ).map(year => `<option value="${year}">${year}</option>`).join("");
    select.value = String(selectedYear);
  }

  function renderMonthOptions(prefix) {
    if (!state.data) return;
    const filters = state.data.filters;
    const yearSelect = document.getElementById(`comparison${prefix}Year`);
    const monthSelect = document.getElementById(`comparison${prefix}Month`);
    const year = Number(yearSelect.value);
    const selected = Number(monthSelect.value)
      || filters[`${prefix.toLowerCase()}_month`];
    const minimum = year === filters.minimum_year ? filters.minimum_month : 1;
    const maximum = year === filters.maximum_year
      ? filters.maximum_month
      : state.data.calendar.months_per_year;
    monthSelect.innerHTML = Array.from(
      { length: maximum - minimum + 1 },
      (_, index) => minimum + index
    ).map(month => `<option value="${month}">${monthNames[month - 1]}</option>`).join("");
    monthSelect.value = String(Math.min(maximum, Math.max(minimum, selected)));
  }

  function renderFilterControls(data) {
    const filters = data.filters;
    renderYearOptions(
      document.getElementById("comparisonStartYear"),
      filters.minimum_year,
      filters.maximum_year,
      filters.start_year
    );
    renderYearOptions(
      document.getElementById("comparisonEndYear"),
      filters.minimum_year,
      filters.maximum_year,
      filters.end_year
    );
    renderMonthOptions("Start");
    renderMonthOptions("End");
    document.getElementById("comparisonStartMonth").value = String(filters.start_month);
    document.getElementById("comparisonEndMonth").value = String(filters.end_month);
  }

  function geometryOuterRings(geometry) {
    if (geometry.type === "Polygon") return [geometry.coordinates[0]];
    if (geometry.type === "MultiPolygon") {
      return geometry.coordinates.map(polygon => polygon[0]);
    }
    return [];
  }

  function geometryBounds(geometry) {
    const bounds = [Infinity, Infinity, -Infinity, -Infinity];
    const visit = coordinates => {
      if (typeof coordinates[0] === "number") {
        bounds[0] = Math.min(bounds[0], coordinates[0]);
        bounds[1] = Math.min(bounds[1], coordinates[1]);
        bounds[2] = Math.max(bounds[2], coordinates[0]);
        bounds[3] = Math.max(bounds[3], coordinates[1]);
        return;
      }
      coordinates.forEach(visit);
    };
    visit(geometry.coordinates);
    return bounds;
  }

  function comparisonBounds(data) {
    return data.aquifers.reduce(
      (bounds, aquifer) => {
        const current = geometryBounds(aquifer.geometry);
        return [
          Math.min(bounds[0], current[0]),
          Math.min(bounds[1], current[1]),
          Math.max(bounds[2], current[2]),
          Math.max(bounds[3], current[3])
        ];
      },
      [Infinity, Infinity, -Infinity, -Infinity]
    );
  }

  function configureComparisonLeaflet(chart) {
    const component = chart.getModel().getComponent("lmap");
    const map = component?.getLeaflet();
    if (!map || map._hydroComparisonConfigured) return;
    map._hydroComparisonConfigured = true;
    map._hydroBaseMap = L.tileLayer(BASEMAP_URL, {
      attribution: BASEMAP_ATTRIBUTION,
      maxNativeZoom: 19,
      maxZoom: 19,
      crossOrigin: true
    }).addTo(map);
    map.setMaxZoom(MAP_MAX_ZOOM);
  }

  function fitComparisonLeaflet(chart, data) {
    const component = chart.getModel().getComponent("lmap");
    const map = component?.getLeaflet();
    if (!map) return;
    const [minimumX, minimumY, maximumX, maximumY] = comparisonBounds(data);
    map.invalidateSize({ animate: false, pan: false });
    map.fitBounds(
      L.latLngBounds([minimumY, minimumX], [maximumY, maximumX]),
      {
        paddingTopLeft: [32, 32],
        paddingBottomRight: [32, 32],
        maxZoom: MAP_MAX_ZOOM,
        animate: false
      }
    );
  }

  function mapOption(data, metric, pieces, unit) {
    const methodLabel = state.method === "thiessen"
      ? "میانگین وزنی تیسن"
      : "میانگین حسابی";
    const seriesData = data.aquifers.map(aquifer => {
      const value = aquifer.methods[state.method][metric];
      const piece = pieceForValue(pieces, value);
      const [minimumX, minimumY, maximumX, maximumY] = geometryBounds(aquifer.geometry);
      return {
        name: aquifer.id,
        value: [
          (minimumX + maximumX) / 2,
          (minimumY + maximumY) / 2,
          value
        ],
        aquifer,
        color: piece?.color || "#CBD5E1",
        rings: geometryOuterRings(aquifer.geometry)
      };
    });
    const [minimumX, minimumY, maximumX, maximumY] = comparisonBounds(data);
    return {
      animationDurationUpdate: 350,
      textStyle: { fontFamily: "Vazirmatn" },
      lmap: {
        center: [(minimumX + maximumX) / 2, (minimumY + maximumY) / 2],
        zoom: 6,
        maxZoom: MAP_MAX_ZOOM,
        zoomSnap: 0.25,
        zoomDelta: 0.5,
        attributionControl: true,
        resizeEnable: true,
        renderOnMoving: true,
        echartsLayerInteractive: true
      },
      tooltip: {
        trigger: "item",
        confine: true,
        textStyle: { fontFamily: "Vazirmatn", fontSize: 11 },
        formatter: parameters => {
          const aquifer = parameters.data?.aquifer;
          if (!aquifer) return "";
          const method = aquifer.methods[state.method];
          const value = method[metric];
          const metricLabel = metric === "observed_decline"
            ? "افت ابتدا تا انتهای بازه"
            : "نرخ افت روندی";
          return `
            <div dir="rtl" class="text-right">
              <strong>${escapeHtml(aquifer.aquifer)}</strong>
              <div class="mt-1 text-slate-500">محدوده ${escapeHtml(aquifer.mahdoude)}</div>
              <div class="mt-2">${metricLabel}: <b dir="ltr">${formatSigned(value, unit)}</b></div>
              <div>روش: ${methodLabel}</div>
              <div>چاه واجد پوشش: ${faNumber.format(aquifer.selected_wells)} از ${faNumber.format(aquifer.total_wells)}</div>
              <div>تراز ابتدا / انتها: <b dir="ltr">${formatNumber(method.start_level)} / ${formatNumber(method.end_level)}</b></div>
            </div>
          `;
        }
      },
      series: [{
        type: "custom",
        coordinateSystem: "lmap",
        clip: false,
        data: seriesData,
        encode: { lng: 0, lat: 1, tooltip: 2 },
        renderItem: (parameters, api) => {
          const item = seriesData[parameters.dataIndex];
          if (!item) return null;
          const children = item.rings.map(ring => ({
            type: "polygon",
            shape: { points: ring.map(coordinate => api.coord(coordinate)) },
            style: {
              fill: item.color,
              stroke: "#FFFFFF",
              lineWidth: 0.9,
              opacity: 0.78
            },
            emphasis: {
              style: {
                fill: "#F3E9D2",
                stroke: "#11395B",
                lineWidth: 1.5,
                opacity: 0.94
              }
            }
          }));
          const center = api.coord(item.value.slice(0, 2));
          children.push({
            type: "text",
            silent: true,
            style: {
              x: center[0],
              y: center[1],
              text: `${item.aquifer.aquifer}\n${formatSigned(item.value[2])}`,
              textAlign: "center",
              textVerticalAlign: "middle",
              font: "8px Vazirmatn",
              lineHeight: 12,
              fill: "#172A3A",
              backgroundColor: "rgba(255,255,255,0.66)",
              padding: [2, 3],
              borderRadius: 3
            }
          });
          return {
            type: "group",
            children
          }
        }
      }]
    };
  }

  function metricValues(data, metric) {
    return data.aquifers
      .map(aquifer => aquifer.methods[state.method][metric])
      .filter(Number.isFinite);
  }

  function observeMapContainers() {
    if (state.mapResizeObserver || !("ResizeObserver" in window)) return;
    const containers = [
      document.getElementById("observedComparisonMap"),
      document.getElementById("trendComparisonMap")
    ];
    state.mapResizeObserver = new ResizeObserver(entries => {
      entries.forEach(entry => {
        if (entry.contentRect.width <= 0 || entry.contentRect.height <= 0) return;
        const chart = echarts.getInstanceByDom(entry.target);
        chart?.resize({
          width: entry.contentRect.width,
          height: entry.contentRect.height
        });
      });
    });
    containers.forEach(container => state.mapResizeObserver.observe(container));
  }

  function renderStats(data) {
    const available = data.stats.available_aquifers[state.method];
    const selectedWells = data.aquifers.reduce(
      (total, aquifer) => total + aquifer.selected_wells,
      0
    );
    const methodLabel = state.method === "thiessen"
      ? "میانگین وزنی تیسن"
      : "میانگین حسابی";
    const cards = [
      ["آبخوان‌های بررسی‌شده", faNumber.format(data.stats.aquifer_count), "کل پلیگون‌های منطبق با داده ورودی"],
      ["چاه‌های واجد پوشش", faNumber.format(selectedWells), "پوشش‌دهنده ابتدا تا انتهای بازه"],
      ["افت مشاهده‌شده معتبر", faNumber.format(available.observed_decline), "آبخوان دارای مقدار دقیق ابتدا و انتها"],
      ["روش فعال", methodLabel, `${faNumber.format(available.trend_decline_per_year)} آبخوان دارای روند معتبر`]
    ];
    document.getElementById("comparisonStats").innerHTML = cards.map(([label, value, note]) => `
      <article class="stat-card">
        <div class="text-[10px] font-bold text-teal">${label}</div>
        <div class="mt-3 text-2xl font-bold text-navy">${value}</div>
        <div class="mt-2 text-[10px] leading-5 text-slate-400">${note}</div>
      </article>
    `).join("");
  }

  function rankedAquifers(data, metric) {
    return [...data.aquifers].sort((first, second) => {
      const firstValue = first.methods[state.method][metric];
      const secondValue = second.methods[state.method][metric];
      const firstValid = Number.isFinite(firstValue);
      const secondValid = Number.isFinite(secondValue);
      if (firstValid && secondValid && secondValue !== firstValue) {
        return secondValue - firstValue;
      }
      if (firstValid !== secondValid) return firstValid ? -1 : 1;
      return first.aquifer.localeCompare(second.aquifer, "fa");
    });
  }

  function paginationButtons(key, pageCount, currentPage) {
    return Array.from(
      { length: pageCount },
      (_, index) => index + 1
    ).map(page => `
      <button
        type="button"
        class="comparison-page-button${page === currentPage ? " is-active" : ""}"
        data-comparison-page="${key}"
        data-page="${page}"
        aria-label="صفحه ${page}"
        ${page === currentPage ? 'aria-current="page"' : ""}
      >${faNumber.format(page)}</button>
    `).join("");
  }

  function renderComparisonTable(data, key, metric, unit) {
    const rows = rankedAquifers(data, metric);
    const pageCount = Math.max(1, Math.ceil(rows.length / comparisonPageSize));
    const currentPage = Math.min(state.tablePages[key], pageCount);
    state.tablePages[key] = currentPage;
    const start = (currentPage - 1) * comparisonPageSize;
    const pageRows = rows.slice(start, start + comparisonPageSize);
    const validBeforePage = rows
      .slice(0, start)
      .filter(aquifer => Number.isFinite(aquifer.methods[state.method][metric]))
      .length;
    let validRank = validBeforePage;
    const body = pageRows.map(aquifer => {
      const method = aquifer.methods[state.method];
      const value = method[metric];
      const hasValue = Number.isFinite(value);
      if (hasValue) validRank += 1;
      const valueClass = hasValue
        ? value > zeroTolerance
          ? "metric-positive"
          : value < -zeroTolerance
            ? "metric-negative"
            : "font-bold text-slate-500"
        : "text-slate-300";
      return `
        <tr>
          <td class="text-center font-bold text-navy">${hasValue ? faNumber.format(validRank) : "—"}</td>
          <td>
            <strong class="block text-navy">${escapeHtml(aquifer.aquifer)}</strong>
            <span class="mt-1 block text-[9px] text-slate-400">${escapeHtml(aquifer.mahdoude)}</span>
          </td>
          <td class="text-center">${faNumber.format(aquifer.selected_wells)} از ${faNumber.format(aquifer.total_wells)}</td>
          <td dir="ltr" class="text-center">${formatNumber(method.start_level)}</td>
          <td dir="ltr" class="text-center">${formatNumber(method.end_level)}</td>
          <td dir="ltr" class="text-center ${valueClass}">${hasValue ? formatSigned(value, unit) : "بدون داده"}</td>
        </tr>
      `;
    }).join("");
    const firstVisible = rows.length ? start + 1 : 0;
    const lastVisible = Math.min(start + comparisonPageSize, rows.length);
    document.getElementById(`${key}ComparisonTable`).innerHTML = `
      <div class="table-scroll flex-1">
        <table class="data-table">
          <thead>
            <tr>
              <th class="text-center">رتبه</th>
              <th>آبخوان / محدوده</th>
              <th class="text-center">چاه واجد پوشش</th>
              <th class="text-center">تراز ابتدا</th>
              <th class="text-center">تراز انتها</th>
              <th class="text-center">${metric === "observed_decline" ? "افت بازه" : "نرخ افت روندی"}</th>
            </tr>
          </thead>
          <tbody>${body}</tbody>
        </table>
      </div>
      <div class="comparison-pagination">
        <div class="text-[10px] text-slate-500">
          نمایش ${faNumber.format(firstVisible)} تا ${faNumber.format(lastVisible)} از ${faNumber.format(rows.length)} آبخوان
        </div>
        <div class="flex flex-wrap items-center justify-center gap-1.5">
          <button type="button" class="comparison-page-button px-3" data-comparison-page="${key}" data-page="${currentPage - 1}" ${currentPage === 1 ? "disabled" : ""}>قبلی</button>
          ${paginationButtons(key, pageCount, currentPage)}
          <button type="button" class="comparison-page-button px-3" data-comparison-page="${key}" data-page="${currentPage + 1}" ${currentPage === pageCount ? "disabled" : ""}>بعدی</button>
        </div>
      </div>
    `;
  }

  function renderComparisonTables(data) {
    renderComparisonTable(data, "observed", "observed_decline", " متر");
    renderComparisonTable(data, "trend", "trend_decline_per_year", " متر/سال");
  }

  function renderMaps(data) {
    const observedValues = metricValues(data, "observed_decline");
    const trendValues = metricValues(data, "trend_decline_per_year");
    const observedPieces = classPieces(observedValues);
    const trendPieces = classPieces(trendValues);
    renderLegend("observedClassLegend", observedPieces);
    renderLegend("trendClassLegend", trendPieces);

    const methodLabel = state.method === "thiessen" ? "تیسن" : "حسابی";
    document.getElementById("observedMapSummary").textContent =
      `${faNumber.format(observedValues.length)} آبخوان دارای مقدار معتبر · روش ${methodLabel} · واحد متر`;
    document.getElementById("trendMapSummary").textContent =
      `${faNumber.format(trendValues.length)} آبخوان دارای روند معتبر · روش ${methodLabel} · واحد متر بر سال`;

    if (!state.charts.length) {
      const observedElement = document.getElementById("observedComparisonMap");
      const trendElement = document.getElementById("trendComparisonMap");
      if (
        observedElement.clientWidth <= 0
        || observedElement.clientHeight <= 0
        || trendElement.clientWidth <= 0
        || trendElement.clientHeight <= 0
      ) {
        return false;
      }
      const observed = echarts.init(observedElement);
      const trend = echarts.init(trendElement);
      observed.group = "comparison-maps";
      trend.group = "comparison-maps";
      echarts.connect("comparison-maps");
      state.charts = [observed, trend];
      observeMapContainers();
    }
    state.charts[0].setOption(
      mapOption(data, "observed_decline", observedPieces, " متر"),
      { replaceMerge: ["series"] }
    );
    state.charts[1].setOption(
      mapOption(data, "trend_decline_per_year", trendPieces, " متر/سال"),
      { replaceMerge: ["series"] }
    );
    configureComparisonLeaflet(state.charts[0]);
    configureComparisonLeaflet(state.charts[1]);
    return true;
  }

  function renderMapsWhenReady(data, renderToken, attempt = 0) {
    if (renderToken !== state.mapRenderToken) return;
    if (renderMaps(data)) {
      state.charts.forEach(chart => chart.resize());
      window.requestAnimationFrame(() => {
        if (renderToken !== state.mapRenderToken) return;
        state.charts.forEach(chart => chart.resize());
        window.requestAnimationFrame(() => {
          if (renderToken !== state.mapRenderToken) return;
          state.charts.forEach(chart => fitComparisonLeaflet(chart, data));
        });
      });
      return;
    }
    if (attempt >= 30) {
      console.error("Comparison map containers did not receive a visible size.");
      return;
    }
    window.requestAnimationFrame(() => {
      renderMapsWhenReady(data, renderToken, attempt + 1);
    });
  }

  function renderComparison(data) {
    state.data = data;
    renderFilterControls(data);
    renderStats(data);
    state.tablePages.observed = 1;
    state.tablePages.trend = 1;
    renderComparisonTables(data);
    document.getElementById("comparisonPeriodBadge").textContent =
      `${persianDate(data.filters.start_year, data.filters.start_month)} تا ${persianDate(data.filters.end_year, data.filters.end_month)}`;
    document.getElementById("comparisonLoading").classList.add("hidden");
    document.getElementById("comparisonMaps").classList.remove("hidden");
    const renderToken = ++state.mapRenderToken;
    window.requestAnimationFrame(() => {
      renderMapsWhenReady(data, renderToken);
    });
  }

  async function loadComparison(filters = null) {
    const token = ++state.requestToken;
    const button = document.getElementById("applyComparisonFilters");
    button.disabled = true;
    button.textContent = "در حال محاسبه...";
    document.getElementById("comparisonLoading").classList.remove("hidden");
    try {
      const params = new URLSearchParams();
      if (filters) {
        params.set("start_year", filters.startYear);
        params.set("start_month", filters.startMonth);
        params.set("end_year", filters.endYear);
        params.set("end_month", filters.endMonth);
      }
      const query = params.toString() ? `?${params}` : "";
      const response = await fetch(`/api/comparison${query}`);
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "دریافت اطلاعات مقایسه ناموفق بود.");
      }
      const data = await response.json();
      if (token !== state.requestToken) return;
      renderComparison(data);
    } catch (error) {
      console.error("Comparison rendering failed:", error);
      document.getElementById("comparisonLoading").innerHTML = `
        <div class="text-center">
          <div class="text-sm font-bold text-coral">نمایش مقایسه ممکن نشد</div>
          <div class="mt-2 text-xs text-slate-500">${escapeHtml(error.message)}</div>
        </div>
      `;
    } finally {
      button.disabled = false;
      button.innerHTML = "<span>به‌روزرسانی مقایسه</span><span aria-hidden=\"true\">←</span>";
    }
  }

  function initialize() {
    document.getElementById("comparisonStartYear").addEventListener(
      "change",
      () => renderMonthOptions("Start")
    );
    document.getElementById("comparisonEndYear").addEventListener(
      "change",
      () => renderMonthOptions("End")
    );
    document.getElementById("comparisonMethod").addEventListener("change", event => {
      state.method = event.target.checked ? "thiessen" : "arithmetic";
      document.getElementById("comparisonMethodTitle").textContent =
        state.method === "thiessen" ? "میانگین وزنی تیسن" : "میانگین حسابی";
      if (state.data) {
        state.tablePages.observed = 1;
        state.tablePages.trend = 1;
        renderStats(state.data);
        renderComparisonTables(state.data);
        renderMaps(state.data);
      }
    });
    document.getElementById("comparisonMaps").addEventListener("click", event => {
      const tab = event.target.closest("[data-comparison-tab]");
      if (tab) {
        const key = tab.dataset.comparisonTab;
        const view = tab.dataset.view;
        document.querySelectorAll(`[data-comparison-tab="${key}"]`).forEach(button => {
          button.classList.toggle("is-active", button === tab);
        });
        document.querySelectorAll(`[data-comparison-panel^="${key}-"]`).forEach(panel => {
          panel.classList.toggle(
            "hidden",
            panel.dataset.comparisonPanel !== `${key}-${view}`
          );
        });
        if (view === "map") {
          const chartIndex = key === "observed" ? 0 : 1;
          window.requestAnimationFrame(() => state.charts[chartIndex]?.resize());
        }
        return;
      }
      const pageButton = event.target.closest("[data-comparison-page]");
      if (!pageButton || pageButton.disabled || !state.data) return;
      const key = pageButton.dataset.comparisonPage;
      state.tablePages[key] = Number(pageButton.dataset.page);
      renderComparisonTable(
        state.data,
        key,
        key === "observed" ? "observed_decline" : "trend_decline_per_year",
        key === "observed" ? " متر" : " متر/سال"
      );
    });
    document.getElementById("comparisonFilters").addEventListener("submit", event => {
      event.preventDefault();
      const filters = {
        startYear: Number(document.getElementById("comparisonStartYear").value),
        startMonth: Number(document.getElementById("comparisonStartMonth").value),
        endYear: Number(document.getElementById("comparisonEndYear").value),
        endMonth: Number(document.getElementById("comparisonEndMonth").value)
      };
      const monthsPerYear = state.data?.calendar.months_per_year || monthNames.length;
      if (
        dateIndex(filters.startYear, filters.startMonth, monthsPerYear)
        > dateIndex(filters.endYear, filters.endMonth, monthsPerYear)
      ) {
        window.alert("تاریخ شروع باید قبل از تاریخ پایان باشد.");
        return;
      }
      loadComparison(filters);
    });
    window.addEventListener("resize", () => {
      state.charts.forEach(chart => chart.resize());
    });
    loadComparison();
  }

  document.addEventListener("DOMContentLoaded", initialize);
})();
