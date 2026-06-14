(() => {
  const state = {
    charts: [],
    map: null,
    mapWellLayers: null,
    selectionMap: null,
    selectedAquiferLayer: null,
    spatialData: null,
    spatialMonthIndex: 0,
    spatialTimer: null,
    spatialCharts: null,
    spatialContourSeriesIds: [],
    contourIntervalInitialized: false,
    spatialViewInitialized: false,
    modalChart: null,
    precipitationModalChart: null,
    aquiferNdviChart: null,
    aquiferAetChart: null,
    observer: null,
    requestToken: 0,
    currentData: null
  };

  const faNumber = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 2 });
  const LEAFLET_MAX_ZOOM = 14;
  const SELECTION_MAP_MAX_ZOOM = 12;
  const BASEMAP_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
  const BASEMAP_ATTRIBUTION =
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  const monthNames = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
  ];

  function setSelectedAquifer(id, label) {
    const input = document.getElementById("selectedAquiferId");
    const badge = document.getElementById("selectedAquiferBadge");
    const button = document.getElementById("showDashboardButton");
    if (!input || !button) return;
    input.value = id || "";
    button.disabled = !id;
    if (badge) {
      badge.textContent = id ? label : "هنوز آبخوانی انتخاب نشده است";
      badge.classList.toggle("is-selected", Boolean(id));
    }
  }

  function activeSelectionTab() {
    return document.querySelector(".selection-tab-button.is-active")?.dataset.selectionTab;
  }

  function syncDropdownSelection() {
    const select = document.getElementById("aquiferSelect");
    if (!select?.value) return;
    const label = select.options[select.selectedIndex]?.textContent || "آبخوان انتخاب‌شده";
    setSelectedAquifer(select.value, label);
  }

  function aquiferLayerStyle(selected = false) {
    return selected
      ? {
          color: "#E76F51",
          weight: 4,
          opacity: 1,
          fillColor: "#E76F51",
          fillOpacity: 0.42
        }
      : {
          color: "#087E8B",
          weight: 1.4,
          opacity: 0.85,
          fillColor: "#54C6C4",
          fillOpacity: 0.14
        };
  }

  function fitLeafletBoundsAndLockZoom(map, bounds, padding) {
    if (!bounds?.isValid()) return;
    map._dataFitBounds = bounds;
    map._dataFitPadding = padding;
    map.fitBounds(bounds, { padding, animate: false });
    map.setMinZoom(map.getZoom());
  }

  function addBaseMap(map) {
    if (map._hydroBaseMap) return map._hydroBaseMap;
    map._hydroBaseMap = L.tileLayer(BASEMAP_URL, {
      attribution: BASEMAP_ATTRIBUTION,
      maxNativeZoom: 19,
      maxZoom: 19,
      crossOrigin: true
    }).addTo(map);
    return map._hydroBaseMap;
  }

  function refreshLeafletMinimumZoom(map) {
    if (!map?._dataFitBounds) return;
    const [horizontal, vertical] = map._dataFitPadding || [0, 0];
    const minimumZoom = map.getBoundsZoom(
      map._dataFitBounds,
      false,
      L.point(horizontal * 2, vertical * 2)
    );
    map.setMinZoom(minimumZoom);
  }

  async function initializeAquiferSelection() {
    const mapElement = document.getElementById("aquiferSelectionMap");
    if (!mapElement || state.selectionMap) return;
    const map = L.map(mapElement, {
      zoomControl: true,
      attributionControl: true,
      preferCanvas: true,
      zoomSnap: 0.25,
      zoomDelta: 0.5,
      maxZoom: SELECTION_MAP_MAX_ZOOM
    });
    state.selectionMap = map;
    addBaseMap(map);

    try {
      const response = await fetch("/api/navigation-map");
      if (!response.ok) throw new Error("دریافت مرز آبخوان‌ها ناموفق بود.");
      const data = await response.json();
      const mahdoudeLayer = L.geoJSON(data.mahdoudes, {
        interactive: false,
        style: {
          color: "#11395B",
          weight: 1.5,
          opacity: 0.55,
          fillColor: "#11395B",
          fillOpacity: 0.035,
          dashArray: "7 6"
        }
      }).addTo(map);
      const aquiferLayer = L.geoJSON(data.aquifers, {
        style: () => aquiferLayerStyle(false),
        onEachFeature: (feature, layer) => {
          const properties = feature.properties;
          layer.bindTooltip(
            `<div dir="rtl"><strong>${escapeHtml(properties.aquifer)}</strong><br><span>${escapeHtml(properties.mahdoude)} · ${faNumber.format(properties.well_count)} چاه</span></div>`,
            { sticky: true, direction: "top" }
          );
          layer.on({
            mouseover: () => {
              if (layer !== state.selectedAquiferLayer) {
                layer.setStyle({ weight: 2.6, fillOpacity: 0.25 });
              }
            },
            mouseout: () => {
              if (layer !== state.selectedAquiferLayer) {
                layer.setStyle(aquiferLayerStyle(false));
              }
            },
            click: () => {
              if (state.selectedAquiferLayer && state.selectedAquiferLayer !== layer) {
                state.selectedAquiferLayer.setStyle(aquiferLayerStyle(false));
              }
              state.selectedAquiferLayer = layer;
              layer.setStyle(aquiferLayerStyle(true));
              layer.bringToFront();
              setSelectedAquifer(
                properties.id,
                `آبخوان ${properties.aquifer} · محدوده ${properties.mahdoude}`
              );
            }
          });
        }
      }).addTo(map);
      aquiferLayer.bringToFront();
      const bounds = mahdoudeLayer.getBounds();
      fitLeafletBoundsAndLockZoom(map, bounds, [4, 4]);
      window.setTimeout(() => map.invalidateSize(), 100);
    } catch (error) {
      console.error("Aquifer selection map failed:", error);
      mapElement.innerHTML = `<div class="flex h-full items-center justify-center p-8 text-center text-xs text-coral">${escapeHtml(error.message)}</div>`;
    }
  }

  function initializeSelectionTabs() {
    document.querySelectorAll(".selection-tab-button").forEach(button => {
      button.addEventListener("click", () => {
        const tab = button.dataset.selectionTab;
        document.querySelectorAll(".selection-tab-button").forEach(item => {
          item.classList.toggle("is-active", item === button);
        });
        document.querySelectorAll("[data-selection-panel]").forEach(panel => {
          panel.classList.toggle("hidden", panel.dataset.selectionPanel !== tab);
        });
        if (tab === "map") {
          window.setTimeout(() => state.selectionMap?.invalidateSize(), 50);
        } else {
          syncDropdownSelection();
        }
      });
    });
    document.getElementById("aquiferSelect")?.addEventListener("change", syncDropdownSelection);
    document.getElementById("aquiferSelectionForm")?.addEventListener("submit", event => {
      if (!document.getElementById("selectedAquiferId")?.value) {
        event.preventDefault();
        window.alert("ابتدا یک آبخوان را از نقشه یا فهرست انتخاب کنید.");
      }
    });
  }

  function persianDate(value) {
    if (!value) return "بدون داده";
    return String(value).replace(/\d/g, digit => "۰۱۲۳۴۵۶۷۸۹"[Number(digit)]);
  }

  function formatNumber(value, suffix = "") {
    return value === null || value === undefined ? "—" : `${faNumber.format(value)}${suffix}`;
  }

  function formatSignedNumber(value, suffix = "") {
    if (value === null || value === undefined) return "—";
    const sign = value > 0 ? "+" : value < 0 ? "−" : "";
    return `${sign}${faNumber.format(Math.abs(value))}${suffix}`;
  }

  function waterYearLabel(year) {
    return `${year}-${year + 1}`;
  }

  function periodDateLabel(year, month) {
    return `${monthNames[month - 1]} ${year}`;
  }

  function escapeHtml(value) {
    const element = document.createElement("div");
    element.textContent = String(value ?? "");
    return element.innerHTML;
  }

  function numberCell(value) {
    return value === null || value === undefined
      ? '<span class="text-slate-300">—</span>'
      : faNumber.format(value);
  }

  function metricCell(value) {
    if (value === null || value === undefined) {
      return '<span class="text-slate-300">—</span>';
    }
    const className = value > 0
      ? "metric-positive"
      : value < 0
        ? "metric-negative"
        : "font-medium text-slate-500";
    return `<span class="${className}">${faNumber.format(value)}</span>`;
  }

  function endpointCell(value, month) {
    return `
      <div>${numberCell(value)}</div>
      <div dir="ltr" class="mt-1 text-[9px] text-slate-400">${month || "—"}</div>
    `;
  }

  function trendText(trend, compact = false) {
    if (!trend || trend.direction === "insufficient" || trend.decline_per_year === null) {
      return compact ? "شیب نامشخص" : "داده کافی برای محاسبه شیب نیست";
    }
    if (trend.direction === "stable") return "تقریباً بدون تغییر";
    const value = faNumber.format(Math.abs(trend.decline_per_year));
    return trend.direction === "decline"
      ? `${compact ? "افت" : "شیب افت"} ${value} متر/سال`
      : `${compact ? "افزایش" : "شیب افزایش"} ${value} متر/سال`;
  }

  function trendChip(label, trend, variant = "") {
    const direction = trend?.direction || "insufficient";
    return `<span class="trend-chip ${direction} ${variant}"><b>${label}</b><span>${trendText(trend, true)}</span></span>`;
  }

  function alignedTrendSeries(trend, categories) {
    const values = new Map(trend?.series || []);
    return categories.map(category => (
      values.has(category) ? values.get(category) : null
    ));
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

  function pointInRing(point, ring) {
    let inside = false;
    for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index++) {
      const [x1, y1] = ring[index];
      const [x2, y2] = ring[previous];
      const intersects = ((y1 > point[1]) !== (y2 > point[1]))
        && point[0] < ((x2 - x1) * (point[1] - y1)) / (y2 - y1 || Number.EPSILON) + x1;
      if (intersects) inside = !inside;
    }
    return inside;
  }

  function pointInPolygon(point, polygon) {
    return pointInRing(point, polygon[0])
      && !polygon.slice(1).some(hole => pointInRing(point, hole));
  }

  function pointInGeometry(point, geometry) {
    if (geometry.type === "Polygon") return pointInPolygon(point, geometry.coordinates);
    if (geometry.type === "MultiPolygon") {
      return geometry.coordinates.some(polygon => pointInPolygon(point, polygon));
    }
    return false;
  }

  function idwValue(points, longitude, latitude, power = 2) {
    let weighted = 0;
    let totalWeight = 0;
    for (const point of points) {
      const dx = longitude - point[0];
      const dy = latitude - point[1];
      const distanceSquared = dx * dx + dy * dy;
      if (distanceSquared < 1e-12) return point[2];
      const weight = 1 / (distanceSquared ** (power / 2));
      weighted += point[2] * weight;
      totalWeight += weight;
    }
    return totalWeight ? weighted / totalWeight : null;
  }

  function interpolationGrid(points, geometry, size = 44) {
    const [minX, minY, maxX, maxY] = geometryBounds(geometry);
    const xCoordinates = Array.from(
      { length: size },
      (_, index) => minX + (maxX - minX) * index / (size - 1)
    );
    const yCoordinates = Array.from(
      { length: size },
      (_, index) => minY + (maxY - minY) * index / (size - 1)
    );
    const values = yCoordinates.map(latitude => (
      xCoordinates.map(longitude => (
        pointInGeometry([longitude, latitude], geometry)
          ? idwValue(points, longitude, latitude)
          : null
      ))
    ));
    return { xCoordinates, yCoordinates, values };
  }

  function aggregateSpatialPoints(points) {
    const grouped = new Map();
    points.forEach(point => {
      const key = `${point[0].toFixed(7)},${point[1].toFixed(7)}`;
      const item = grouped.get(key) || {
        longitude: point[0],
        latitude: point[1],
        values: []
      };
      item.values.push(point[2]);
      grouped.set(key, item);
    });
    return [...grouped.values()].map(item => [
      item.longitude,
      item.latitude,
      item.values.reduce((sum, value) => sum + value, 0) / item.values.length
    ]);
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

  function declineClassPieces(points) {
    const values = points
      .map(point => point[2])
      .filter(Number.isFinite);
    if (!values.length) return [];

    const zeroTolerance = 0.005;
    const negativeValues = values
      .filter(value => value < -zeroTolerance)
      .sort((first, second) => first - second);
    const positiveValues = values
      .filter(value => value > zeroTolerance)
      .sort((first, second) => first - second);
    const negativeThreshold = negativeValues.length
      ? quantile(negativeValues, 0.5)
      : -zeroTolerance;
    const positiveThresholds = positiveValues.length
      ? [0.2, 0.4, 0.6, 0.8].map(probability => (
        quantile(positiveValues, probability)
      ))
      : [zeroTolerance, zeroTolerance, zeroTolerance, zeroTolerance];

    return [
      {
        max: negativeThreshold,
        label: "افزایش زیاد",
        rangeLabel: `تا ${formatSignedNumber(negativeThreshold)}`,
        color: "#1D4ED8"
      },
      {
        gt: negativeThreshold,
        max: -zeroTolerance,
        label: "افزایش کم",
        rangeLabel: `${formatSignedNumber(negativeThreshold)} تا ۰`,
        color: "#93C5FD"
      },
      {
        gt: -zeroTolerance,
        lte: zeroTolerance,
        label: "بدون تغییر",
        rangeLabel: "۰",
        color: "#FFFFFF"
      },
      {
        gt: zeroTolerance,
        lte: positiveThresholds[0],
        label: "افت خیلی کم",
        rangeLabel: `تا ${formatSignedNumber(positiveThresholds[0])}`,
        color: "#FEE2E2"
      },
      {
        gt: positiveThresholds[0],
        lte: positiveThresholds[1],
        label: "افت کم",
        rangeLabel: `${formatSignedNumber(positiveThresholds[0])} تا ${formatSignedNumber(positiveThresholds[1])}`,
        color: "#FCA5A5"
      },
      {
        gt: positiveThresholds[1],
        lte: positiveThresholds[2],
        label: "افت متوسط",
        rangeLabel: `${formatSignedNumber(positiveThresholds[1])} تا ${formatSignedNumber(positiveThresholds[2])}`,
        color: "#F87171"
      },
      {
        gt: positiveThresholds[2],
        lte: positiveThresholds[3],
        label: "افت زیاد",
        rangeLabel: `${formatSignedNumber(positiveThresholds[2])} تا ${formatSignedNumber(positiveThresholds[3])}`,
        color: "#EF4444"
      },
      {
        gt: positiveThresholds[3],
        label: "افت خیلی زیاد",
        rangeLabel: `بیش از ${formatSignedNumber(positiveThresholds[3])}`,
        color: "#B91C1C"
      }
    ];
  }

  function declinePieceForValue(pieces, value) {
    return pieces.find(piece => (
      (piece.gt === undefined || value > piece.gt)
      && (piece.lte === undefined || value <= piece.lte)
      && (piece.min === undefined || value >= piece.min)
      && (piece.max === undefined || value <= piece.max)
    )) || pieces.at(-1);
  }

  function declinePieceRange(piece) {
    if (piece.rangeLabel) return piece.rangeLabel;
    if (piece.min !== undefined && piece.max !== undefined) {
      return formatSignedNumber(piece.min);
    }
    if (piece.gt === undefined) return `تا ${formatSignedNumber(piece.lte)}`;
    if (piece.lte === undefined) return `بیش از ${formatSignedNumber(piece.gt)}`;
    return `${formatSignedNumber(piece.gt)} تا ${formatSignedNumber(piece.lte)}`;
  }

  function declineIdwSurface(points, geometry, size = 96) {
    const uniquePoints = aggregateSpatialPoints(points);
    if (!uniquePoints.length) return [];
    const [minX, minY, maxX, maxY] = geometryBounds(geometry);
    const data = [];
    for (let row = 0; row < size; row += 1) {
      const latitude = minY + (maxY - minY) * row / (size - 1);
      for (let column = 0; column < size; column += 1) {
        const longitude = minX + (maxX - minX) * column / (size - 1);
        if (!pointInGeometry([longitude, latitude], geometry)) continue;
        const interpolated = idwValue(uniquePoints, longitude, latitude, 3);
        if (!Number.isFinite(interpolated)) continue;
        data.push([
          longitude,
          latitude,
          interpolated,
          "پهنه IDW افت سال‌به‌سال"
        ]);
      }
    }
    uniquePoints.forEach(point => {
      data.push([point[0], point[1], point[2], "مقدار مشاهده‌شده چاه"]);
    });
    return data;
  }

  function niceContourInterval(points, targetCount = 18) {
    const values = points.map(point => point[2]);
    const minimum = Math.min(...values);
    const maximum = Math.max(...values);
    if (!Number.isFinite(minimum) || !Number.isFinite(maximum) || maximum - minimum < 1e-8) {
      return 1;
    }
    const raw = (maximum - minimum) / targetCount;
    const magnitude = 10 ** Math.floor(Math.log10(raw));
    const normalized = raw / magnitude;
    const factor = [1, 2, 2.5, 5, 10]
      .filter(candidate => candidate <= normalized)
      .at(-1) || 1;
    return Number((factor * magnitude).toPrecision(8));
  }

  function contourLevels(points, interval) {
    const values = points.map(point => point[2]);
    const minimum = Math.min(...values);
    const maximum = Math.max(...values);
    if (
      !Number.isFinite(minimum)
      || !Number.isFinite(maximum)
      || !Number.isFinite(interval)
      || interval <= 0
      || maximum - minimum < 1e-8
    ) {
      return [];
    }
    const first = Math.ceil(minimum / interval) * interval;
    const levels = [];
    for (let level = first; level <= maximum + interval * 1e-8; level += interval) {
      levels.push(Number(level.toPrecision(10)));
      if (levels.length >= 120) break;
    }
    return levels;
  }

  function contourSegments(grid, level) {
    const segments = [];
    const cases = {
      1: [[3, 0]], 2: [[0, 1]], 3: [[3, 1]], 4: [[1, 2]],
      5: [[3, 2], [0, 1]], 6: [[0, 2]], 7: [[3, 2]], 8: [[2, 3]],
      9: [[2, 0]], 10: [[0, 3], [1, 2]], 11: [[2, 1]], 12: [[1, 3]],
      13: [[1, 0]], 14: [[0, 3]]
    };
    const edgePoint = (edge, corners, values) => {
      const edgeCorners = [[0, 1], [1, 2], [3, 2], [0, 3]];
      const [fromIndex, toIndex] = edgeCorners[edge];
      const from = corners[fromIndex];
      const to = corners[toIndex];
      const fromValue = values[fromIndex];
      const toValue = values[toIndex];
      const ratio = Math.abs(toValue - fromValue) < 1e-12
        ? 0.5
        : (level - fromValue) / (toValue - fromValue);
      return [
        from[0] + (to[0] - from[0]) * ratio,
        from[1] + (to[1] - from[1]) * ratio
      ];
    };

    for (let row = 0; row < grid.yCoordinates.length - 1; row += 1) {
      for (let column = 0; column < grid.xCoordinates.length - 1; column += 1) {
        const values = [
          grid.values[row][column],
          grid.values[row][column + 1],
          grid.values[row + 1][column + 1],
          grid.values[row + 1][column]
        ];
        if (values.some(value => value === null || !Number.isFinite(value))) continue;
        const mask = values.reduce(
          (result, value, index) => result | (value >= level ? 1 << index : 0),
          0
        );
        if (!cases[mask]) continue;
        const corners = [
          [grid.xCoordinates[column], grid.yCoordinates[row]],
          [grid.xCoordinates[column + 1], grid.yCoordinates[row]],
          [grid.xCoordinates[column + 1], grid.yCoordinates[row + 1]],
          [grid.xCoordinates[column], grid.yCoordinates[row + 1]]
        ];
        cases[mask].forEach(([firstEdge, secondEdge]) => {
          segments.push([
            edgePoint(firstEdge, corners, values),
            edgePoint(secondEdge, corners, values)
          ]);
        });
      }
    }
    return segments;
  }

  function spatialWellPoints(data, monthIndex, comparisonIndex, mode) {
    const currentPoints = [];
    const declinePoints = [];
    data.wells.forEach(well => {
      const current = well.series[monthIndex]?.[1];
      const previous = comparisonIndex >= 0
        ? well.series[comparisonIndex]?.[1]
        : null;
      const hasComparison = current !== null && current !== undefined
        && previous !== null && previous !== undefined;
      const accepted = mode === "calculation"
        ? well.included
        : mode === "comparable"
          ? hasComparison
          : true;
      if (!accepted || well.longitude === null || well.latitude === null) return;
      if (current !== null && current !== undefined) {
        currentPoints.push([well.longitude, well.latitude, current, well.name]);
      }
      if (hasComparison) {
        declinePoints.push([
          well.longitude,
          well.latitude,
          previous - current,
          well.name
        ]);
      }
    });
    return { currentPoints, declinePoints };
  }

  function spatialLeafletOption(geometry) {
    const [minimumX, minimumY, maximumX, maximumY] = geometryBounds(geometry);
    return {
      center: [(minimumX + maximumX) / 2, (minimumY + maximumY) / 2],
      zoom: 8,
      maxZoom: LEAFLET_MAX_ZOOM,
      zoomSnap: 0.25,
      zoomDelta: 0.5,
      attributionControl: true,
      resizeEnable: true,
      renderOnMoving: true,
      echartsLayerInteractive: true
    };
  }

  function configureSpatialLeaflet(chart, feature) {
    const component = chart.getModel().getComponent("lmap");
    const map = component?.getLeaflet();
    if (!map || map._hydroSpatialConfigured) return;
    map._hydroSpatialConfigured = true;
    const echartsLayer = component.getEChartsLayer();
    if (echartsLayer) {
      echartsLayer.style.zIndex = "450";
    }
    addBaseMap(map);
    map.createPane("aquiferBoundaryPane");
    map.getPane("aquiferBoundaryPane").style.zIndex = "350";
    const boundary = L.geoJSON(feature, {
      pane: "aquiferBoundaryPane",
      interactive: false,
      style: {
        color: "#087E8B",
        weight: 2,
        opacity: 0.95,
        fillColor: "#EAF5F4",
        fillOpacity: 0.48
      }
    }).addTo(map);
    map._spatialBoundaryBounds = boundary.getBounds();
    map.on("resize", () => refreshLeafletMinimumZoom(map));
  }

  function fitSpatialLeaflet(chart) {
    const component = chart?.getModel().getComponent("lmap");
    const map = component?.getLeaflet();
    if (!map?._spatialBoundaryBounds) return;
    chart.resize();
    map.invalidateSize({ animate: false, pan: false });
    fitLeafletBoundsAndLockZoom(map, map._spatialBoundaryBounds, [24, 24]);
    const center = map.getCenter();
    component.setCenterAndZoom([center.lat, center.lng], map.getZoom());
    chart.dispatchAction({ type: "lmapRoam" });
  }

  function syncSpatialMapHeaderHeights() {
    const headers = [
      document.querySelector('[data-spatial-map-header="contour"]'),
      document.querySelector('[data-spatial-map-header="decline"]')
    ].filter(Boolean);
    headers.forEach(header => {
      header.style.height = "";
    });
    if (window.innerWidth < 1024 || headers.length < 2) return;
    const height = Math.max(...headers.map(header => header.scrollHeight));
    headers.forEach(header => {
      header.style.height = `${height}px`;
    });
  }

  function finalizeInitialSpatialView() {
    if (state.spatialViewInitialized || !state.spatialCharts) return;
    window.requestAnimationFrame(() => {
      syncSpatialMapHeaderHeights();
      fitSpatialLeaflet(state.spatialCharts.contour);
      fitSpatialLeaflet(state.spatialCharts.decline);
      state.spatialViewInitialized = true;
      window.requestAnimationFrame(() => {
        // Rebuild the series after Leaflet has settled on its fitted view.
        renderSpatialFrame();
        window.requestAnimationFrame(() => {
          ["contourMapChart", "declineMapChart"].forEach(id => {
            const element = document.getElementById(id);
            if (element) element.style.visibility = "visible";
          });
          applyHeatmapClip();
        });
      });
    });
  }

  function geometryOuterRings(geometry) {
    if (geometry.type === "Polygon") return [geometry.coordinates[0]];
    if (geometry.type === "MultiPolygon") {
      return geometry.coordinates.map(polygon => polygon[0]);
    }
    return [];
  }

  function applyHeatmapClip() {
    const data = state.spatialData;
    const chart = state.spatialCharts?.decline;
    if (!data || !chart) return;
    const seriesModel = chart.getModel().queryComponents({
      mainType: "series",
      id: "monthly-decline-heat"
    })[0];
    const seriesView = seriesModel && chart.getViewOfSeriesModel(seriesModel);
    if (!seriesView?.group) return;
    const paths = geometryOuterRings(data.boundaries.aquifer.geometry)
      .map(ring => ring
        .map(coordinate => chart.convertToPixel({ lmapIndex: 0 }, coordinate))
        .filter(point => point?.every(Number.isFinite)))
      .filter(points => points.length >= 3)
      .map(points => new echarts.graphic.Polygon({ shape: { points } }));
    if (!paths.length) return;
    seriesView.group.setClipPath(
      new echarts.graphic.CompoundPath({ shape: { paths } })
    );
  }

  function spatialMonthLabels(data) {
    return data.hydrographs.thiessen.map(item => item[0]);
  }

  function spatialComparisonIndex(data, monthIndex) {
    const labels = spatialMonthLabels(data);
    const current = labels[monthIndex];
    if (!current) return -1;
    const [year, month] = current.split("-").map(Number);
    return labels.indexOf(`${year - 1}-${String(month).padStart(2, "0")}`);
  }

  function defaultSpatialMonthIndex(data, preferredMonth = 7) {
    const labels = spatialMonthLabels(data);
    for (let index = labels.length - 1; index >= 0; index -= 1) {
      if (Number(labels[index].slice(5, 7)) === preferredMonth) return index;
    }
    return Math.max(0, labels.length - 1);
  }

  function spatialYearStepIndex(data, monthIndex, step) {
    const labels = spatialMonthLabels(data);
    const current = labels[monthIndex];
    if (!current) return -1;
    const [year, month] = current.split("-").map(Number);
    return labels.indexOf(`${year + step}-${String(month).padStart(2, "0")}`);
  }

  function spatialComparableYearIndexes(data, monthIndex) {
    const labels = spatialMonthLabels(data);
    const current = labels[monthIndex];
    if (!current) return [];
    const month = Number(current.slice(5, 7));
    return labels
      .map((label, index) => ({ label, index }))
      .filter(item => (
        Number(item.label.slice(5, 7)) === month
        && spatialComparisonIndex(data, item.index) >= 0
      ))
      .map(item => item.index);
  }

  function spatialRangeDeclinePoints(data, targetMonth, mode) {
    const labels = spatialMonthLabels(data);
    return labels.flatMap((label, monthIndex) => {
      if (Number(label.slice(5, 7)) !== targetMonth) return [];
      const comparisonIndex = spatialComparisonIndex(data, monthIndex);
      if (comparisonIndex < 0) return [];
      return spatialWellPoints(data, monthIndex, comparisonIndex, mode).declinePoints;
    });
  }

  function syncSpatialDateControls() {
    const data = state.spatialData;
    if (!data) return;
    const labels = spatialMonthLabels(data);
    const current = labels[state.spatialMonthIndex];
    const [year, month] = current.split("-").map(Number);
    const yearSelect = document.getElementById("spatialYear");
    const monthSelect = document.getElementById("spatialMonth");
    const years = [...new Set(labels.map(label => Number(label.slice(0, 4))))];
    yearSelect.innerHTML = years
      .map(value => `<option value="${value}">${value}</option>`)
      .join("");
    yearSelect.value = String(year);
    const availableMonths = labels
      .filter(label => Number(label.slice(0, 4)) === year)
      .map(label => Number(label.slice(5, 7)));
    monthSelect.innerHTML = availableMonths
      .map(value => `<option value="${value}">${monthNames[value - 1]}</option>`)
      .join("");
    monthSelect.value = String(month);
  }

  function selectSpatialDate() {
    const data = state.spatialData;
    if (!data) return;
    stopSpatialPlayback();
    const year = Number(document.getElementById("spatialYear").value);
    const month = Number(document.getElementById("spatialMonth").value);
    const label = `${year}-${String(month).padStart(2, "0")}`;
    const index = spatialMonthLabels(data).indexOf(label);
    if (index >= 0) {
      state.spatialMonthIndex = index;
      renderSpatialFrame();
    }
  }

  function renderSpatialFrame() {
    const data = state.spatialData;
    const charts = state.spatialCharts;
    if (!data || !charts) return;
    const monthIndex = state.spatialMonthIndex;
    const mode = document.getElementById("spatialWellMode")?.value || "calculation";
    const month = data.hydrographs.thiessen[monthIndex]?.[0];
    const comparisonIndex = spatialComparisonIndex(data, monthIndex);
    const previousYearMonth = comparisonIndex >= 0
      ? data.hydrographs.thiessen[comparisonIndex]?.[0]
      : null;
    const { currentPoints, declinePoints } = spatialWellPoints(
      data,
      monthIndex,
      comparisonIndex,
      mode
    );
    const geometry = data.boundaries.aquifer.geometry;
    const intervalInput = document.getElementById("contourInterval");
    if (currentPoints.length >= 3 && !state.contourIntervalInitialized) {
      intervalInput.value = String(niceContourInterval(currentPoints));
      state.contourIntervalInitialized = true;
    }
    let interval = Number(intervalInput.value);
    if ((!Number.isFinite(interval) || interval <= 0) && currentPoints.length >= 3) {
      interval = niceContourInterval(currentPoints);
      intervalInput.value = String(interval);
    }
    const levels = currentPoints.length >= 3 ? contourLevels(currentPoints, interval) : [];
    const grid = levels.length ? interpolationGrid(currentPoints, geometry) : null;
    const contourSeries = levels.map((level, index) => ({
      id: `contour-${level}`,
      name: `تراز ${faNumber.format(level)}`,
      type: "lines",
      coordinateSystem: "lmap",
      polyline: true,
      silent: true,
      data: contourSegments(grid, level).map(coords => ({ coords, value: level })),
      lineStyle: {
        color: "#111827",
        width: 1.8,
        opacity: 0.88
      },
      emphasis: { disabled: true },
      animation: false
    }));
    const activeContourIds = contourSeries.map(series => series.id);
    const removedContourSeries = state.spatialContourSeriesIds
      .filter(id => !activeContourIds.includes(id))
      .map(id => ({ id, data: [] }));
    state.spatialContourSeriesIds = activeContourIds;
    const contourLabels = levels.flatMap((level, index) => {
      const segments = contourSegments(grid, level);
      if (!segments.length) return [];
      const segment = segments[Math.floor(segments.length / 2)];
      return [{
        value: [
          (segment[0][0] + segment[1][0]) / 2,
          (segment[0][1] + segment[1][1]) / 2,
          level
        ],
        itemStyle: { color: "#111827" }
      }];
    });

    charts.contour.setOption({
      series: [
        ...contourSeries,
        ...removedContourSeries,
        {
          id: "contour-labels",
          name: "برچسب خطوط تراز",
          type: "scatter",
          coordinateSystem: "lmap",
          silent: true,
          symbolSize: 4,
          data: contourLabels,
          label: {
            show: true,
            position: "top",
            formatter: parameters => faNumber.format(parameters.value[2]),
            fontFamily: "Vazirmatn",
            fontSize: 9,
            color: "#111827",
            backgroundColor: "rgba(255,255,255,0.82)",
            borderRadius: 4,
            padding: [2, 4]
          },
          animation: false
        },
        {
          id: "contour-wells",
          name: "پیزومترها",
          type: "scatter",
          coordinateSystem: "lmap",
          symbolSize: 8,
          data: currentPoints.map(point => ({ value: point })),
          itemStyle: { color: "#11395B", borderColor: "#FFFFFF", borderWidth: 1.5 },
          z: 10,
          animation: false
        }
      ]
    });
    charts.contour.dispatchAction({ type: "lmapRoam" });

    const declineValues = declinePoints.map(point => point[2]).filter(Number.isFinite);
    const minimumDecline = declineValues.length ? Math.min(...declineValues) : 0;
    const maximumDecline = declineValues.length ? Math.max(...declineValues) : 0;
    const declineSurface = declineIdwSurface(declinePoints, geometry);
    const targetMonth = Number(month.slice(5, 7));
    const rangeDeclinePoints = spatialRangeDeclinePoints(data, targetMonth, mode);
    const declinePieces = declineClassPieces(rangeDeclinePoints);
    charts.decline.setOption({
      series: [
        {
          id: "monthly-decline-heat",
          name: "افت سال‌به‌سال",
          type: "scatter",
          coordinateSystem: "lmap",
          symbol: "rect",
          symbolSize: 9,
          data: declineSurface.map(point => ({
            value: point,
            itemStyle: {
              color: declinePieceForValue(declinePieces, point[2])?.color || "#CBD5E1",
              opacity: 0.94
            }
          })),
          animation: false
        },
        {
          id: "decline-wells",
          name: "پیزومترها",
          type: "scatter",
          coordinateSystem: "lmap",
          symbolSize: 7,
          data: declinePoints.map(point => ({ value: point })),
          itemStyle: { color: "#FFFFFF", borderColor: "#11395B", borderWidth: 1.4 },
          label: {
            show: true,
            position: "right",
            formatter: parameters => formatSignedNumber(parameters.value[2]),
            fontFamily: "Vazirmatn",
            fontSize: 9,
            fontWeight: 700,
            color: "#11395B",
            backgroundColor: "rgba(255,255,255,0.84)",
            borderRadius: 4,
            padding: [2, 4]
          },
          z: 10,
          animation: false
        }
      ]
    });
    charts.decline.dispatchAction({ type: "lmapRoam" });
    window.requestAnimationFrame(applyHeatmapClip);

    document.getElementById("spatialMonthLabel").textContent = persianDate(month);
    document.getElementById("contourMapSummary").textContent = currentPoints.length >= 3
      ? `${faNumber.format(currentPoints.length)} چاه · ${faNumber.format(levels.length)} خط · فاصله ${formatNumber(interval, " متر")}`
      : `${faNumber.format(currentPoints.length)} چاه · حداقل ۳ چاه برای درون‌یابی لازم است`;
    document.getElementById("declineMapSummary").textContent = previousYearMonth
      ? `${faNumber.format(declinePoints.length)} چاه · مرز کلاس‌ها ثابت بر اساس ${faNumber.format(rangeDeclinePoints.length)} مشاهده در کل بازه · دامنه این سال ${formatSignedNumber(minimumDecline)} تا ${formatSignedNumber(maximumDecline)} متر · نسبت به ${persianDate(previousYearMonth)}`
      : "برای این ماه، مقدار ماه مشابه در سال قبل داخل بازه موجود نیست";
    document.getElementById("declineClassLegend").innerHTML = declinePieces.map(piece => `
      <span class="inline-flex items-center gap-1.5 rounded-md bg-white/90 px-2 py-1 text-slate-600 shadow-sm ring-1 ring-slate-100">
        <i class="h-2.5 w-2.5 rounded-sm" style="background:${piece.color}"></i>
        ${piece.label} <b dir="ltr">${declinePieceRange(piece)}</b>
      </span>
    `).join("");
    syncSpatialMapHeaderHeights();
    document.getElementById("spatialPreviousMonth").disabled =
      spatialYearStepIndex(data, monthIndex, -1) < 0;
    document.getElementById("spatialNextMonth").disabled =
      spatialYearStepIndex(data, monthIndex, 1) < 0;
    syncSpatialDateControls();
    finalizeInitialSpatialView();
  }

  function stopSpatialPlayback() {
    if (state.spatialTimer) {
      window.clearInterval(state.spatialTimer);
      state.spatialTimer = null;
    }
    const button = document.getElementById("spatialPlay");
    if (button) button.textContent = "پخش";
  }

  function renderSpatialAnalysis(data) {
    const contourElement = document.getElementById("contourMapChart");
    const declineElement = document.getElementById("declineMapChart");
    if (!contourElement || !declineElement) return;
    contourElement.style.visibility = "hidden";
    declineElement.style.visibility = "hidden";
    state.spatialData = data;
    state.spatialMonthIndex = defaultSpatialMonthIndex(
      data,
      data.calendar?.water_year_start_month
    );
    state.spatialContourSeriesIds = [];
    state.contourIntervalInitialized = false;
    state.spatialViewInitialized = false;
    state.spatialCharts = {
      contour: echarts.init(contourElement),
      decline: echarts.init(declineElement)
    };
    state.charts.push(state.spatialCharts.contour, state.spatialCharts.decline);
    state.spatialCharts.contour.setOption({
      animation: false,
      textStyle: { fontFamily: "Vazirmatn" },
      tooltip: {
        trigger: "item",
        textStyle: { fontFamily: "Vazirmatn" },
        formatter: parameters => {
          const value = parameters.value;
          return value?.length
            ? `${escapeHtml(value[3] || "")}<br>تراز: ${formatNumber(value[2], " متر")}`
            : "";
        }
      },
      lmap: spatialLeafletOption(data.boundaries.aquifer.geometry),
      series: []
    });
    state.spatialCharts.decline.setOption({
      animation: false,
      textStyle: { fontFamily: "Vazirmatn" },
      tooltip: {
        trigger: "item",
        textStyle: { fontFamily: "Vazirmatn" },
        formatter: parameters => {
          const value = parameters.value;
          if (!value?.length) return "";
          const direction = value[2] > 0
            ? "افت نسبت به ماه مشابه سال قبل"
            : value[2] < 0
              ? "افزایش تراز نسبت به ماه مشابه سال قبل"
              : "افت صفر / بدون تغییر";
          return `${escapeHtml(value[3] || "")}<br>${direction}: <b dir="ltr">${formatSignedNumber(value[2], " متر")}</b>`;
        }
      },
      lmap: spatialLeafletOption(data.boundaries.aquifer.geometry),
      series: []
    });
    configureSpatialLeaflet(state.spatialCharts.contour, data.boundaries.aquifer);
    configureSpatialLeaflet(state.spatialCharts.decline, data.boundaries.aquifer);
    state.spatialCharts.decline.on("lmapRoam", () => {
      window.requestAnimationFrame(applyHeatmapClip);
    });
    document.getElementById("spatialWellMode").onchange = renderSpatialFrame;
    document.getElementById("contourInterval").onchange = renderSpatialFrame;
    document.getElementById("spatialYear").onchange = () => {
      const labels = spatialMonthLabels(data);
      const year = Number(document.getElementById("spatialYear").value);
      const monthSelect = document.getElementById("spatialMonth");
      const preferredMonth = data.calendar?.water_year_start_month || 1;
      const selectedMonth = Number(monthSelect.value) || preferredMonth;
      const availableMonths = labels
        .filter(label => Number(label.slice(0, 4)) === year)
        .map(label => Number(label.slice(5, 7)));
      monthSelect.innerHTML = availableMonths
        .map(value => `<option value="${value}">${monthNames[value - 1]}</option>`)
        .join("");
      const nextMonth = availableMonths.includes(selectedMonth)
        ? selectedMonth
        : availableMonths.includes(preferredMonth)
          ? preferredMonth
          : availableMonths.at(-1);
      monthSelect.value = String(nextMonth);
      selectSpatialDate();
    };
    document.getElementById("spatialMonth").onchange = selectSpatialDate;
    document.getElementById("spatialPreviousMonth").onclick = () => {
      stopSpatialPlayback();
      const index = spatialYearStepIndex(data, state.spatialMonthIndex, -1);
      if (index >= 0) {
        state.spatialMonthIndex = index;
        renderSpatialFrame();
      }
    };
    document.getElementById("spatialNextMonth").onclick = () => {
      stopSpatialPlayback();
      const index = spatialYearStepIndex(data, state.spatialMonthIndex, 1);
      if (index >= 0) {
        state.spatialMonthIndex = index;
        renderSpatialFrame();
      }
    };
    document.getElementById("spatialPlay").onclick = () => {
      if (state.spatialTimer) {
        stopSpatialPlayback();
        return;
      }
      const indexes = spatialComparableYearIndexes(data, state.spatialMonthIndex);
      if (!indexes.length) return;
      let position = indexes.indexOf(state.spatialMonthIndex);
      if (position < 0 || position >= indexes.length - 1) {
        position = 0;
        state.spatialMonthIndex = indexes[position];
        renderSpatialFrame();
      }
      document.getElementById("spatialPlay").textContent = "توقف";
      state.spatialTimer = window.setInterval(() => {
        position += 1;
        if (position >= indexes.length) {
          stopSpatialPlayback();
          return;
        }
        state.spatialMonthIndex = indexes[position];
        renderSpatialFrame();
      }, 1200);
    };
    renderSpatialFrame();
  }

  function disposeVisuals() {
    stopSpatialPlayback();
    if (state.observer) {
      state.observer.disconnect();
      state.observer = null;
    }
    state.charts.forEach(chart => chart.dispose());
    state.charts = [];
    state.spatialCharts = null;
    state.spatialData = null;
    state.spatialContourSeriesIds = [];
    state.contourIntervalInitialized = false;
    state.spatialViewInitialized = false;
    if (state.modalChart) {
      state.modalChart.dispose();
      state.modalChart = null;
    }
    if (state.precipitationModalChart) {
      state.precipitationModalChart.dispose();
      state.precipitationModalChart = null;
    }
    state.aquiferNdviChart = null;
    state.aquiferAetChart = null;
    document.getElementById("wellDetailModal")?.classList.add("hidden");
    document.getElementById("precipitationDetailModal")?.classList.add("hidden");
    document.body.classList.remove("overflow-hidden");
    if (state.map) {
      state.map.remove();
      state.map = null;
      state.mapWellLayers = null;
    }
  }

  function baseChartOption() {
    return {
      animationDuration: 450,
      textStyle: { fontFamily: "Vazirmatn", color: "#475569" },
      tooltip: {
        trigger: "axis",
        textStyle: { fontFamily: "Vazirmatn" },
        valueFormatter: value => value == null ? "بدون داده" : `${faNumber.format(value)} متر`
      },
      grid: { top: 50, right: 68, bottom: 58, left: 68 },
      xAxis: {
        type: "category",
        boundaryGap: true,
        axisLabel: {
          formatter: persianDate,
          hideOverlap: true,
          fontSize: 10
        },
        axisLine: { lineStyle: { color: "#CBD5E1" } }
      },
      yAxis: [
        {
          type: "value",
          name: "تراز (متر)",
          nameTextStyle: { fontFamily: "Vazirmatn", fontSize: 10, padding: [0, 0, 8, 0] },
          scale: true,
          splitLine: { lineStyle: { color: "#E9EFF2", type: "dashed" } },
          axisLabel: { formatter: value => faNumber.format(value), fontSize: 10 }
        },
        {
          type: "value",
          name: "بارش (mm/month)",
          min: 0,
          nameTextStyle: { fontFamily: "Vazirmatn", fontSize: 9, padding: [0, 0, 8, 0] },
          axisLine: { show: true, lineStyle: { color: "#0EA5E9" } },
          axisTick: { show: true, lineStyle: { color: "#0EA5E9" } },
          splitLine: { show: false },
          axisLabel: {
            formatter: value => faNumber.format(value),
            fontSize: 9,
            color: "#0284C7"
          }
        }
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: 0 },
        {
          type: "slider",
          xAxisIndex: 0,
          height: 18,
          bottom: 8,
          borderColor: "transparent",
          fillerColor: "rgba(8, 126, 139, 0.15)",
          handleStyle: { color: "#087E8B" }
        }
      ]
    };
  }

  function precipitationBarSeries(precipitation) {
    return {
      name: "بارش ماهانه",
      type: "bar",
      yAxisIndex: 1,
      data: precipitation.series.map(item => item[1]),
      barMaxWidth: 14,
      itemStyle: {
        color: "rgba(14, 165, 233, 0.34)",
        borderColor: "rgba(2, 132, 199, 0.62)",
        borderWidth: 0.7,
        borderRadius: [3, 3, 0, 0]
      },
      emphasis: {
        itemStyle: { color: "rgba(2, 132, 199, 0.58)" }
      },
      tooltip: {
        valueFormatter: value => (
          value == null ? "بدون داده" : `${faNumber.format(value)} میلی‌متر`
        )
      },
      z: 1
    };
  }

  function ndviMetricLabel(metric) {
    return {
      mean: "میانگین",
      median: "میانه",
      max: "بیشینه"
    }[metric] || "میانه";
  }

  function ndviBarSeries(ndvi, metric) {
    const series = ndvi.metrics[metric] || ndvi.metrics.median;
    return {
      name: `NDVI ${ndviMetricLabel(metric)}`,
      type: "bar",
      yAxisIndex: 1,
      data: series.map(item => item[1]),
      barMaxWidth: 14,
      itemStyle: {
        color: "rgba(16, 185, 129, 0.34)",
        borderColor: "rgba(5, 150, 105, 0.7)",
        borderWidth: 0.8,
        borderRadius: [3, 3, 0, 0]
      },
      emphasis: {
        itemStyle: { color: "rgba(5, 150, 105, 0.6)" }
      },
      tooltip: {
        valueFormatter: value => (
          value == null ? "بدون داده" : faNumber.format(value)
        )
      },
      z: 1
    };
  }

  function aetBarSeries(aet) {
    return {
      name: "AET ماهانه",
      type: "bar",
      yAxisIndex: 1,
      data: aet.series.map(item => item[1]),
      barMaxWidth: 14,
      itemStyle: {
        color: "rgba(245, 158, 11, 0.38)",
        borderColor: "rgba(217, 119, 6, 0.78)",
        borderWidth: 0.8,
        borderRadius: [3, 3, 0, 0]
      },
      emphasis: {
        itemStyle: { color: "rgba(217, 119, 6, 0.66)" }
      },
      tooltip: {
        valueFormatter: value => (
          value == null ? "بدون داده" : `${faNumber.format(value)} میلی‌متر`
        )
      },
      z: 1
    };
  }

  function renderFilterControls(data) {
    state.currentData = data;
    const years = Array.from(
      { length: data.filters.maximum_year - data.filters.minimum_year + 1 },
      (_, index) => data.filters.minimum_year + index
    );
    const yearOptions = years
      .map(year => `<option value="${year}">${year}</option>`)
      .join("");
    const yearValues = {
      startYear: data.filters.start_year,
      endYear: data.filters.end_year,
      comparisonStartYear: data.filters.comparison_start_year,
      comparisonEndYear: data.filters.comparison_end_year
    };
    Object.entries(yearValues).forEach(([id, value]) => {
      const select = document.getElementById(id);
      if (!select.options.length) select.innerHTML = yearOptions;
      select.value = String(value);
    });
    renderMonthOptions("start", data.filters.start_month);
    renderMonthOptions("end", data.filters.end_month);
    renderMonthOptions("comparisonStart", data.filters.comparison_start_month);
    renderMonthOptions("comparisonEnd", data.filters.comparison_end_month);
    document.getElementById("continuousOnly").checked = data.filters.continuous_only;
    renderManualWellSelector(data);
  }

  function selectedManualWellIds() {
    return Array.from(
      document.querySelectorAll('#manualWellList input[type="checkbox"]:checked')
    ).map(input => input.value);
  }

  function updateManualWellCount() {
    const count = selectedManualWellIds().length;
    const eligible = document.querySelectorAll(
      '#manualWellList input[type="checkbox"]:not(:disabled)'
    ).length;
    const label = document.getElementById("manualWellCount");
    if (label) {
      label.textContent = `${faNumber.format(count)} چاه انتخاب‌شده از ${faNumber.format(eligible)} چاه دارای داده در بازه`;
    }
  }

  function syncManualSelectionUI() {
    const toggle = document.getElementById("manualWellSelection");
    const panel = document.getElementById("manualWellPanel");
    const continuousOnly = document.getElementById("continuousOnly");
    if (!toggle || !panel || !continuousOnly) return;
    panel.classList.toggle("hidden", !toggle.checked);
    continuousOnly.disabled = toggle.checked;
    continuousOnly.closest("label")?.classList.toggle("opacity-50", toggle.checked);
    updateManualWellCount();
  }

  function renderManualWellSelector(data) {
    const toggle = document.getElementById("manualWellSelection");
    const list = document.getElementById("manualWellList");
    const search = document.getElementById("manualWellSearch");
    if (!toggle || !list || !search) return;

    toggle.checked = Boolean(data.filters.manual_selection);
    list.innerHTML = data.wells.map(well => {
      const suffix = well.name_suffix > 1 ? ` (${faNumber.format(well.name_suffix)})` : "";
      const disabled = !well.has_range_data;
      return `
        <label class="manual-well-option${disabled ? " is-disabled" : ""}" data-well-name="${escapeHtml(well.name.toLocaleLowerCase("fa-IR"))}">
          <input
            type="checkbox"
            value="${escapeHtml(well.id)}"
            ${well.included ? "checked" : ""}
            ${disabled ? "disabled" : ""}
          >
          <span>
            <strong class="block font-medium">${escapeHtml(well.name)}${suffix}</strong>
            <small class="mt-1 block text-[9px] text-slate-400">
              ${disabled ? "فاقد داده در بازه" : well.included ? "داخل محاسبات فعلی" : "قابل انتخاب"}
            </small>
          </span>
        </label>
      `;
    }).join("");

    list.onchange = updateManualWellCount;
    toggle.onchange = syncManualSelectionUI;
    search.value = "";
    search.oninput = () => {
      const query = search.value.trim().toLocaleLowerCase("fa-IR");
      list.querySelectorAll(".manual-well-option").forEach(option => {
        option.classList.toggle("hidden", Boolean(query) && !option.dataset.wellName.includes(query));
      });
    };
    document.getElementById("selectAllEligibleWells").onclick = () => {
      list.querySelectorAll('input[type="checkbox"]:not(:disabled)').forEach(input => {
        input.checked = true;
      });
      updateManualWellCount();
    };
    document.getElementById("clearSelectedWells").onclick = () => {
      list.querySelectorAll('input[type="checkbox"]').forEach(input => {
        input.checked = false;
      });
      updateManualWellCount();
    };
    syncManualSelectionUI();
  }

  function renderMonthOptions(side, selectedMonth = null) {
    const data = state.currentData;
    if (!data) return;
    const yearSelect = document.getElementById(`${side}Year`);
    const monthSelect = document.getElementById(`${side}Month`);
    const year = Number(yearSelect.value);
    let first = 1;
    let last = 12;
    if (year === data.filters.minimum_year) first = data.filters.minimum_month;
    if (year === data.filters.maximum_year) last = data.filters.maximum_month;
    monthSelect.innerHTML = monthNames
      .map((name, index) => index + 1)
      .filter(month => month >= first && month <= last)
      .map(month => `<option value="${month}">${monthNames[month - 1]}</option>`)
      .join("");
    const preferred = selectedMonth ?? (
      side.toLowerCase().endsWith("end") ? last : first
    );
    monthSelect.value = String(Math.min(Math.max(preferred || first, first), last));
  }

  function renderStats(data) {
    const stats = data.stats;
    const change = stats.change;
    const changeLabel = change === null
      ? "بدون داده"
      : change < 0
        ? `${formatNumber(Math.abs(change), " متر")} افت`
        : `${formatNumber(change, " متر")} افزایش`;
    const cards = [
      ["کل پیزومترها", formatNumber(stats.total_wells), "شامل تمام نقاط ثبت‌شده", "bg-navy"],
      ["داخل محاسبات", formatNumber(stats.selected_wells), `${formatNumber(stats.selected_sites)} ایستگاه مکانی تیسن`, "bg-teal"],
      ["خارج از محاسبات", formatNumber(stats.excluded_wells), "با برچسب مجزا در نمودارها", "bg-amber-400"],
      ["تعداد ماه‌ها", formatNumber(data.hydrographs.arithmetic.length), "در بازه ماهانه منتخب", "bg-aqua"],
      ["تغییر دوره", changeLabel, "اولین تا آخرین مقدار موجود", change < 0 ? "bg-coral" : "bg-teal"]
    ];
    document.getElementById("statsGrid").innerHTML = cards.map(([label, value, note, color]) => `
      <article class="stat-card">
        <span class="absolute -left-4 -top-4 h-16 w-16 rounded-full ${color} opacity-10"></span>
        <div class="text-xs text-slate-500">${label}</div>
        <div class="mt-3 text-xl font-bold text-navy md:text-2xl">${value}</div>
        <div class="mt-2 text-[10px] leading-5 text-slate-400">${note}</div>
      </article>
    `).join("");
    document.getElementById("periodBadge").textContent =
      `${periodDateLabel(data.filters.start_year, data.filters.start_month)} تا ${periodDateLabel(data.filters.end_year, data.filters.end_month)}`;
    document.getElementById("wellCountLabel").textContent =
      `${faNumber.format(stats.total_wells)} نمودار · ${faNumber.format(stats.selected_wells)} داخل محاسبات`;
  }

  function renderMap(data) {
    const map = L.map("map", {
      zoomControl: true,
      attributionControl: true,
      preferCanvas: true,
      zoomSnap: 0.25,
      zoomDelta: 0.5,
      maxZoom: LEAFLET_MAX_ZOOM
    });
    state.map = map;
    const baseMap = addBaseMap(map);

    const mahdoudeLayer = L.geoJSON(data.boundaries.mahdoude, {
      style: {
        color: "#11395B",
        weight: 2,
        opacity: 0.75,
        fillColor: "#54C6C4",
        fillOpacity: 0.04,
        dashArray: "7 6"
      }
    }).addTo(map);

    const aquiferLayer = L.geoJSON(data.boundaries.aquifer, {
      style: {
        color: "#087E8B",
        weight: 3,
        opacity: 1,
        fillColor: "#54C6C4",
        fillOpacity: 0.08
      }
    }).addTo(map);

    const palette = ["#0E7490", "#0891B2", "#14B8A6", "#65A30D", "#D97706", "#7C3AED", "#DB2777"];
    const thiessenLayer = L.geoJSON(data.thiessen_polygons, {
      style: feature => {
        const key = feature.properties.site_key || "";
        const hash = [...key].reduce((sum, char) => sum + char.charCodeAt(0), 0);
        const color = palette[hash % palette.length];
        return {
          color,
          weight: 1.5,
          opacity: 0.9,
          fillColor: color,
          fillOpacity: 0.22
        };
      },
      onEachFeature: (feature, layer) => {
        layer.bindPopup(`
          <div dir="rtl" class="min-w-40 text-right">
            <strong>پهنه تیسن</strong>
            <div style="margin-top:6px;color:#475569;font-size:11px">${escapeHtml(feature.properties.well_names)}</div>
            <div style="margin-top:5px;color:#087E8B;font-size:11px">وزن مساحتی: ${formatNumber(feature.properties.weight * 100, "٪")}</div>
          </div>
        `);
      }
    }).addTo(map);
    aquiferLayer.bringToFront();

    const wellLayers = {
      included: L.layerGroup().addTo(map),
      excluded: L.layerGroup().addTo(map),
      no_data: L.layerGroup().addTo(map)
    };
    state.mapWellLayers = wellLayers;

    const precipitationLayer = L.layerGroup().addTo(map);
    const precipitationIcon = L.divIcon({
      className: "precipitation-station-icon",
      html: "<span aria-hidden=\"true\">×</span>",
      iconSize: [24, 24],
      iconAnchor: [12, 12],
      tooltipAnchor: [0, -12]
    });
    data.precipitation.stations.forEach(station => {
      if (station.latitude === null || station.longitude === null) return;
      const distance = station.distance_km > 0
        ? `<div style="margin-top:5px;color:#7c3aed;font-size:11px">فاصله تا محدوده: ${formatNumber(station.distance_km, " کیلومتر")}</div>`
        : "";
      const marker = L.marker(
        [station.latitude, station.longitude],
        {
          icon: precipitationIcon,
          keyboard: true,
          title: station.name,
          zIndexOffset: 900
        }
      )
        .bindTooltip(`
          <div dir="rtl" class="min-w-44 text-right">
            <strong>${escapeHtml(station.name)}</strong>
            <div style="margin-top:6px;color:#64748b;font-size:11px">شناسه: ${escapeHtml(station.id)}</div>
            <div style="margin-top:5px;color:#64748b;font-size:11px">محدوده: ${escapeHtml(station.mahdoude || "خارج از مرزهای موجود")}</div>
            <div style="margin-top:5px;color:#64748b;font-size:11px">ارتفاع: ${formatNumber(station.elevation, " متر")}</div>
            ${distance}
          </div>
        `, { direction: "top" })
        .addTo(precipitationLayer);
      marker.on("click", () => openPrecipitationModal(station));
    });

    data.wells.forEach(well => {
      if (well.latitude === null || well.longitude === null) return;
      const colors = { included: "#087E8B", excluded: "#F59E0B", no_data: "#E76F51" };
      const color = colors[well.status] || "#64748B";
      const marker = L.circleMarker([well.latitude, well.longitude], {
        radius: well.included ? 5 : 6,
        color: "#FFFFFF",
        weight: 2,
        fillColor: color,
        fillOpacity: 1
      }).addTo(wellLayers[well.status] || wellLayers.excluded);
      const status = well.included ? "داخل محاسبات آبخوان" : well.exclusion_reason;
      marker.bindTooltip(`
        <div dir="rtl" class="min-w-40 text-right">
          <strong>${escapeHtml(well.name)}</strong>
          <div style="margin-top:6px;color:${color};font-size:11px">${escapeHtml(status)}</div>
          <div style="margin-top:5px;color:#64748b;font-size:11px">ارتفاع چاه: ${formatNumber(well.elevation, " متر")}</div>
        </div>
      `, { direction: "top", offset: [0, -5] });
      marker.on("click", () => openWellModal(well));
    });

    const syncMapLayer = (checkboxId, layer) => {
      const checkbox = document.getElementById(checkboxId);
      if (!checkbox) return;
      const update = () => {
        if (checkbox.checked && !map.hasLayer(layer)) layer.addTo(map);
        if (!checkbox.checked && map.hasLayer(layer)) map.removeLayer(layer);
      };
      checkbox.onchange = update;
      update();
    };
    syncMapLayer("showExcludedWells", wellLayers.excluded);
    syncMapLayer("showNoDataWells", wellLayers.no_data);
    syncMapLayer("showPrecipitationStations", precipitationLayer);

    L.control.layers(
      { "نقشه پایه OpenStreetMap": baseMap },
      {
        "پهنه‌های تیسن": thiessenLayer,
        "ایستگاه‌های بارش منتخب": precipitationLayer,
        "مرز آبخوان": aquiferLayer,
        "مرز محدوده": mahdoudeLayer
      },
      { collapsed: true, position: "topleft" }
    ).addTo(map);

    const bounds = mahdoudeLayer.getBounds();
    data.precipitation.stations.forEach(station => {
      if (station.latitude !== null && station.longitude !== null) {
        bounds.extend([station.latitude, station.longitude]);
      }
    });
    fitLeafletBoundsAndLockZoom(map, bounds, [24, 24]);
    window.setTimeout(() => map.invalidateSize(), 100);
  }

  function renderAquiferChart(data) {
    const chart = echarts.init(document.getElementById("aquiferChart"));
    const option = baseChartOption();
    const categories = data.hydrographs.arithmetic.map(item => item[0]);
    option.xAxis.data = categories;
    option.legend = {
      top: 4,
      right: 0,
      textStyle: { fontFamily: "Vazirmatn", fontSize: 11 },
      itemWidth: 18,
      selected: {
        "میانگین حسابی": false,
        "روند حسابی (بازه اصلی)": false,
        "روند حسابی (مقایسه‌ای)": false,
        "میانگین تیسن": true,
        "روند تیسن (بازه اصلی)": true,
        "روند تیسن (مقایسه‌ای)": true,
        "بارش ماهانه": true
      }
    };
    option.grid.top = 86;
    option.series = [
      precipitationBarSeries(data.precipitation),
      {
        name: "میانگین حسابی",
        type: "line",
        data: data.hydrographs.arithmetic.map(item => item[1]),
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 2.5, color: "#11395B" },
        itemStyle: { color: "#11395B" },
        z: 3
      },
      {
        name: "روند حسابی (بازه اصلی)",
        type: "line",
        data: data.hydrographs.arithmetic_trend.series.map(item => item[1]),
        showSymbol: false,
        silent: true,
        connectNulls: false,
        lineStyle: { width: 2, color: "#DC2626", type: "dashed", opacity: 0.8 },
        itemStyle: { color: "#DC2626" },
        z: 4
      },
      {
        name: "روند حسابی (مقایسه‌ای)",
        type: "line",
        data: alignedTrendSeries(
          data.hydrographs.arithmetic_comparison_trend,
          categories
        ),
        showSymbol: false,
        silent: true,
        connectNulls: false,
        lineStyle: { width: 2, color: "#111827", type: "dashed", opacity: 0.9 },
        itemStyle: { color: "#111827" },
        z: 5
      },
      {
        name: "میانگین تیسن",
        type: "line",
        data: data.hydrographs.thiessen.map(item => item[1]),
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 2.5, color: "#E76F51" },
        itemStyle: { color: "#E76F51" },
        z: 3
      },
      {
        name: "روند تیسن (بازه اصلی)",
        type: "line",
        data: data.hydrographs.thiessen_trend.series.map(item => item[1]),
        showSymbol: false,
        silent: true,
        connectNulls: false,
        lineStyle: { width: 2, color: "#DC2626", type: "dashed", opacity: 0.8 },
        itemStyle: { color: "#DC2626" },
        z: 4
      },
      {
        name: "روند تیسن (مقایسه‌ای)",
        type: "line",
        data: alignedTrendSeries(
          data.hydrographs.thiessen_comparison_trend,
          categories
        ),
        showSymbol: false,
        silent: true,
        connectNulls: false,
        lineStyle: { width: 2, color: "#111827", type: "dashed", opacity: 0.9 },
        itemStyle: { color: "#111827" },
        z: 5
      }
    ];
    chart.setOption(option);
    state.charts.push(chart);
    document.getElementById("aquiferTrendSummary").innerHTML = [
      trendChip("حسابی اصلی", data.hydrographs.arithmetic_trend),
      trendChip("تیسن اصلی", data.hydrographs.thiessen_trend),
      trendChip(
        "حسابی مقایسه‌ای",
        data.hydrographs.arithmetic_comparison_trend,
        "comparison"
      ),
      trendChip(
        "تیسن مقایسه‌ای",
        data.hydrographs.thiessen_comparison_trend,
        "comparison"
      )
    ].join("");
    const stationNames = data.precipitation.stations
      .map(station => station.name)
      .join("، ");
    const source = document.getElementById("precipitationSource");
    source.innerHTML = `
      <strong class="text-sky-700">${escapeHtml(data.precipitation.method_label)}</strong>
      <span> · ${faNumber.format(data.precipitation.station_count)} ایستگاه · ${escapeHtml(stationNames)}</span>
    `;
  }

  function renderAquiferNdviChart(data) {
    const element = document.getElementById("aquiferNdviChart");
    const metricSelect = document.getElementById("ndviMetric");
    if (!element || !metricSelect || element.closest(".hidden")) return;
    const metric = metricSelect.value || data.ndvi.default_metric;
    if (!state.aquiferNdviChart) {
      state.aquiferNdviChart = echarts.init(element);
      state.charts.push(state.aquiferNdviChart);
    }

    const option = baseChartOption();
    option.xAxis.data = data.hydrographs.arithmetic.map(item => item[0]);
    option.yAxis[1] = {
      type: "value",
      name: "NDVI",
      scale: true,
      nameTextStyle: {
        fontFamily: "Vazirmatn",
        fontSize: 10,
        padding: [0, 0, 8, 0],
        color: "#059669"
      },
      axisLine: { show: true, lineStyle: { color: "#10B981" } },
      axisTick: { show: true, lineStyle: { color: "#10B981" } },
      splitLine: { show: false },
      axisLabel: {
        formatter: value => faNumber.format(value),
        fontSize: 9,
        color: "#059669"
      }
    };
    option.legend = {
      top: 4,
      right: 0,
      textStyle: { fontFamily: "Vazirmatn", fontSize: 11 },
      itemWidth: 18,
      selected: {
        "میانگین حسابی": false,
        "میانگین تیسن": true,
        [`NDVI ${ndviMetricLabel(metric)}`]: true
      }
    };
    option.grid.top = 76;
    option.series = [
      ndviBarSeries(data.ndvi, metric),
      {
        name: "میانگین حسابی",
        type: "line",
        data: data.hydrographs.arithmetic.map(item => item[1]),
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 2.5, color: "#11395B" },
        itemStyle: { color: "#11395B" },
        tooltip: {
          valueFormatter: value => (
            value == null ? "بدون داده" : `${faNumber.format(value)} متر`
          )
        },
        z: 3
      },
      {
        name: "میانگین تیسن",
        type: "line",
        data: data.hydrographs.thiessen.map(item => item[1]),
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 2.5, color: "#E76F51" },
        itemStyle: { color: "#E76F51" },
        tooltip: {
          valueFormatter: value => (
            value == null ? "بدون داده" : `${faNumber.format(value)} متر`
          )
        },
        z: 3
      }
    ];
    state.aquiferNdviChart.setOption(option, true);
    state.aquiferNdviChart.resize();
  }

  function renderAquiferAetChart(data) {
    const element = document.getElementById("aquiferAetChart");
    if (!element || element.closest(".hidden")) return;
    if (!state.aquiferAetChart) {
      state.aquiferAetChart = echarts.init(element);
      state.charts.push(state.aquiferAetChart);
    }

    const option = baseChartOption();
    option.xAxis.data = data.hydrographs.arithmetic.map(item => item[0]);
    option.yAxis[1] = {
      type: "value",
      name: "AET (mm/month)",
      min: 0,
      nameTextStyle: {
        fontFamily: "Vazirmatn",
        fontSize: 10,
        padding: [0, 0, 8, 0],
        color: "#D97706"
      },
      axisLine: { show: true, lineStyle: { color: "#F59E0B" } },
      axisTick: { show: true, lineStyle: { color: "#F59E0B" } },
      splitLine: { show: false },
      axisLabel: {
        formatter: value => faNumber.format(value),
        fontSize: 9,
        color: "#D97706"
      }
    };
    option.legend = {
      top: 4,
      right: 0,
      textStyle: { fontFamily: "Vazirmatn", fontSize: 11 },
      itemWidth: 18,
      selected: {
        "میانگین حسابی": false,
        "میانگین تیسن": true,
        "AET ماهانه": true
      }
    };
    option.grid.top = 76;
    option.series = [
      aetBarSeries(data.aet),
      {
        name: "میانگین حسابی",
        type: "line",
        data: data.hydrographs.arithmetic.map(item => item[1]),
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 2.5, color: "#11395B" },
        itemStyle: { color: "#11395B" },
        tooltip: {
          valueFormatter: value => (
            value == null ? "بدون داده" : `${faNumber.format(value)} متر`
          )
        },
        z: 3
      },
      {
        name: "میانگین تیسن",
        type: "line",
        data: data.hydrographs.thiessen.map(item => item[1]),
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 2.5, color: "#E76F51" },
        itemStyle: { color: "#E76F51" },
        tooltip: {
          valueFormatter: value => (
            value == null ? "بدون داده" : `${faNumber.format(value)} متر`
          )
        },
        z: 3
      }
    ];
    state.aquiferAetChart.setOption(option, true);
    state.aquiferAetChart.resize();
  }

  function renderAquiferAnnualTable(data) {
    const container = document.getElementById("aquiferAnnualTable");
    const rows = data.annual_decline.map(row => `
      <tr>
        <td dir="ltr" class="font-bold text-navy">${row.water_year}</td>
        <td>${numberCell(row.thiessen.start_level)}</td>
        <td>${endpointCell(row.thiessen.end_level, row.thiessen_end_month)}</td>
        <td>${metricCell(row.thiessen.decline)}</td>
        <td>${metricCell(row.thiessen.cumulative_decline)}</td>
        <td>${numberCell(row.arithmetic.start_level)}</td>
        <td>${endpointCell(row.arithmetic.end_level, row.arithmetic_end_month)}</td>
        <td>${metricCell(row.arithmetic.decline)}</td>
        <td>${metricCell(row.arithmetic.cumulative_decline)}</td>
      </tr>
    `).join("");
    container.innerHTML = `
      <table class="data-table">
        <thead>
          <tr>
            <th rowspan="2">سال آبی</th>
            <th colspan="4" class="group-heading">میانگین وزنی تیسن</th>
            <th colspan="4" class="group-heading">میانگین حسابی</th>
          </tr>
          <tr>
            <th>تراز مهر شروع</th>
            <th>تراز پایان</th>
            <th>افت سالانه</th>
            <th>افت تجمعی</th>
            <th>تراز مهر شروع</th>
            <th>تراز پایان</th>
            <th>افت سالانه</th>
            <th>افت تجمعی</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="border-t border-slate-100 bg-slate-50 px-5 py-3 text-[10px] leading-5 text-slate-500">
        پایان سال به‌طور معمول مهر بعد است؛ اگر مهر موجود نباشد، شهریور به‌عنوان پایان جایگزین می‌شود.
      </div>
    `;
  }

  function wellAnnualTable(well) {
    const rows = well.annual_decline.map(row => `
      <tr>
        <td dir="ltr" class="font-bold text-navy">${row.water_year}</td>
        <td>${numberCell(row.start_level)}</td>
        <td>${endpointCell(row.end_level, row.end_month)}</td>
        <td>${metricCell(row.decline)}</td>
        <td>${metricCell(row.cumulative_decline)}</td>
      </tr>
    `).join("");
    return `
      <div class="table-scroll h-72">
        <table class="data-table">
          <thead>
            <tr>
              <th>سال آبی</th>
              <th>تراز مهر شروع</th>
              <th>تراز پایان</th>
              <th>افت سالانه</th>
              <th>افت تجمعی</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  }

  function closeWellModal() {
    const modal = document.getElementById("wellDetailModal");
    if (!modal) return;
    modal.classList.add("hidden");
    document.body.classList.remove("overflow-hidden");
    if (state.modalChart) {
      state.modalChart.dispose();
      state.modalChart = null;
    }
  }

  function closePrecipitationModal() {
    const modal = document.getElementById("precipitationDetailModal");
    if (!modal) return;
    modal.classList.add("hidden");
    document.body.classList.remove("overflow-hidden");
    if (state.precipitationModalChart) {
      state.precipitationModalChart.dispose();
      state.precipitationModalChart = null;
    }
  }

  function openPrecipitationModal(station) {
    const modal = document.getElementById("precipitationDetailModal");
    if (!modal) return;
    closeWellModal();
    closePrecipitationModal();
    const distance = station.distance_km > 0
      ? ` · فاصله تا محدوده: ${formatNumber(station.distance_km, " کیلومتر")}`
      : "";
    document.getElementById("precipitationModalTitle").textContent = station.name;
    document.getElementById("precipitationModalMeta").textContent =
      `شناسه: ${station.id} · ارتفاع: ${formatNumber(station.elevation, " متر")}${distance}`;
    modal.classList.remove("hidden");
    document.body.classList.add("overflow-hidden");

    window.requestAnimationFrame(() => {
      const element = document.getElementById("precipitationModalChart");
      if (!element) return;
      state.precipitationModalChart = echarts.init(element);
      const option = baseChartOption();
      option.tooltip.valueFormatter = value =>
        value == null ? "بدون داده" : `${faNumber.format(value)} میلی‌متر`;
      option.grid = { top: 62, right: 64, bottom: 58, left: 64 };
      option.xAxis.data = station.series.map(item => item[0]);
      option.yAxis = [{
        type: "value",
        name: "بارش ماهانه (میلی‌متر)",
        min: 0,
        nameTextStyle: { fontFamily: "Vazirmatn", fontSize: 10, padding: [0, 0, 8, 0] },
        splitLine: { lineStyle: { color: "#E9EFF2", type: "dashed" } },
        axisLabel: { formatter: value => faNumber.format(value), fontSize: 10 }
      }];
      option.series = [{
        name: "بارش ماهانه",
        type: "bar",
        data: station.series.map(item => item[1]),
        barMaxWidth: 22,
        itemStyle: {
          color: "#0EA5E9",
          borderColor: "#0284C7",
          borderWidth: 0.8,
          borderRadius: [5, 5, 0, 0]
        },
        emphasis: { itemStyle: { color: "#087E8B" } }
      }];
      state.precipitationModalChart.setOption(option);
    });
  }

  function openWellModal(well) {
    const modal = document.getElementById("wellDetailModal");
    if (!modal) return;
    closeWellModal();
    const suffix = well.name_suffix > 1 ? ` (${faNumber.format(well.name_suffix)})` : "";
    const status = well.included ? "داخل محاسبات آبخوان" : well.exclusion_reason || "خارج از محاسبات";
    document.getElementById("wellModalTitle").textContent = `${well.name}${suffix}`;
    document.getElementById("wellModalMeta").textContent =
      `${status} · ارتفاع چاه: ${formatNumber(well.elevation, " متر")}`;
    document.getElementById("wellModalTrend").innerHTML = [
      trendChip("شیب بازه اصلی", well.trend),
      trendChip("شیب بازه مقایسه‌ای", well.comparison_trend, "comparison")
    ].join(" ");
    document.getElementById("wellModalTable").innerHTML = wellAnnualTable(well);
    modal.querySelectorAll('[data-tab-group="modal-well"]').forEach(button => {
      button.classList.toggle("is-active", button.dataset.tab === "chart");
    });
    modal.querySelectorAll('[data-tab-panel^="modal-well-"]').forEach(panel => {
      panel.classList.toggle("hidden", panel.dataset.tabPanel !== "modal-well-chart");
    });
    modal.classList.remove("hidden");
    document.body.classList.add("overflow-hidden");

    window.requestAnimationFrame(() => {
      const element = document.getElementById("wellModalChart");
      if (!element) return;
      state.modalChart = echarts.init(element);
      const option = baseChartOption();
      const color = well.included ? "#087E8B" : "#F59E0B";
      option.xAxis.data = well.series.map(item => item[0]);
      option.legend = {
        top: 4,
        right: 8,
        textStyle: { fontFamily: "Vazirmatn", fontSize: 10 }
      };
      option.grid.top = 58;
      option.series = [
        precipitationBarSeries(state.currentData.precipitation),
        {
          name: "تراز آب",
          type: "line",
          data: well.series.map(item => item[1]),
          showSymbol: false,
          connectNulls: false,
          lineStyle: { width: 2.5, color },
          areaStyle: { color: "rgba(84, 198, 196, 0.12)" },
          itemStyle: { color },
          z: 3
        },
        {
          name: "روند بازه اصلی",
          type: "line",
          data: well.trend.series.map(item => item[1]),
          showSymbol: false,
          silent: true,
          connectNulls: false,
          lineStyle: { width: 2, color: "#DC2626", type: "dashed", opacity: 0.8 },
          itemStyle: { color: "#DC2626" },
          z: 4
        },
        {
          name: "روند بازه مقایسه‌ای",
          type: "line",
          data: alignedTrendSeries(
            well.comparison_trend,
            well.series.map(item => item[0])
          ),
          showSymbol: false,
          silent: true,
          connectNulls: false,
          lineStyle: { width: 2, color: "#111827", type: "dashed", opacity: 0.9 },
          itemStyle: { color: "#111827" },
          z: 5
        }
      ];
      state.modalChart.setOption(option);
    });
  }

  function bindWellModal() {
    document.querySelectorAll("[data-close-well-modal]").forEach(button => {
      button.onclick = closeWellModal;
    });
    document.querySelectorAll("[data-close-precipitation-modal]").forEach(button => {
      button.onclick = closePrecipitationModal;
    });
  }

  function wellCard(well, index) {
    const statuses = {
      included: ["bg-teal/10 text-teal", "داخل محاسبات"],
      excluded: ["bg-amber-100 text-amber-700", "خارج از محاسبات"],
      no_data: ["bg-coral/10 text-coral", "فاقد داده"]
    };
    const [statusClass, statusText] = statuses[well.status] || ["bg-slate-100 text-slate-500", "نامشخص"];
    const suffix = well.name_suffix > 1 ? ` (${faNumber.format(well.name_suffix)})` : "";
    return `
      <article class="panel overflow-hidden transition hover:shadow-lg">
        <header class="border-b border-slate-100 px-5 py-4">
          <div class="flex items-start justify-between gap-3">
          <div>
            <h4 class="text-sm font-bold text-navy">${escapeHtml(well.name)}${suffix}</h4>
            <div class="mt-1 text-[10px] text-slate-400">ارتفاع: ${formatNumber(well.elevation, " متر")}</div>
            ${well.exclusion_reason ? `<div class="mt-1 text-[10px] leading-5 text-amber-600">${escapeHtml(well.exclusion_reason)}</div>` : ""}
            <div class="mt-2 flex flex-wrap gap-2">
              ${trendChip("روند اصلی", well.trend)}
              ${trendChip("روند مقایسه‌ای", well.comparison_trend, "comparison")}
            </div>
          </div>
          <span class="shrink-0 rounded-full px-3 py-1 text-[10px] ${statusClass}">${statusText}</span>
          </div>
          <div class="mt-4 flex items-center justify-between gap-3">
            <span class="text-[10px] text-slate-400">نمایش اطلاعات چاه</span>
            <div class="tab-list" role="tablist" aria-label="نمای چاه ${escapeHtml(well.name)}">
              <button class="tab-button is-active" type="button" data-tab-group="well-${index}" data-tab="chart">نمودار</button>
              <button class="tab-button" type="button" data-tab-group="well-${index}" data-tab="table">جدول افت</button>
            </div>
          </div>
        </header>
        <div data-tab-panel="well-${index}-chart">
          ${well.has_range_data
            ? `<div id="well-chart-${index}" class="h-72 w-full" data-well-chart="${index}"></div>`
            : `<div class="flex h-72 items-center justify-center bg-slate-50/60 p-6 text-center text-xs leading-7 text-slate-400">
                 برای این پیزومتر در بازه انتخابی رکورد اندازه‌گیری موجود نیست.
               </div>`}
        </div>
        <div class="hidden" data-tab-panel="well-${index}-table">
          ${wellAnnualTable(well)}
        </div>
      </article>
    `;
  }

  function renderWellCharts(data) {
    const container = document.getElementById("wellCharts");
    container.innerHTML = data.wells.map(wellCard).join("");
    state.observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        const element = entry.target;
        const index = Number(element.dataset.wellChart);
        const well = data.wells[index];
        const chart = echarts.init(element);
        const option = baseChartOption();
        option.xAxis.data = well.series.map(item => item[0]);
        const color = well.included ? "#087E8B" : "#F59E0B";
        option.legend = {
          top: 4,
          right: 8,
          textStyle: { fontFamily: "Vazirmatn", fontSize: 10 }
        };
        option.grid.top = 58;
        option.series = [
          precipitationBarSeries(data.precipitation),
          {
            name: "تراز آب",
            type: "line",
            data: well.series.map(item => item[1]),
            showSymbol: false,
            connectNulls: false,
            lineStyle: {
              width: 2,
              color,
              type: well.included ? "solid" : "dashed"
            },
            areaStyle: { color: well.included ? "rgba(84, 198, 196, 0.12)" : "rgba(245, 158, 11, 0.08)" },
            itemStyle: { color },
            z: 3
          },
          {
            name: "روند بازه اصلی",
            type: "line",
            data: well.trend.series.map(item => item[1]),
            showSymbol: false,
            silent: true,
            connectNulls: false,
            lineStyle: { width: 2, color: "#DC2626", type: "dashed", opacity: 0.8 },
            itemStyle: { color: "#DC2626" },
            z: 4
          },
          {
            name: "روند بازه مقایسه‌ای",
            type: "line",
            data: alignedTrendSeries(
              well.comparison_trend,
              well.series.map(item => item[0])
            ),
            showSymbol: false,
            silent: true,
            connectNulls: false,
            lineStyle: { width: 2, color: "#111827", type: "dashed", opacity: 0.9 },
            itemStyle: { color: "#111827" },
            z: 5
          }
        ];
        chart.setOption(option);
        state.charts.push(chart);
        state.observer.unobserve(element);
      });
    }, { rootMargin: "500px 0px" });
    container.querySelectorAll("[data-well-chart]").forEach(element => state.observer.observe(element));
  }

  function renderDashboardData(data) {
    disposeVisuals();
    renderFilterControls(data);
    renderStats(data);
    bindWellModal();
    renderMap(data);
    renderAquiferChart(data);
    const ndviMetric = document.getElementById("ndviMetric");
    ndviMetric.value = data.ndvi.default_metric;
    ndviMetric.onchange = () => renderAquiferNdviChart(data);
    renderAquiferAnnualTable(data);
    renderSpatialAnalysis(data);
    renderWellCharts(data);
  }

  function switchTab(button) {
    const group = button.dataset.tabGroup;
    const tab = button.dataset.tab;
    const scope = button.closest("article");
    if (!scope || !group || !tab) return;
    scope.querySelectorAll(`[data-tab-group="${group}"]`).forEach(item => {
      item.classList.toggle("is-active", item === button);
    });
    scope.querySelectorAll(`[data-tab-panel^="${group}-"]`).forEach(panel => {
      panel.classList.toggle("hidden", panel.dataset.tabPanel !== `${group}-${tab}`);
    });
    if (tab === "chart" || tab === "ndvi" || tab === "aet") {
      const chartElement = scope.querySelector("[data-well-chart]");
      if (chartElement && state.observer) state.observer.observe(chartElement);
      if (group === "aquifer" && tab === "ndvi") {
        window.requestAnimationFrame(() => renderAquiferNdviChart(state.currentData));
      }
      if (group === "aquifer" && tab === "aet") {
        window.requestAnimationFrame(() => renderAquiferAetChart(state.currentData));
      }
      window.setTimeout(() => state.charts.forEach(chart => chart.resize()), 50);
      window.setTimeout(() => state.modalChart?.resize(), 50);
    }
  }

  async function loadDashboard(root, filters = null) {
    const aquiferId = root.dataset.aquiferId;
    if (!aquiferId) return;
    const token = ++state.requestToken;
    const button = root.querySelector("#applyAnalysisFilters");
    if (button) {
      button.disabled = true;
      button.textContent = "در حال محاسبه...";
    }
    try {
      const params = new URLSearchParams();
      if (filters) {
        params.set("start_year", filters.startYear);
        params.set("start_month", filters.startMonth);
        params.set("end_year", filters.endYear);
        params.set("end_month", filters.endMonth);
        params.set("comparison_start_year", filters.comparisonStartYear);
        params.set("comparison_start_month", filters.comparisonStartMonth);
        params.set("comparison_end_year", filters.comparisonEndYear);
        params.set("comparison_end_month", filters.comparisonEndMonth);
        params.set("continuous_only", String(filters.continuousOnly));
        params.set("manual_selection", String(filters.manualSelection));
        filters.selectedWellIds.forEach(wellId => {
          params.append("selected_well_ids", wellId);
        });
      }
      const query = params.toString() ? `?${params}` : "";
      const response = await fetch(`/api/aquifers/${encodeURIComponent(aquiferId)}${query}`);
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "دریافت اطلاعات آبخوان ناموفق بود.");
      }
      const data = await response.json();
      if (token !== state.requestToken) return;
      renderDashboardData(data);
    } catch (error) {
      console.error("Dashboard rendering failed:", error);
      window.alert(error.message);
    } finally {
      const activeButton = root.querySelector("#applyAnalysisFilters");
      if (activeButton) {
        activeButton.disabled = false;
        activeButton.innerHTML = "<span>به‌روزرسانی تحلیل</span><span aria-hidden=\"true\">←</span>";
      }
    }
  }

  function initializeDashboard(root) {
    const form = root.querySelector("#analysisFilters");
    root.querySelector("#startYear").addEventListener("change", () => renderMonthOptions("start"));
    root.querySelector("#endYear").addEventListener("change", () => renderMonthOptions("end"));
    root.querySelector("#comparisonStartYear").addEventListener(
      "change",
      () => renderMonthOptions("comparisonStart")
    );
    root.querySelector("#comparisonEndYear").addEventListener(
      "change",
      () => renderMonthOptions("comparisonEnd")
    );
    form.addEventListener("submit", event => {
      event.preventDefault();
      const startYear = Number(root.querySelector("#startYear").value);
      const startMonth = Number(root.querySelector("#startMonth").value);
      const endYear = Number(root.querySelector("#endYear").value);
      const endMonth = Number(root.querySelector("#endMonth").value);
      const comparisonStartYear = Number(
        root.querySelector("#comparisonStartYear").value
      );
      const comparisonStartMonth = Number(
        root.querySelector("#comparisonStartMonth").value
      );
      const comparisonEndYear = Number(
        root.querySelector("#comparisonEndYear").value
      );
      const comparisonEndMonth = Number(
        root.querySelector("#comparisonEndMonth").value
      );
      const monthsPerYear = state.currentData?.calendar?.months_per_year
        || monthNames.length;
      if (
        startYear * monthsPerYear + startMonth
        > endYear * monthsPerYear + endMonth
      ) {
        window.alert("تاریخ شروع باید قبل از تاریخ پایان باشد.");
        return;
      }
      const analysisStartIndex = startYear * monthsPerYear + startMonth;
      const analysisEndIndex = endYear * monthsPerYear + endMonth;
      const comparisonStartIndex = (
        comparisonStartYear * monthsPerYear + comparisonStartMonth
      );
      const comparisonEndIndex = (
        comparisonEndYear * monthsPerYear + comparisonEndMonth
      );
      if (comparisonStartIndex > comparisonEndIndex) {
        window.alert("تاریخ شروع بازه مقایسه باید قبل از تاریخ پایان باشد.");
        return;
      }
      if (
        comparisonEndIndex < analysisStartIndex
        || comparisonStartIndex > analysisEndIndex
      ) {
        window.alert("بازه مقایسه شیب باید با بازه تحلیل هم‌پوشانی داشته باشد.");
        return;
      }
      const manualSelection = root.querySelector("#manualWellSelection").checked;
      const selectedWellIds = manualSelection ? selectedManualWellIds() : [];
      if (manualSelection && !selectedWellIds.length) {
        window.alert("برای انتخاب دستی، حداقل یک چاه دارای داده را انتخاب کنید.");
        return;
      }
      loadDashboard(root, {
        startYear,
        startMonth,
        endYear,
        endMonth,
        comparisonStartYear,
        comparisonStartMonth,
        comparisonEndYear,
        comparisonEndMonth,
        continuousOnly: root.querySelector("#continuousOnly").checked,
        manualSelection,
        selectedWellIds
      });
    });
    loadDashboard(root);
  }

  document.body.addEventListener("htmx:afterSwap", event => {
    if (event.detail.target.id === "aquiferSelect") {
      event.detail.target.addEventListener("change", syncDropdownSelection);
      if (activeSelectionTab() === "dropdown") syncDropdownSelection();
      return;
    }
    if (event.detail.target.id !== "dashboardContent") return;
    const root = event.detail.target.querySelector("[data-dashboard]");
    if (root) {
      initializeDashboard(root);
      window.requestAnimationFrame(() => {
        root.querySelector("#analysisFilters")?.scrollIntoView({
          behavior: "smooth",
          block: "start"
        });
      });
    }
  });

  document.body.addEventListener("click", event => {
    const button = event.target.closest(".tab-button");
    if (button) switchTab(button);
  });

  window.addEventListener("resize", () => {
    syncSpatialMapHeaderHeights();
    state.charts.forEach(chart => chart.resize());
    state.modalChart?.resize();
    state.precipitationModalChart?.resize();
    if (state.map) {
      state.map.invalidateSize();
      refreshLeafletMinimumZoom(state.map);
    }
    if (state.selectionMap) {
      state.selectionMap.invalidateSize();
      refreshLeafletMinimumZoom(state.selectionMap);
    }
    window.requestAnimationFrame(applyHeatmapClip);
  });

  document.addEventListener("DOMContentLoaded", () => {
    initializeSelectionTabs();
    initializeAquiferSelection();
  });

  document.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      closeWellModal();
      closePrecipitationModal();
    }
  });
})();
