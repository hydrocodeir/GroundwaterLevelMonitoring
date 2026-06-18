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
    spatialSurfaceMethod: "idw",
    annualSurfaceMethod: "idw",
    ndviGroundwaterMethod: "surface_idw",
    aetGroundwaterMethod: "surface_idw",
    contourIntervalInitialized: false,
    spatialViewInitialized: false,
    modalChart: null,
    precipitationModalChart: null,
    aquiferNdviChart: null,
    aquiferAetChart: null,
    aquiferAnnualChangesChart: null,
    aquiferRiskSignalChart: null,
    aquiferScenarioChart: null,
    observer: null,
    requestToken: 0,
    currentData: null,
    aiRequestToken: 0,
    aiOptions: null,
    blockedAiProviders: {},
    chatHistory: [],
    chatAquiferId: null,
    chatContextKey: null,
    chatRequestToken: 0
  };

  const CHAT_HISTORY_STORAGE_PREFIX = "hydrocodeir.aquifer-chat-history.v1";

  const faNumber = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 2 });
  const LEAFLET_MAX_ZOOM = 14;
  const SELECTION_MAP_MAX_ZOOM = 12;
  const BASEMAP_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
  const BASEMAP_ATTRIBUTION =
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  const surfaceMethodOrder = ["idw", "ordinary_kriging", "spline"];
  const surfaceMethodLabels = {
    idw: "IDW",
    ordinary_kriging: "Ordinary Kriging",
    spline: "Thin Plate Spline"
  };
  const surfaceMethodColors = {
    idw: "#087E8B",
    ordinary_kriging: "#7C3AED",
    spline: "#F59E0B"
  };
  const surfaceMethodTrendColors = {
    idw: "#7C3AED",
    ordinary_kriging: "#0F766E",
    spline: "#DB2777"
  };
  const correctedSupportLabels = {
    fixed_thiessen: "تیسن ثابت",
    fixed_grid: "شبکه ثابت",
    fixed_arithmetic: "چاه‌های ثابت"
  };
  const correctedSupportHints = {
    fixed_thiessen: "وزن‌های تیسن یک‌بار از چاه‌های منتخب ساخته می‌شوند و در همه ماه‌ها ثابت می‌مانند؛ چاه حذف‌شده با مقدار اصلاحی وارد محاسبه می‌شود.",
    fixed_grid: "یک شبکه ثابت روی مرز آبخوان ساخته می‌شود و مقدار اصلاح‌شده چاه‌ها هر ماه روی همان سلول‌ها درون‌یابی و میانگین مساحتی می‌شود.",
    fixed_arithmetic: "مجموعه چاه‌های مبنا ثابت می‌ماند و میانگین حسابی از مقدار اصلاح‌شده همان چاه‌ها محاسبه می‌شود."
  };
  const correctedStatusLabels = {
    measured: "اندازه‌گیری‌شده",
    out_of_range_censored: "خارج از دامنه",
    retired_no_longer_measurable: "بازنشسته/غیرقابل اندازه‌گیری",
    missing: "فاقد داده",
    inactive: "غیرفعال",
    new_well_added: "چاه جدید",
    imputed: "برآوردشده",
    replacement_candidate: "گزینه جایگزین"
  };
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

  function resizeSelectionMap() {
    if (!state.selectionMap) return;
    const refresh = () => {
      state.selectionMap.invalidateSize({ animate: false, pan: false });
      refreshLeafletMinimumZoom(state.selectionMap);
    };
    refresh();
    window.requestAnimationFrame(refresh);
    [80, 220, 500].forEach(delay => {
      window.setTimeout(refresh, delay);
    });
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
      resizeSelectionMap();
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
          resizeSelectionMap();
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

  function toNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function meanValue(values) {
    const numeric = values
      .map(toNumber)
      .filter(value => value !== null);
    if (!numeric.length) return null;
    return numeric.reduce((sum, value) => sum + value, 0) / numeric.length;
  }

  function minValue(values) {
    const numeric = values
      .map(toNumber)
      .filter(value => value !== null);
    return numeric.length ? Math.min(...numeric) : null;
  }

  function maxValue(values) {
    const numeric = values
      .map(toNumber)
      .filter(value => value !== null);
    return numeric.length ? Math.max(...numeric) : null;
  }

  function aiRiskLabel(level) {
    return {
      low: "کم",
      moderate: "متوسط",
      high: "زیاد",
      critical: "بحرانی"
    }[level] || "نامشخص";
  }

  function aiRiskBadgeClass(level) {
    return {
      low: "border-emerald-200 bg-emerald-50 text-emerald-700",
      moderate: "border-amber-200 bg-amber-50 text-amber-700",
      high: "border-coral/20 bg-coral/10 text-coral",
      critical: "border-red-200 bg-red-50 text-red-700"
    }[level] || "border-slate-200 bg-slate-50 text-slate-500";
  }

  function buildAiSummaryData(data) {
    const analysis = data.time_series_analysis || {};
    const llmInput = analysis.llm_input || {};
    const trends = llmInput.trend_statistics || {};
    const groundwaterTrend = trends.groundwater_level_change || {};
    const precipitationTrend = trends.precipitation || {};
    const aetTrend = trends.aet || {};
    const ndviTrend = trends.ndvi || {};
    const irrigatedAreaTrend = trends.irrigated_area || {};
    const groundwaterValues = (data.hydrographs.piezometric_surface || data.hydrographs.thiessen)
      .map(item => toNumber(item[1]))
      .filter(value => value !== null);
    const criticalWellsCount = data.wells.filter(well => (
      well.has_range_data && well.trend?.direction === "decline"
    )).length;
    const period = analysis.period || {};
    const waterYear = period.water_year_count === 1
      ? period.start_water_year
      : `${period.start_water_year || "—"} تا ${period.end_water_year || "—"}`;
    return {
      water_year: waterYear,
      language: "fa",
      dataset_type: "groundwater_dashboard",
      groundwater_level_change_m: toNumber(data.stats.change),
      precipitation_anomaly_percent: toNumber(precipitationTrend.percentage_change),
      ndvi_change: toNumber(
        ndviTrend.start_value !== null && ndviTrend.start_value !== undefined
          && ndviTrend.end_value !== null && ndviTrend.end_value !== undefined
          ? ndviTrend.end_value - ndviTrend.start_value
          : null
      ),
      aet_change_percent: toNumber(aetTrend.percentage_change),
      critical_wells_count: criticalWellsCount,
      total_wells_count: data.stats.total_wells,
      mean_groundwater_level_m: meanValue(groundwaterValues),
      minimum_groundwater_level_m: minValue(groundwaterValues),
      maximum_groundwater_level_m: maxValue(groundwaterValues),
      selected_period: period,
      trend_statistics: trends,
      correlations: llmInput.correlations || {},
      lag_analysis: llmInput.lag_analysis || {},
      stress_indicators: llmInput.stress_indicators || {},
      agricultural_pressure: analysis.agricultural_pressure || {},
      risk_assessment: analysis.risk_assessment || llmInput.risk_assessment || {},
      driver_classification: analysis.driver_classification || {},
      five_year_scenario: data.five_year_scenario || {},
      data_context: {
        start_month: data.filters.start_month,
        start_year: data.filters.start_year,
        end_month: data.filters.end_month,
        end_year: data.filters.end_year,
        active_wells: data.stats.active_wells,
        selected_wells: data.stats.selected_wells,
        excluded_wells: data.stats.excluded_wells
      },
      selected_period_label: `${period.start_water_year || "—"} تا ${period.end_water_year || "—"}`
    };
  }

  function resetAiAnalysisCard() {
    const status = document.getElementById("aiAnalysisStatus");
    const card = document.getElementById("aiAnalysisCard");
    const button = document.getElementById("aiAnalyzeButton");
    if (status) {
      status.textContent = "ارائه‌دهنده و مدل را انتخاب کنید، سپس تحلیل را اجرا کنید.";
      status.className = "rounded-xl border border-sky-100 bg-sky-50/80 px-4 py-3 text-[10px] leading-6 text-slate-600";
    }
    if (card) card.classList.add("hidden");
    if (button) {
      button.disabled = false;
      button.innerHTML = "<span>اجرای تحلیل</span>";
    }
  }

  function selectedAiProvider() {
    const providerId = document.getElementById("aiProvider")?.value;
    return state.aiOptions?.providers?.find(provider => provider.id === providerId) || null;
  }

  function isAiProviderBlocked(providerId) {
    return Boolean(state.blockedAiProviders?.[providerId]);
  }

  function blockAiProvider(providerId) {
    if (!providerId || isAiProviderBlocked(providerId)) return;
    state.blockedAiProviders = {
      ...(state.blockedAiProviders || {}),
      [providerId]: true
    };
  }

  function firstSelectableProviderId(options, preferredProviderId) {
    const providers = options.providers || [];
    const preferred = providers.find(provider => (
      provider.id === preferredProviderId
      && provider.enabled
      && !isAiProviderBlocked(provider.id)
    ));
    if (preferred) return preferred.id;
    const fallback = providers.find(provider => provider.enabled && !isAiProviderBlocked(provider.id));
    return fallback?.id || "";
  }

  function providerUnavailableHint(providerId) {
    if (providerId === "groq") {
      return "Groq موقتاً دسترسی این حساب یا موقعیت شبکه را رد کرده است. OpenRouter یا Gemini را انتخاب کنید.";
    }
    if (providerId === "gemini") {
      return "Gemini موقتاً دسترسی این کلید، پروژه یا موقعیت شبکه را رد کرده است. OpenRouter یا Groq را انتخاب کنید.";
    }
    if (providerId === "openrouter") {
      return "OpenRouter موقتاً در این نشست در دسترس نیست. یک provider دیگر را انتخاب کنید.";
    }
    return "این provider موقتاً در دسترس نیست. یک provider دیگر را انتخاب کنید.";
  }

  function selectedModel(provider, modelId) {
    return provider?.models?.find(model => model.id === modelId) || null;
  }

  function providerModelHint(provider) {
    if (!provider) return "";
    if (provider.id === "groq") {
      return "مدل‌های Groq از سهمیه Free Tier حساب شما استفاده می‌کنند و محدودیت نرخ دارند.";
    }
    if (provider.id === "gemini") {
      return "Gemini 3.5 Flash در Free Tier ورودی و خروجی رایگان دارد و محدودیت نرخ حساب اعمال می‌شود.";
    }
    return "مدل‌های دارای برچسب رایگان هزینه توکن ندارند؛ دسترسی و ظرفیت آن‌ها ممکن است تغییر کند.";
  }

  function joinHints(...items) {
    return items.filter(Boolean).join(" ");
  }

  function updateAiModelHint() {
    const modelSelect = document.getElementById("aiModel");
    const hint = document.getElementById("aiModelHint");
    const provider = selectedAiProvider();
    if (!modelSelect || !hint || !provider?.enabled || isAiProviderBlocked(provider.id)) return;
    const model = selectedModel(provider, modelSelect.value);
    hint.textContent = joinHints(model?.usage_hint, providerModelHint(provider));
  }

  function syncAiModelOptions() {
    const modelSelect = document.getElementById("aiModel");
    const hint = document.getElementById("aiModelHint");
    const analyzeButton = document.getElementById("aiAnalyzeButton");
    const provider = selectedAiProvider();
    if (!modelSelect || !hint || !analyzeButton) return;
    modelSelect.innerHTML = "";
    if (!provider?.enabled || isAiProviderBlocked(provider.id)) {
      modelSelect.disabled = true;
      analyzeButton.disabled = true;
      hint.textContent = provider
        ? providerUnavailableHint(provider.id)
        : "برای استفاده از این ارائه‌دهنده، کلید API آن را در فایل .env وارد و سرور را restart کنید.";
      return;
    }
    provider.models.forEach(model => {
      const option = document.createElement("option");
      option.value = model.id;
      option.textContent = `${model.label}${model.free ? " · رایگان" : ""}`;
      option.selected = model.id === provider.default_model;
      modelSelect.appendChild(option);
    });
    modelSelect.disabled = !provider.models.length;
    analyzeButton.disabled = !provider.models.length;
    updateAiModelHint();
  }

  function renderAiOptions(options) {
    const providerSelect = document.getElementById("aiProvider");
    state.aiOptions = options;
    if (providerSelect) {
      const previousProvider = providerSelect.value || options.default_provider;
      const selectedProviderId = firstSelectableProviderId(options, previousProvider);
      providerSelect.innerHTML = "";
      (options.providers || []).forEach(provider => {
        const blocked = isAiProviderBlocked(provider.id);
        const selectable = provider.enabled && !blocked;
        const option = document.createElement("option");
        option.value = provider.id;
        option.disabled = !selectable;
        option.textContent = `${provider.label}${provider.enabled ? "" : " · کلید تنظیم نشده"}${blocked ? " · موقتاً غیرفعال" : ""}`;
        option.selected = provider.id === selectedProviderId;
        providerSelect.appendChild(option);
      });
      if (selectedProviderId) {
        providerSelect.value = selectedProviderId;
      }
      syncAiModelOptions();
    }
    renderChatAiOptions(options);
  }

  async function loadAiOptions() {
    if (state.aiOptions) {
      renderAiOptions(state.aiOptions);
      return;
    }
    const status = document.getElementById("aiAnalysisStatus")
      || document.getElementById("aquiferChatStatus");
    try {
      const response = await fetch("/api/ai/options");
      const options = await response.json().catch(() => ({}));
      if (!response.ok || options.status !== "success") {
        throw new Error(options.message || "دریافت تنظیمات AI ناموفق بود.");
      }
      renderAiOptions(options);
      const hasEnabledProvider = options.providers?.some(provider => provider.enabled);
      if (!hasEnabledProvider && status) {
        status.textContent = "هیچ کلید API فعالی پیدا نشد. کلید OpenRouter، Gemini یا Groq را در فایل .env تنظیم کنید.";
        status.className = "rounded-xl border border-amber-100 bg-amber-50/80 px-4 py-3 text-[10px] leading-6 text-amber-700";
        status.classList.remove("hidden");
      }
    } catch (error) {
      if (status) {
        status.textContent = error.message || "دریافت تنظیمات AI ناموفق بود.";
        status.className = "rounded-xl border border-red-100 bg-red-50/80 px-4 py-3 text-[10px] leading-6 text-red-700";
        status.classList.remove("hidden");
      }
    }
  }

  function selectedChatProvider() {
    const providerId = document.getElementById("aquiferChatProvider")?.value;
    return state.aiOptions?.providers?.find(provider => provider.id === providerId) || null;
  }

  function syncChatModelOptions() {
    const modelSelect = document.getElementById("aquiferChatModel");
    const hint = document.getElementById("aquiferChatModelHint");
    const sendButton = document.getElementById("aquiferChatSend");
    const provider = selectedChatProvider();
    if (!modelSelect || !sendButton) return;
    modelSelect.innerHTML = "";
    if (!provider?.enabled || isAiProviderBlocked(provider.id)) {
      modelSelect.disabled = true;
      sendButton.disabled = true;
      if (hint) hint.textContent = provider ? providerUnavailableHint(provider.id) : "";
      return;
    }
    provider.models.forEach(model => {
      const option = document.createElement("option");
      option.value = model.id;
      option.textContent = `${model.label}${model.free ? " · رایگان" : ""}`;
      option.selected = model.id === provider.default_model;
      modelSelect.appendChild(option);
    });
    modelSelect.disabled = !provider.models.length;
    sendButton.disabled = !provider.models.length;
    updateChatModelHint();
  }

  function updateChatModelHint() {
    const modelSelect = document.getElementById("aquiferChatModel");
    const hint = document.getElementById("aquiferChatModelHint");
    const provider = selectedChatProvider();
    if (!modelSelect || !hint || !provider?.enabled || isAiProviderBlocked(provider.id)) return;
    const model = selectedModel(provider, modelSelect.value);
    hint.textContent = joinHints(model?.usage_hint, providerModelHint(provider));
  }

  function renderChatAiOptions(options) {
    const providerSelect = document.getElementById("aquiferChatProvider");
    if (!providerSelect) return;
    const previousProvider = providerSelect.value || options.default_provider;
    const selectedProviderId = firstSelectableProviderId(options, previousProvider);
    providerSelect.innerHTML = "";
    (options.providers || []).forEach(provider => {
      const blocked = isAiProviderBlocked(provider.id);
      const selectable = provider.enabled && !blocked;
      const option = document.createElement("option");
      option.value = provider.id;
      option.disabled = !selectable;
      option.textContent = `${provider.label}${provider.enabled ? "" : " · غیرفعال"}${blocked ? " · موقتاً غیرفعال" : ""}`;
      option.selected = provider.id === selectedProviderId;
      providerSelect.appendChild(option);
    });
    if (selectedProviderId) {
      providerSelect.value = selectedProviderId;
    }
    syncChatModelOptions();
  }

  function appendAquiferChatMessage(role, text, meta = "") {
    const messages = document.getElementById("aquiferChatMessages");
    if (!messages) return null;
    const message = document.createElement("div");
    message.className = `aquifer-chat-message ${role}`;
    const content = document.createElement("div");
    content.textContent = text;
    message.appendChild(content);
    if (meta) {
      const metadata = document.createElement("div");
      metadata.className = "aquifer-chat-message-meta";
      metadata.textContent = meta;
      message.appendChild(metadata);
    }
    messages.appendChild(message);
    messages.scrollTop = messages.scrollHeight;
    return message;
  }

  function chatHistoryStorageKey(contextKey) {
    return `${CHAT_HISTORY_STORAGE_PREFIX}:${contextKey}`;
  }

  function getLocalStorage() {
    try {
      return window.localStorage;
    } catch (error) {
      return null;
    }
  }

  function normalizeChatHistory(history) {
    if (!Array.isArray(history)) return [];
    return history
      .filter(message => (
        message
        && (message.role === "user" || message.role === "assistant")
        && typeof message.content === "string"
        && message.content.trim()
      ))
      .map(message => ({
        role: message.role,
        content: message.content.trim()
      }))
      .slice(-10);
  }

  function loadAquiferChatHistory(contextKey) {
    const storage = getLocalStorage();
    if (!contextKey || !storage) return [];
    try {
      const stored = storage.getItem(chatHistoryStorageKey(contextKey));
      if (!stored) return [];
      return normalizeChatHistory(JSON.parse(stored));
    } catch (error) {
      return [];
    }
  }

  function saveAquiferChatHistory(contextKey, history) {
    const storage = getLocalStorage();
    if (!contextKey || !storage) return;
    try {
      storage.setItem(
        chatHistoryStorageKey(contextKey),
        JSON.stringify(normalizeChatHistory(history))
      );
    } catch (error) {
      // Ignore storage limits or private-mode failures.
    }
  }

  function clearAquiferChatHistory(contextKey) {
    const storage = getLocalStorage();
    if (!contextKey || !storage) return;
    try {
      storage.removeItem(chatHistoryStorageKey(contextKey));
    } catch (error) {
      // Ignore storage failures.
    }
  }

  function resetAquiferChat(data) {
    const widget = document.getElementById("aquiferChatWidget");
    const title = document.getElementById("aquiferChatTitle");
    if (!widget || !data?.id) return;
    const filters = data.filters || {};
    const contextKey = JSON.stringify([
      data.id,
      filters.start_year,
      filters.start_month,
      filters.end_year,
      filters.end_month,
      Boolean(filters.continuous_only),
      Boolean(filters.manual_selection),
      filters.selected_well_ids || [],
      filters.storage_coefficient,
      filters.surface_interpolation_methods || [],
      filters.surface_interpolation_method
    ]);
    const changedContext = state.chatContextKey !== contextKey;
    state.chatAquiferId = data.id;
    state.chatContextKey = contextKey;
    widget.classList.remove("hidden");
    if (title) title.textContent = `آبخوان ${data.aquifer}`;
    if (!changedContext) return;
    state.chatRequestToken += 1;
    state.chatHistory = loadAquiferChatHistory(contextKey);
    const messages = document.getElementById("aquiferChatMessages");
    if (messages) messages.innerHTML = "";
    if (state.chatHistory.length === 0) {
      appendAquiferChatMessage(
        "assistant",
        `درباره آبخوان ${data.aquifer}، روند تراز، سال‌های آبی یا پیزومترهای آن سؤال کنید.`
      );
    } else {
      appendAquiferChatMessage(
        "assistant",
        "گفتگوی قبلی این آبخوان بازیابی شد."
      );
      state.chatHistory.forEach(message => {
        appendAquiferChatMessage(message.role, message.content);
      });
    }
    const status = document.getElementById("aquiferChatStatus");
    status?.classList.add("hidden");
  }

  function clearAquiferChat() {
    if (!state.currentData) return;
    state.chatHistory = [];
    state.chatRequestToken += 1;
    clearAquiferChatHistory(state.chatContextKey);
    const messages = document.getElementById("aquiferChatMessages");
    if (messages) messages.innerHTML = "";
    appendAquiferChatMessage(
      "assistant",
      `گفتگو پاک شد. سؤال جدیدتان درباره آبخوان ${state.currentData.aquifer} را بنویسید.`
    );
  }

  function toggleAquiferChat(forceOpen = null) {
    const panel = document.getElementById("aquiferChatPanel");
    const toggle = document.getElementById("aquiferChatToggle");
    if (!panel || !toggle) return;
    const shouldOpen = forceOpen ?? panel.classList.contains("hidden");
    panel.classList.toggle("hidden", !shouldOpen);
    toggle.setAttribute("aria-expanded", String(shouldOpen));
    if (shouldOpen) {
      loadAiOptions();
      window.setTimeout(() => document.getElementById("aquiferChatInput")?.focus(), 50);
    }
  }

  function aquiferChatErrorMessage(error, provider) {
    const message = error?.message || "گفتگو با AI ناموفق بود.";
    const forbidden = /HTTP 403|not permitted|Forbidden|permission denied/i.test(message);
    if (forbidden && provider === "groq") {
      return "Groq دسترسی این حساب یا موقعیت شبکه را رد کرده است. یک provider دیگر انتخاب کنید.";
    }
    if (forbidden && provider === "gemini") {
      return "Gemini دسترسی این کلید، پروژه یا موقعیت شبکه را رد کرده است. یک provider دیگر انتخاب کنید.";
    }
    return message;
  }

  async function sendAquiferChatMessage() {
    const input = document.getElementById("aquiferChatInput");
    const sendButton = document.getElementById("aquiferChatSend");
    const status = document.getElementById("aquiferChatStatus");
    const provider = document.getElementById("aquiferChatProvider")?.value;
    const model = document.getElementById("aquiferChatModel")?.value;
    const question = input?.value.trim();
    if (!state.currentData || !question || !provider || !model) return;

    const previousHistory = state.chatHistory.slice(-10);
    appendAquiferChatMessage("user", question);
    if (input) input.value = "";
    const pending = appendAquiferChatMessage("assistant pending", "در حال بررسی داده‌های آبخوان...");
    const token = ++state.chatRequestToken;
    if (sendButton) sendButton.disabled = true;
    status?.classList.add("hidden");

    const filters = state.currentData.filters || {};
    try {
      const response = await fetch("/api/ai/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          aquifer_id: state.currentData.id,
          language: "fa",
          provider,
          model,
          question,
          history: previousHistory,
          filters: {
            start_year: filters.start_year,
            start_month: filters.start_month,
            end_year: filters.end_year,
            end_month: filters.end_month,
            continuous_only: Boolean(filters.continuous_only),
            manual_selection: Boolean(filters.manual_selection),
            selected_well_ids: filters.selected_well_ids || [],
            storage_coefficient: filters.storage_coefficient,
            surface_interpolation_methods: filters.surface_interpolation_methods || [],
            surface_interpolation_method: filters.surface_interpolation_method,
            corrected_support_method: filters.corrected_support_method || "fixed_thiessen"
          }
        })
      });
      const result = await response.json().catch(() => ({}));
      if (token !== state.chatRequestToken) return;
      if (!response.ok || result.status !== "success") {
        throw new Error(result.message || "گفتگو با AI ناموفق بود.");
      }
      pending?.remove();
      appendAquiferChatMessage(
        "assistant",
        result.answer,
        `${result.provider} · ${result.model}`
      );
      state.chatHistory = [
        ...previousHistory,
        { role: "user", content: question },
        { role: "assistant", content: result.answer }
      ].slice(-10);
      saveAquiferChatHistory(state.chatContextKey, state.chatHistory);
    } catch (error) {
      if (token !== state.chatRequestToken) return;
      pending?.remove();
      const forbidden = /HTTP 403|not permitted|Forbidden|permission denied/i.test(error.message || "");
      if (forbidden) {
        blockAiProvider(provider);
        if (state.aiOptions) {
          renderAiOptions(state.aiOptions);
        }
      }
      appendAquiferChatMessage(
        "assistant error",
        aquiferChatErrorMessage(error, provider)
      );
    } finally {
      if (token === state.chatRequestToken && sendButton) {
        sendButton.disabled = false;
      }
    }
  }

  function initializeAquiferChat() {
    document.getElementById("aquiferChatToggle")?.addEventListener("click", () => {
      toggleAquiferChat();
    });
    document.getElementById("aquiferChatClose")?.addEventListener("click", () => {
      toggleAquiferChat(false);
    });
    document.getElementById("aquiferChatClear")?.addEventListener("click", clearAquiferChat);
    document.getElementById("aquiferChatProvider")?.addEventListener(
      "change",
      syncChatModelOptions
    );
    document.getElementById("aquiferChatModel")?.addEventListener("change", updateChatModelHint);
    document.getElementById("aquiferChatForm")?.addEventListener("submit", event => {
      event.preventDefault();
      sendAquiferChatMessage();
    });
    document.getElementById("aquiferChatInput")?.addEventListener("keydown", event => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        document.getElementById("aquiferChatForm")?.requestSubmit();
      }
    });
  }

  function closeAiModal() {
    const modal = document.getElementById("aiAnalysisModal");
    if (!modal) return;
    modal.classList.add("hidden");
    document.body.classList.remove("overflow-hidden");
  }

  function openAiModal() {
    const modal = document.getElementById("aiAnalysisModal");
    if (!modal || !state.currentData) return;
    closeWellModal();
    closePrecipitationModal();
    modal.classList.remove("hidden");
    document.body.classList.add("overflow-hidden");
    loadAiOptions();
  }

  function renderAiAnalysisResult(result, summaryData) {
    const card = document.getElementById("aiAnalysisCard");
    const status = document.getElementById("aiAnalysisStatus");
    const provider = document.getElementById("aiAnalysisProvider");
    const model = document.getElementById("aiAnalysisModel");
    const risk = document.getElementById("aiAnalysisRisk");
    const text = document.getElementById("aiAnalysisText");
    const meta = document.getElementById("aiAnalysisMeta");
    const findings = document.getElementById("aiAnalysisFindings");
    const recommendations = document.getElementById("aiAnalysisRecommendations");
    const uncertainty = document.getElementById("aiAnalysisUncertainty");
    if (!card || !status || !provider || !model || !risk || !text || !meta || !findings || !recommendations || !uncertainty) return;

    provider.textContent = result.provider || "—";
    model.textContent = result.model || "—";
    risk.textContent = aiRiskLabel(result.risk_level);
    risk.className = `rounded-full px-3 py-1 text-[10px] font-bold ${aiRiskBadgeClass(result.risk_level)}`;
    text.textContent = result.analysis || "—";

    meta.innerHTML = [
      ["بازه", summaryData.selected_period_label || "—"],
      ["خطر پیش‌محاسبه", aiRiskLabel(result.precomputed_risk_level)],
      ["چاه‌های کل", formatNumber(summaryData.total_wells_count)],
      ["چاه‌های بحرانی", formatNumber(summaryData.critical_wells_count)],
      ["تغییر تراز", formatSignedNumber(summaryData.groundwater_level_change_m, " m")],
      ["تغییر بارش", formatSignedNumber(summaryData.precipitation_anomaly_percent, "%")],
      ["تغییر NDVI", formatSignedNumber(summaryData.ndvi_change)],
      ["تغییر AET", formatSignedNumber(summaryData.aet_change_percent, "%")]
    ].map(([label, value]) => (
      `<div class="flex items-start justify-between gap-3"><span>${escapeHtml(label)}</span><strong class="text-navy">${escapeHtml(value)}</strong></div>`
    )).join("");

    const renderList = (items, emptyLabel) => {
      if (!items.length) {
        return `<li class="rounded-lg border border-dashed border-slate-200 px-3 py-2 text-slate-400">${escapeHtml(emptyLabel)}</li>`;
      }
      return items.map(item => (
        `<li class="rounded-lg border border-slate-100 bg-white px-3 py-2">${escapeHtml(item)}</li>`
      )).join("");
    };

    findings.innerHTML = renderList(result.key_findings || [], "یافته‌ای ارائه نشده است.");
    recommendations.innerHTML = renderList(result.recommendations || [], "پیشنهادی ارائه نشده است.");
    uncertainty.textContent = result.uncertainty_note || "—";
    status.textContent = `گزارش توسط ${result.provider || "provider"} با مدل ${result.model || "model"} تولید شد.`;
    status.className = "rounded-xl border border-emerald-100 bg-emerald-50/80 px-4 py-3 text-[10px] leading-6 text-emerald-700";
    card.classList.remove("hidden");
  }

  async function analyzeWithAi(root) {
    const button = root.querySelector("#aiAnalyzeButton");
    const language = root.querySelector("#aiLanguage")?.value || "fa";
    const provider = root.querySelector("#aiProvider")?.value;
    const model = root.querySelector("#aiModel")?.value;
    if (!state.currentData) return;
    if (!provider || !model) {
      const status = document.getElementById("aiAnalysisStatus");
      if (status) {
        status.textContent = "ابتدا یک ارائه‌دهنده و مدل فعال انتخاب کنید.";
        status.className = "rounded-xl border border-amber-100 bg-amber-50/80 px-4 py-3 text-[10px] leading-6 text-amber-700";
      }
      return;
    }
    const summaryData = buildAiSummaryData(state.currentData);
    const waterYear = summaryData.water_year || summaryData.selected_period_label || "—";
    const payload = {
      language,
      provider,
      model,
      dataset_type: "groundwater_dashboard",
      water_year: waterYear,
      summary_data: summaryData
    };
    const token = ++state.aiRequestToken;
    if (button) {
      button.disabled = true;
      button.innerHTML = "<span>در حال تحلیل...</span>";
    }
    const status = document.getElementById("aiAnalysisStatus");
    const card = document.getElementById("aiAnalysisCard");
    if (status) {
      status.textContent = "در حال ارسال خلاصهٔ تحلیلی به موتور AI...";
      status.className = "rounded-xl border border-sky-100 bg-sky-50/80 px-4 py-3 text-[10px] leading-6 text-sky-700";
    }
    if (card) card.classList.add("hidden");
    try {
      const response = await fetch("/api/ai/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await response.json().catch(() => ({}));
      if (token !== state.aiRequestToken) return;
      if (!response.ok || data.status !== "success") {
        throw new Error(data.message || "تحلیل AI ناموفق بود.");
      }
      renderAiAnalysisResult(data, summaryData);
    } catch (error) {
      if (token !== state.aiRequestToken) return;
      const provider = root.querySelector("#aiProvider")?.value;
      const forbidden = /HTTP 403|not permitted|Forbidden|permission denied/i.test(error.message || "");
      if (forbidden) {
        blockAiProvider(provider);
        if (state.aiOptions) {
          renderAiOptions(state.aiOptions);
        }
      }
      if (status) {
        status.textContent = forbidden && provider === "groq"
          ? "Groq دسترسی این حساب یا موقعیت شبکه را با خطای 403 رد کرده است. از OpenRouter استفاده کنید یا وضعیت دسترسی حساب Groq را در کنسول آن بررسی کنید."
          : forbidden && provider === "gemini"
            ? "Gemini دسترسی این کلید یا پروژه را رد کرده است. فعال بودن Gemini API و محدودیت‌های کلید در Google AI Studio را بررسی کنید."
            : error.message || "تحلیل AI ناموفق بود.";
        status.className = "rounded-xl border border-red-100 bg-red-50/80 px-4 py-3 text-[10px] leading-6 text-red-700";
      }
      if (card) card.classList.add("hidden");
    } finally {
      if (token === state.aiRequestToken && button) {
        button.disabled = false;
        button.innerHTML = "<span>اجرای تحلیل</span>";
      }
    }
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

  function groundwaterMethodLabel(method, compact = false) {
    if (method === "piezometric_surface") {
      return compact ? "سطح درون‌یابی" : "میانگین مساحتی سطح پیزومتریک";
    }
    if (method === "arithmetic") return compact ? "حسابی" : "میانگین حسابی";
    return compact ? "تیسن" : "میانگین وزنی تیسن";
  }

  function surfaceHydrographLabel(data, compact = false) {
    const method = primarySurfaceMethod(data);
    const label = surfaceMethodLabel(data, method) || data?.piezometric_surface?.short_label || "سطح پیزومتریک";
    if (!compact) return label;
    return label
      .replace("سطح پیزومتریک ", "سطح ")
      .replace("Ordinary Kriging", "Kriging")
      .replace("Thin Plate Spline", "Spline");
  }

  function surfaceMethodLabel(data, method, compact = false) {
    const label = data?.surface_methods?.[method]?.metadata?.short_label
      || data?.piezometric_surface?.short_label
      || surfaceMethodLabels[method]
      || method;
    if (!compact) return label;
    return label
      .replace("سطح پیزومتریک ", "سطح ")
      .replace("Ordinary Kriging", "Kriging")
      .replace("Thin Plate Spline", "Spline");
  }

  function primarySurfaceMethod(data) {
    const methods = selectedSurfaceMethods(data);
    return methods[0] || "idw";
  }

  function currentAnnualSurfaceMethod(data) {
    const methods = annualDeclineMethods(data).map(method => method.key);
    if (methods.includes(state.annualSurfaceMethod)) {
      return state.annualSurfaceMethod;
    }
    return methods[0] || "thiessen";
  }

  function selectedSurfaceMethods(data) {
    const filters = data?.filters || {};
    const methods = Array.isArray(filters.surface_interpolation_methods)
      ? filters.surface_interpolation_methods.filter(Boolean)
      : [];
    const fallback = filters.surface_interpolation_method || "idw";
    const requested = methods.length ? methods : [fallback];
    const normalized = [];
    requested.forEach(method => {
      if (surfaceMethodOrder.includes(method) && !normalized.includes(method)) {
        normalized.push(method);
      }
    });
    if (!normalized.includes("idw")) {
      normalized.unshift("idw");
    }
    return surfaceMethodOrder.filter(method => normalized.includes(method));
  }

  function surfaceMethodPayload(data, method) {
    return data?.surface_methods?.[method] || (
      method === primarySurfaceMethod(data)
        ? {
            metadata: data?.piezometric_surface || {},
            series: data?.hydrographs?.piezometric_surface || [],
            trend: data?.hydrographs?.piezometric_surface_trend || {},
            comparison_trend: data?.hydrographs?.piezometric_surface_comparison_trend || null,
            annual_decline: data?.annual_decline || [],
            five_year_scenario: data?.five_year_scenario?.piezometric_surface || {}
          }
        : null
    );
  }

  function annualRowsForPayload(rows, method) {
    return (rows || []).map(row => ({
      water_year: row.water_year,
      start_level: row[method]?.start_level ?? null,
      end_level: row[method]?.end_level ?? null,
      end_month: row[`${method}_end_month`] ?? row[method]?.end_month ?? null,
      decline: row[method]?.decline ?? null,
      cumulative_decline: row[method]?.cumulative_decline ?? null,
      storage_change_mcm: row[method]?.storage_change_mcm ?? null,
      cumulative_storage_change_mcm: row[method]?.cumulative_storage_change_mcm ?? null
    }));
  }

  function annualDeclineMethods(data) {
    const methods = [
      {
        key: "thiessen",
        label: "تیسن خام",
        color: "#E76F51",
        rows: annualRowsForPayload(data?.annual_decline, "thiessen")
      },
      {
        key: "arithmetic",
        label: "حسابی خام",
        color: "#11395B",
        rows: annualRowsForPayload(data?.annual_decline, "arithmetic")
      }
    ];
    selectedSurfaceMethods(data).forEach(method => {
      const payload = surfaceMethodPayload(data, method);
      if (!payload?.annual_decline) return;
      methods.push({
        key: `surface_${method}`,
        label: `${surfaceMethodLabel(data, method, true)} خام`,
        color: surfaceMethodColor(method),
        rows: payload.annual_decline || []
      });
    });
    const correctedAnnual = data?.corrected?.annual_decline || {};
    [
      ["corrected_thiessen", "تیسن اصلاحی", "#16A34A"],
      ["corrected_arithmetic", "حسابی اصلاحی", "#0F766E"]
    ].forEach(([key, label, color]) => {
      if (correctedAnnual[key]) {
        methods.push({ key, label, color, rows: correctedAnnual[key] });
      }
    });
    selectedSurfaceMethods(data).forEach(method => {
      const key = `corrected_${method}`;
      if (correctedAnnual[key]) {
        methods.push({
          key,
          label: `${surfaceMethodLabels[method] || method} اصلاحی`,
          color: surfaceMethodTrendColor(method),
          rows: correctedAnnual[key]
        });
      }
    });
    return methods.filter((method, index, all) => (
      method.rows?.length
      && all.findIndex(item => item.key === method.key) === index
    ));
  }

  function annualDeclineMethod(data, key) {
    const methods = annualDeclineMethods(data);
    return methods.find(method => method.key === key) || methods[0] || null;
  }

  function correctedSupportMethod(data) {
    return data?.filters?.corrected_support_method || data?.corrected?.support_method || "fixed_thiessen";
  }

  function correctedPrimaryLabel(data, compact = false) {
    const label = data?.corrected?.support_label
      || correctedSupportLabels[correctedSupportMethod(data)]
      || "هیدروگراف اصلاح‌شده";
    return compact ? label.replace("پشتیبان ثابت ", "") : label;
  }

  function correctedSeries(data, key) {
    return data?.corrected?.hydrographs?.[key] || [];
  }

  function groundwaterChartMethods(data) {
    const methods = [
      {
        key: "arithmetic",
        label: "میانگین حسابی",
        color: "#11395B",
        series: data?.hydrographs?.arithmetic || []
      },
      {
        key: "thiessen",
        label: "میانگین تیسن",
        color: "#E76F51",
        series: data?.hydrographs?.thiessen || []
      }
    ];
    selectedSurfaceMethods(data).forEach(method => {
      const payload = surfaceMethodPayload(data, method);
      if (!payload?.series?.length) return;
      methods.push({
        key: `surface_${method}`,
        label: surfaceMethodLabel(data, method, true),
        color: surfaceMethodColor(method),
        series: payload.series || []
      });
    });
    [
      ["corrected_arithmetic", "اصلاح‌شده حسابی", "#0F766E"],
      ["corrected_thiessen", "اصلاح‌شده تیسن", "#16A34A"]
    ].forEach(([key, label, color]) => {
      const series = correctedSeries(data, key);
      if (series.length) {
        methods.push({ key, label, color, series });
      }
    });
    selectedSurfaceMethods(data).forEach(method => {
      const key = `corrected_${method}`;
      const series = correctedSeries(data, key);
      if (!series.length) return;
      methods.push({
        key,
        label: `اصلاح‌شده ${surfaceMethodLabels[method] || method}`,
        color: surfaceMethodTrendColor(method),
        series
      });
    });
    return methods.filter((method, index, all) => (
      method.series?.length
      && all.findIndex(item => item.key === method.key) === index
    ));
  }

  function defaultGroundwaterChartMethod(data) {
    const methods = groundwaterChartMethods(data);
    return methods.find(method => method.key === "surface_idw") || methods[0] || null;
  }

  function groundwaterChartMethod(data, key) {
    const methods = groundwaterChartMethods(data);
    return methods.find(method => method.key === key)
      || methods.find(method => method.key === "surface_idw")
      || methods[0]
      || null;
  }

  function populateGroundwaterMethodSelect(select, data, selectedKey) {
    if (!select) return null;
    const methods = groundwaterChartMethods(data);
    const selected = methods.find(method => method.key === selectedKey)
      || defaultGroundwaterChartMethod(data);
    select.innerHTML = methods
      .map(method => `<option value="${method.key}">${escapeHtml(method.label)}</option>`)
      .join("");
    if (selected) {
      select.value = selected.key;
    }
    return selected;
  }

  function groundwaterLineSeries(method) {
    return {
      name: method.label,
      type: "line",
      data: (method.series || []).map(item => item[1]),
      showSymbol: false,
      connectNulls: false,
      lineStyle: { width: 2.6, color: method.color },
      itemStyle: { color: method.color },
      tooltip: {
        valueFormatter: value => (
          value == null ? "بدون داده" : `${faNumber.format(value)} متر`
        )
      },
      z: 3
    };
  }

  function correctedTrend(data, key) {
    return data?.corrected?.hydrographs?.[`${key}_trend`] || {};
  }

  function correctedComparisonTrend(data, key) {
    return data?.corrected?.hydrographs?.[`${key}_comparison_trend`] || {};
  }

  function correctedPrimarySeriesKey(data) {
    const support = correctedSupportMethod(data);
    if (support === "fixed_arithmetic") return "corrected_arithmetic";
    if (support === "fixed_grid") return `corrected_${primarySurfaceMethod(data)}`;
    return "corrected_thiessen";
  }

  function correctedStatusLabel(status) {
    return correctedStatusLabels[status] || status || "نامشخص";
  }

  function surfaceMethodColor(method) {
    return surfaceMethodColors[method] || "#087E8B";
  }

  function surfaceMethodTrendColor(method) {
    return surfaceMethodTrendColors[method] || "#7C3AED";
  }

  function trendChip(label, trend, variant = "") {
    const direction = trend?.direction || "insufficient";
    return `<span class="trend-chip ${direction} ${variant}"><b>${label}</b><span>${trendText(trend, true)}</span></span>`;
  }

  function isLegendSeriesSelected(selected, name) {
    return selected?.[name] !== false;
  }

  function renderAquiferTrendSummary(data, surfacePayloads, selected) {
    const items = [
      {
        label: "حسابی اصلی",
        seriesName: "میانگین حسابی",
        trend: data.hydrographs.arithmetic_trend
      },
      {
        label: "تیسن اصلی",
        seriesName: "میانگین تیسن",
        trend: data.hydrographs.thiessen_trend
      },
      ...(data.filters.comparison_enabled ? [
        {
          label: "حسابی مقایسه‌ای",
          seriesName: "روند حسابی (مقایسه‌ای)",
          trend: data.hydrographs.arithmetic_comparison_trend,
          variant: "comparison"
        },
        {
          label: "تیسن مقایسه‌ای",
          seriesName: "روند تیسن (مقایسه‌ای)",
          trend: data.hydrographs.thiessen_comparison_trend,
          variant: "comparison"
        }
      ] : []),
      ...surfacePayloads.flatMap(([method, payload]) => {
        const label = surfaceMethodLabel(data, method, true);
        return [
          {
            label: `${label} اصلی`,
            seriesName: label,
            trend: payload.trend
          },
          ...(data.filters.comparison_enabled && payload?.comparison_trend ? [{
            label: `${label} مقایسه‌ای`,
            seriesName: `روند ${label} (مقایسه‌ای)`,
            trend: payload.comparison_trend,
            variant: "comparison"
          }] : [])
        ];
      }),
      {
        label: "اصلاحی حسابی",
        seriesName: "اصلاح‌شده حسابی",
        trend: correctedTrend(data, "corrected_arithmetic")
      },
      {
        label: "اصلاحی تیسن",
        seriesName: "اصلاح‌شده تیسن",
        trend: correctedTrend(data, "corrected_thiessen")
      },
      ...selectedSurfaceMethods(data).map(method => ({
        label: `اصلاحی ${surfaceMethodLabels[method] || method}`,
        seriesName: `اصلاح‌شده ${surfaceMethodLabels[method] || method}`,
        trend: correctedTrend(data, `corrected_${method}`)
      }))
    ].filter(item => (
      isLegendSeriesSelected(selected, item.seriesName)
      && item.trend?.direction
      && item.trend.direction !== "insufficient"
      && item.trend.decline_per_year !== null
      && item.trend.decline_per_year !== undefined
    ));
    const summary = document.getElementById("aquiferTrendSummary");
    if (!summary) return;
    summary.innerHTML = items
      .map(item => trendChip(item.label, item.trend, item.variant || ""))
      .join("");
    summary.classList.toggle("hidden", items.length === 0);
  }

  function riskLevelLabel(level) {
    return {
      low: "کم",
      moderate: "متوسط",
      high: "زیاد",
      critical: "بحرانی",
      insufficient: "داده ناکافی"
    }[level] || "نامشخص";
  }

  function riskLevelColor(level) {
    return {
      low: "#059669",
      moderate: "#D97706",
      high: "#E76F51",
      critical: "#DC2626",
      insufficient: "#94A3B8"
    }[level] || "#64748B";
  }

  function riskBadgeClass(level) {
    return {
      low: "border-emerald-200 bg-emerald-50 text-emerald-700",
      moderate: "border-amber-200 bg-amber-50 text-amber-700",
      high: "border-coral/20 bg-coral/10 text-coral",
      critical: "border-red-200 bg-red-50 text-red-700",
      insufficient: "border-slate-200 bg-slate-50 text-slate-500"
    }[level] || "border-slate-200 bg-slate-50 text-slate-500";
  }

  function driverLabel(label) {
    return {
      "Climate Dominated": "غلبه اقلیمی",
      "Human Dominated": "غلبه انسانی/کشاورزی",
      "Mixed Influence": "اثر ترکیبی"
    }[label] || "نامشخص";
  }

  function confidenceLabel(confidence) {
    return {
      low: "کم",
      medium: "متوسط",
      high: "زیاد"
    }[confidence] || "نامشخص";
  }

  function scorePercent(value) {
    const number = toNumber(value);
    return number === null ? "—" : `${faNumber.format(number)}٪`;
  }

  function scoreBar(label, score, detail, color = "#087E8B") {
    const value = toNumber(score);
    const width = value === null ? 0 : Math.max(0, Math.min(100, value));
    return `
      <div class="rounded-xl border border-slate-200 bg-white p-3">
        <div class="flex items-center justify-between gap-3">
          <span class="text-[11px] font-bold text-navy">${label}</span>
          <span dir="ltr" class="text-xs font-bold" style="color:${color}">${scorePercent(value)}</span>
        </div>
        <div class="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
          <div class="h-full rounded-full" style="width:${width}%;background:${color}"></div>
        </div>
        <div class="mt-2 text-[10px] leading-5 text-slate-500">${detail}</div>
      </div>
    `;
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

  function thinPlateSplineBasis(distance) {
    if (distance <= 1e-12) return 0;
    const distanceSquared = distance * distance;
    return distanceSquared * Math.log(distance);
  }

  function invertMatrix(matrix) {
    const size = matrix.length;
    const augmented = matrix.map((row, rowIndex) => [
      ...row.map(value => Number(value)),
      ...Array.from({ length: size }, (_, index) => (index === rowIndex ? 1 : 0))
    ]);
    for (let pivotIndex = 0; pivotIndex < size; pivotIndex += 1) {
      let pivotRow = pivotIndex;
      for (let row = pivotIndex + 1; row < size; row += 1) {
        if (Math.abs(augmented[row][pivotIndex]) > Math.abs(augmented[pivotRow][pivotIndex])) {
          pivotRow = row;
        }
      }
      if (Math.abs(augmented[pivotRow][pivotIndex]) < 1e-12) {
        return null;
      }
      if (pivotRow !== pivotIndex) {
        [augmented[pivotIndex], augmented[pivotRow]] = [augmented[pivotRow], augmented[pivotIndex]];
      }
      const pivot = augmented[pivotIndex][pivotIndex];
      for (let column = 0; column < size * 2; column += 1) {
        augmented[pivotIndex][column] /= pivot;
      }
      for (let row = 0; row < size; row += 1) {
        if (row === pivotIndex) continue;
        const factor = augmented[row][pivotIndex];
        if (Math.abs(factor) < 1e-12) continue;
        for (let column = 0; column < size * 2; column += 1) {
          augmented[row][column] -= factor * augmented[pivotIndex][column];
        }
      }
    }
    return augmented.map(row => row.slice(size));
  }

  function multiplyMatrixVector(matrix, vector) {
    return matrix.map(row => row.reduce((sum, value, index) => (
      sum + value * vector[index]
    ), 0));
  }

  function sphericalVariogram(distance, nugget, sill, variogramRange) {
    const safeRange = Math.max(variogramRange, 1e-9);
    const ratio = Math.min(1, Math.max(0, distance / safeRange));
    const structure = distance < safeRange
      ? 1.5 * ratio - 0.5 * (ratio ** 3)
      : 1;
    return nugget + sill * structure;
  }

  function buildThinPlateSplineModel(points) {
    if (points.length < 3) return null;
    const size = points.length;
    const matrix = Array.from({ length: size + 3 }, () => (
      Array(size + 3).fill(0)
    ));
    const rhs = Array(size + 3).fill(0);
    for (let row = 0; row < size; row += 1) {
      const [x1, y1, value] = points[row];
      rhs[row] = value;
      for (let column = 0; column < size; column += 1) {
        const [x2, y2] = points[column];
        const distance = Math.hypot(x1 - x2, y1 - y2);
        matrix[row][column] = thinPlateSplineBasis(distance);
      }
      matrix[row][row] += 1e-9;
      matrix[row][size] = 1;
      matrix[row][size + 1] = x1;
      matrix[row][size + 2] = y1;
      matrix[size][row] = 1;
      matrix[size + 1][row] = x1;
      matrix[size + 2][row] = y1;
    }
    const inverse = invertMatrix(matrix);
    if (!inverse) return null;
    return {
      points,
      coefficients: multiplyMatrixVector(inverse, rhs),
      size
    };
  }

  function thinPlateSplineValue(model, longitude, latitude) {
    if (!model) return null;
    const { points, coefficients, size } = model;
    let value = coefficients[size] + coefficients[size + 1] * longitude + coefficients[size + 2] * latitude;
    for (let index = 0; index < size; index += 1) {
      const [x, y] = points[index];
      const distance = Math.hypot(longitude - x, latitude - y);
      value += coefficients[index] * thinPlateSplineBasis(distance);
    }
    return Number.isFinite(value) ? value : null;
  }

  function buildOrdinaryKrigingModel(points) {
    if (points.length < 3) return null;
    const values = points.map(point => point[2]);
    const variance = values.reduce((sum, value) => sum + value, 0) / values.length;
    const meanCentered = values.map(value => (value - variance) ** 2);
    const sill = Math.max(
      meanCentered.reduce((sum, value) => sum + value, 0) / meanCentered.length,
      1e-9
    );
    let maxDistance = 0;
    let maxSemivariance = sill;
    const size = points.length;
    for (let row = 0; row < size; row += 1) {
      for (let column = row + 1; column < size; column += 1) {
        const dx = points[row][0] - points[column][0];
        const dy = points[row][1] - points[column][1];
        const distance = Math.hypot(dx, dy);
        maxDistance = Math.max(maxDistance, distance);
        const semivariance = 0.5 * ((points[row][2] - points[column][2]) ** 2);
        maxSemivariance = Math.max(maxSemivariance, semivariance);
      }
    }
    if (maxDistance <= 1e-12) return null;
    const variogramRange = maxDistance / 2;
    const nugget = 0;
    const system = Array.from({ length: size + 1 }, () => (
      Array(size + 1).fill(0)
    ));
    for (let row = 0; row < size; row += 1) {
      for (let column = 0; column < size; column += 1) {
        const dx = points[row][0] - points[column][0];
        const dy = points[row][1] - points[column][1];
        const distance = Math.hypot(dx, dy);
        system[row][column] = row === column
          ? 0
          : sphericalVariogram(distance, nugget, maxSemivariance, variogramRange);
      }
      system[row][size] = 1;
      system[size][row] = 1;
    }
    const inverse = invertMatrix(system);
    if (!inverse) return null;
    return {
      points,
      values,
      inverse,
      nugget,
      sill: maxSemivariance,
      variogramRange
    };
  }

  function ordinaryKrigingValue(model, longitude, latitude) {
    if (!model) return null;
    const { points, values, inverse, nugget, sill, variogramRange } = model;
    for (let index = 0; index < points.length; index += 1) {
      const [x, y, value] = points[index];
      if (Math.hypot(longitude - x, latitude - y) <= 1e-12) {
        return value;
      }
    }
    const rhs = [
      ...points.map(point => sphericalVariogram(
        Math.hypot(point[0] - longitude, point[1] - latitude),
        nugget,
        sill,
        variogramRange
      )),
      1
    ];
    const weights = multiplyMatrixVector(inverse, rhs);
    const estimate = values.reduce((sum, value, index) => (
      sum + value * weights[index]
    ), 0);
    return Number.isFinite(estimate) ? estimate : null;
  }

  function buildSpatialInterpolator(points, method, idwPower = 2) {
    const uniquePoints = aggregateSpatialPoints(points);
    if (!uniquePoints.length) return null;
    if (method === "ordinary_kriging") {
      const model = buildOrdinaryKrigingModel(uniquePoints);
      if (model) {
        return {
          points: uniquePoints,
          valueAt: (longitude, latitude) => ordinaryKrigingValue(model, longitude, latitude)
        };
      }
    }
    if (method === "spline") {
      const model = buildThinPlateSplineModel(uniquePoints);
      if (model) {
        return {
          points: uniquePoints,
          valueAt: (longitude, latitude) => thinPlateSplineValue(model, longitude, latitude)
        };
      }
    }
    return {
      points: uniquePoints,
      valueAt: (longitude, latitude) => idwValue(uniquePoints, longitude, latitude, idwPower)
    };
  }

  function interpolationGrid(points, geometry, method = "idw", size = 44) {
    const interpolator = buildSpatialInterpolator(points, method, 2);
    if (!interpolator) {
      return { xCoordinates: [], yCoordinates: [], values: [] };
    }
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
          ? interpolator.valueAt(longitude, latitude)
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

  function declineSurface(points, geometry, method = "idw", size = 96) {
    const interpolator = buildSpatialInterpolator(points, method, 3);
    if (!interpolator?.points?.length) return [];
    const [minX, minY, maxX, maxY] = geometryBounds(geometry);
    const data = [];
    for (let row = 0; row < size; row += 1) {
      const latitude = minY + (maxY - minY) * row / (size - 1);
      for (let column = 0; column < size; column += 1) {
        const longitude = minX + (maxX - minX) * column / (size - 1);
        if (!pointInGeometry([longitude, latitude], geometry)) continue;
        const interpolated = interpolator.valueAt(longitude, latitude);
        if (!Number.isFinite(interpolated)) continue;
        data.push([
          longitude,
          latitude,
          interpolated,
          `پهنه ${surfaceMethodLabels[method] || method} افت سال‌به‌سال`
        ]);
      }
    }
    interpolator.points.forEach(point => {
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
    const method = document.getElementById("spatialSurfaceMethod")?.value
      || state.spatialSurfaceMethod
      || primarySurfaceMethod(data);
    state.spatialSurfaceMethod = method;
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
    const grid = levels.length ? interpolationGrid(currentPoints, geometry, method) : null;
    const contourSeries = levels.map(level => ({
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
    const contourLabels = levels.flatMap(level => {
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
    const declineSurfaceData = declineSurface(declinePoints, geometry, method);
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
          data: declineSurfaceData.map(point => ({
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
          z: 10,
          animation: false
        }
      ]
    });
    charts.decline.dispatchAction({ type: "lmapRoam" });
    window.requestAnimationFrame(applyHeatmapClip);

    const methodLabel = surfaceMethodLabel(data, method, true);
    document.getElementById("spatialMonthLabel").textContent = persianDate(month);
    document.getElementById("contourMapSummary").textContent = currentPoints.length >= 3
      ? `${methodLabel} · ${faNumber.format(currentPoints.length)} چاه · ${faNumber.format(levels.length)} خط · فاصله ${formatNumber(interval, " متر")}`
      : `${methodLabel} · ${faNumber.format(currentPoints.length)} چاه · حداقل ۳ چاه برای درون‌یابی لازم است`;
    document.getElementById("declineMapSummary").textContent = previousYearMonth
      ? `${methodLabel} · ${faNumber.format(declinePoints.length)} چاه قابل مقایسه · نسبت به ${persianDate(previousYearMonth)}`
      : "برای این ماه، مقدار ماه مشابه در سال قبل داخل بازه موجود نیست";
    const spatialStats = document.getElementById("spatialFrameStats");
    if (spatialStats) {
      spatialStats.innerHTML = [
        ["ماه جاری", persianDate(month), "مبنای خطوط تراز"],
        ["ماه مرجع", previousYearMonth ? persianDate(previousYearMonth) : "ناموجود", "همان ماه در سال قبل"],
        ["چاه‌های تراز", faNumber.format(currentPoints.length), currentPoints.length >= 3 ? "آماده درون‌یابی" : "کمتر از حداقل لازم"],
        ["چاه‌های مقایسه", faNumber.format(declinePoints.length), previousYearMonth ? "دارای داده دو سال" : "بدون مرجع سال قبل"],
        [
          "دامنه تغییر",
          declineValues.length
            ? `${formatSignedNumber(minimumDecline, " متر")} تا ${formatSignedNumber(maximumDecline, " متر")}`
            : "—",
          `${faNumber.format(rangeDeclinePoints.length)} مشاهده برای کلاس‌بندی`
        ]
      ].map(([label, value, note]) => `
        <article class="spatial-stat">
          <span>${label}</span>
          <b dir="auto">${value}</b>
          <small>${note}</small>
        </article>
      `).join("");
    }
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
    state.spatialSurfaceMethod = primarySurfaceMethod(data);
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
    const spatialSurfaceMethod = document.getElementById("spatialSurfaceMethod");
    if (spatialSurfaceMethod) {
      spatialSurfaceMethod.innerHTML = selectedSurfaceMethods(data)
        .map(method => `<option value="${method}">${escapeHtml(surfaceMethodLabel(data, method))}</option>`)
        .join("");
      spatialSurfaceMethod.value = state.spatialSurfaceMethod;
      spatialSurfaceMethod.onchange = event => {
        stopSpatialPlayback();
        state.spatialSurfaceMethod = event.target.value;
        renderSpatialFrame();
      };
    }
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
    state.spatialSurfaceMethod = "idw";
    state.annualSurfaceMethod = "idw";
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
    state.aquiferAnnualChangesChart = null;
    state.aquiferRiskSignalChart = null;
    state.aquiferScenarioChart = null;
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

  function surfaceLineSeries(data, method, values, categories, comparisonEnabled = false) {
    const label = surfaceMethodLabel(data, method, true);
    const color = surfaceMethodColor(method);
    const trendColor = surfaceMethodTrendColor(method);
    const series = [];
    if (Array.isArray(values?.series)) {
      series.push({
        name: label,
        type: "line",
        data: values.series.map(item => item[1]),
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 2.5, color },
        itemStyle: { color },
        z: 3
      });
    }
    if (Array.isArray(values?.trend?.series)) {
      series.push({
        name: `روند ${label} (بازه اصلی)`,
        type: "line",
        data: values.trend.series.map(item => item[1]),
        showSymbol: false,
        silent: true,
        connectNulls: false,
        lineStyle: { width: 2, color: trendColor, type: "dashed", opacity: 0.82 },
        itemStyle: { color: trendColor },
        z: 4
      });
    }
    if (comparisonEnabled && Array.isArray(values?.comparison_trend?.series)) {
      series.push({
        name: `روند ${label} (مقایسه‌ای)`,
        type: "line",
        data: alignedTrendSeries(values.comparison_trend, categories),
        showSymbol: false,
        silent: true,
        connectNulls: false,
        lineStyle: { width: 2, color: "#111827", type: "dashed", opacity: 0.9 },
        itemStyle: { color: "#111827" },
        z: 5
      });
    }
    return series;
  }

  function correctedHydrographSeries(data) {
    const primaryKey = correctedPrimarySeriesKey(data);
    const primaryLabel = `اصلاح‌شده ${correctedPrimaryLabel(data, true)}`;
    const series = [];
    const addLine = (key, name, color, selected = false) => {
      const values = correctedSeries(data, key);
      if (!values.length) return;
      series.push({
        name,
        type: "line",
        data: values.map(item => item[1]),
        showSymbol: false,
        connectNulls: false,
        lineStyle: {
          width: key === primaryKey ? 3 : 2,
          color,
          type: key === primaryKey ? "solid" : "dashed",
          opacity: selected || key === primaryKey ? 0.98 : 0.72
        },
        itemStyle: { color },
        z: key === primaryKey ? 7 : 4
      });
    };
    addLine("corrected_arithmetic", "اصلاح‌شده حسابی", "#0F766E");
    addLine("corrected_thiessen", "اصلاح‌شده تیسن", "#16A34A");
    surfaceMethodOrder.forEach(method => {
      addLine(
        `corrected_${method}`,
        `اصلاح‌شده ${surfaceMethodLabels[method] || method}`,
        surfaceMethodTrendColor(method)
      );
    });
    const trend = correctedTrend(data, primaryKey);
    if (Array.isArray(trend?.series)) {
      series.push({
        name: `روند ${primaryLabel}`,
        type: "line",
        data: trend.series.map(item => item[1]),
        showSymbol: false,
        silent: true,
        connectNulls: false,
        lineStyle: { width: 2.2, color: "#059669", type: "dashed", opacity: 0.85 },
        itemStyle: { color: "#059669" },
        z: 8
      });
    }
    const difference = correctedSeries(data, "raw_minus_corrected");
    if (difference.length) {
      series.push({
        name: "اختلاف خام-اصلاح‌شده",
        type: "line",
        data: difference.map(item => item[1]),
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 1.8, color: "#64748B", type: "dotted", opacity: 0.8 },
        itemStyle: { color: "#64748B" },
        z: 2
      });
    }
    return series;
  }

  function correctedStatusAreaSeries(data) {
    const rows = data?.corrected?.status_counts || [];
    if (!rows.length) return [];
    const config = [
      ["measured_count", "وضعیت: اندازه‌گیری", "rgba(8, 126, 139, 0.12)"],
      ["retired_count", "وضعیت: بازنشسته", "rgba(231, 111, 81, 0.15)"],
      ["new_well_count", "وضعیت: چاه جدید", "rgba(124, 58, 237, 0.12)"],
      ["imputed_count", "وضعیت: برآورد", "rgba(245, 158, 11, 0.13)"]
    ];
    return config.map(([key, name, color]) => ({
      name,
      type: "line",
      yAxisIndex: 2,
      stack: "well-status",
      data: rows.map(row => row[key] || 0),
      showSymbol: false,
      smooth: false,
      lineStyle: { width: 0 },
      areaStyle: { color },
      emphasis: { focus: "series" },
      tooltip: {
        valueFormatter: value => `${faNumber.format(value || 0)} ماه-چاه`
      },
      z: 0
    }));
  }

  function surfaceTrendChips(data, method, trend, variant = "") {
    const label = surfaceMethodLabel(data, method, true);
    return trendChip(`${label}${variant ? ` ${variant}` : ""}`, trend, variant === "مقایسه‌ای" ? "comparison" : "");
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
    const storageInput = document.getElementById("storageCoefficient");
    if (storageInput && data.filters.storage_coefficient != null) {
      storageInput.value = String(data.filters.storage_coefficient);
    }
    const selectedSurfaceMethodSet = new Set(
      Array.isArray(data.filters.surface_interpolation_methods)
        ? data.filters.surface_interpolation_methods
        : [data.filters.surface_interpolation_method || "idw"]
    );
    document
      .querySelectorAll("#surfaceInterpolationMethods input[type='checkbox']")
      .forEach(input => {
        const method = input.value;
        if (method === "idw") {
          input.checked = true;
          input.disabled = true;
          return;
        }
        input.checked = selectedSurfaceMethodSet.has(method);
      });
    const correctedSupportSelect = document.getElementById("correctedSupportMethod");
    if (correctedSupportSelect) {
      correctedSupportSelect.value = correctedSupportMethod(data);
      const hint = document.getElementById("correctedSupportHint");
      const updateHint = () => {
        if (hint) {
          hint.textContent = correctedSupportHints[correctedSupportSelect.value] || "";
        }
      };
      correctedSupportSelect.onchange = updateHint;
      updateHint();
    }
    const spatialSurfaceMethod = document.getElementById("spatialSurfaceMethod");
    if (spatialSurfaceMethod) {
      const methods = selectedSurfaceMethods(data);
      spatialSurfaceMethod.innerHTML = methods
        .map(method => `<option value="${method}">${escapeHtml(surfaceMethodLabel(data, method))}</option>`)
        .join("");
      spatialSurfaceMethod.value = primarySurfaceMethod(data);
    }
    const annualSurfaceMethod = document.getElementById("annualSurfaceMethod");
    if (annualSurfaceMethod) {
      const methods = annualDeclineMethods(data);
      const method = currentAnnualSurfaceMethod(data);
      annualSurfaceMethod.innerHTML = methods
        .map(item => `<option value="${item.key}">${escapeHtml(item.label)}</option>`)
        .join("");
      annualSurfaceMethod.value = method;
      state.annualSurfaceMethod = method;
    }
    const ndviGroundwaterMethod = populateGroundwaterMethodSelect(
      document.getElementById("ndviGroundwaterMethod"),
      data,
      state.ndviGroundwaterMethod
    );
    if (ndviGroundwaterMethod) {
      state.ndviGroundwaterMethod = ndviGroundwaterMethod.key;
    }
    const aetGroundwaterMethod = populateGroundwaterMethodSelect(
      document.getElementById("aetGroundwaterMethod"),
      data,
      state.aetGroundwaterMethod
    );
    if (aetGroundwaterMethod) {
      state.aetGroundwaterMethod = aetGroundwaterMethod.key;
    }
    document.getElementById("comparisonTrendEnabled").checked =
      Boolean(data.filters.comparison_enabled);
    syncComparisonTrendUI();
    renderManualWellSelector(data);
  }

  function syncComparisonTrendUI() {
    const toggle = document.getElementById("comparisonTrendEnabled");
    const panel = document.getElementById("comparisonTrendPanel");
    if (!toggle || !panel) return;
    panel.classList.toggle("hidden", !toggle.checked);
  }

  function selectedSurfaceMethodsFromForm(root) {
    const methods = Array.from(
      root.querySelectorAll("#surfaceInterpolationMethods input[type='checkbox']")
    )
      .filter(input => input.checked || input.disabled)
      .map(input => input.value)
      .filter(Boolean);
    if (!methods.includes("idw")) {
      methods.unshift("idw");
    }
    return surfaceMethodOrder.filter(method => methods.includes(method));
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
    const corrected = data.corrected || {};
    const correctedCounts = corrected.status_counts || [];
    const totalRetired = correctedCounts.reduce((sum, row) => sum + (Number(row.retired_count) || 0), 0);
    const totalImputed = correctedCounts.reduce((sum, row) => sum + (Number(row.imputed_count) || 0), 0);
    const change = stats.change;
    const changeLabel = change === null
      ? "بدون داده"
      : change < 0
        ? `${formatNumber(Math.abs(change), " متر")} افت`
        : `${formatNumber(change, " متر")} افزایش`;
    const featuredCards = [
      {
        eyebrow: "شاخص کلیدی",
        label: "تغییر دوره",
        value: changeLabel,
        note: "اختلاف اولین و آخرین مقدار موجود در بازه تحلیل",
        tone: change < 0 ? "alert" : "default"
      },
      {
        eyebrow: "شبکه تحلیلی",
        label: "چاه‌های داخل محاسبات",
        value: formatNumber(stats.selected_wells),
        note: `${formatNumber(stats.selected_sites)} ایستگاه مکانی برای تیسن و تحلیل سطح`,
        tone: "support"
      }
    ];
    const compactCards = [
      ["کل پیزومترها", formatNumber(stats.total_wells), "همه نقاط ثبت‌شده"],
      ["خارج از محاسبات", formatNumber(stats.excluded_wells), "با برچسب مجزا در نمودارها"],
      ["تعداد ماه‌ها", formatNumber(data.hydrographs.arithmetic.length), "در بازه ماهانه منتخب"],
      [
        "ضریب ذخیره",
        data.storage?.coefficient == null ? "—" : faNumber.format(data.storage.coefficient),
        data.storage?.area_km2 == null
          ? "مساحت آبخوان نامشخص"
          : `${formatNumber(data.storage.area_km2, " km²")}`
      ],
      [
        "پشتیبان اصلاح",
        formatNumber(corrected.fixed_support_well_count),
        `${correctedPrimaryLabel(data, true)} · ${formatNumber(corrected.fixed_support_site_count)} سایت`
      ],
      [
        "برآورد اصلاحی",
        formatNumber(totalImputed),
        `${formatNumber(totalRetired)} ماه-چاه بازنشسته`
      ]
    ];
    document.getElementById("statsGrid").innerHTML = `
      <div class="dashboard-stats-featured">
        ${featuredCards.map(card => `
          <article class="stat-hero-card" data-tone="${card.tone}">
            <div class="stat-hero-eyebrow">${card.eyebrow}</div>
            <div class="stat-hero-label">${card.label}</div>
            <div class="stat-hero-value">${card.value}</div>
            <div class="stat-hero-note">${card.note}</div>
          </article>
        `).join("")}
      </div>
      <div class="dashboard-stats-secondary">
        ${compactCards.map(([label, value, note]) => `
          <article class="stat-mini-card">
            <div class="stat-mini-label">${label}</div>
            <div class="stat-mini-value">${value}</div>
            <div class="stat-mini-note">${note}</div>
          </article>
        `).join("")}
      </div>
    `;
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
      const monitoringStatus = well.monitoring_status || well.status;
      const markerHtml = {
        out_of_range_censored: `<span style="display:grid;place-items:center;width:22px;height:22px;border:2px solid ${color};border-radius:999px;background:#fff;color:${color};font-size:16px;line-height:1">↓</span>`,
        retired_no_longer_measurable: `<span style="display:grid;place-items:center;width:22px;height:22px;color:#E76F51;font-size:24px;font-weight:700;line-height:1">×</span>`,
        new_well_added: `<span style="display:grid;place-items:center;width:22px;height:22px;color:#087E8B;font-size:22px;font-weight:800;line-height:1">+</span>`,
        replacement_candidate: `<span style="display:grid;place-items:center;width:24px;height:24px;border:2px solid #7C3AED;border-radius:999px;background:#fff;color:#7C3AED;font-size:17px;font-weight:800;line-height:1">★</span>`,
        imputed: `<span style="display:block;width:18px;height:18px;border:2px dashed ${color};border-radius:999px;background:rgba(255,255,255,.9)"></span>`
      }[monitoringStatus];
      const marker = markerHtml
        ? L.marker([well.latitude, well.longitude], {
            icon: L.divIcon({
              className: "monitoring-status-icon",
              html: markerHtml,
              iconSize: [24, 24],
              iconAnchor: [12, 12],
              tooltipAnchor: [0, -12]
            }),
            keyboard: true,
            title: well.name
          }).addTo(wellLayers[well.status] || wellLayers.excluded)
        : L.circleMarker([well.latitude, well.longitude], {
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
          <div style="margin-top:5px;color:#334155;font-size:11px">وضعیت پایش: ${escapeHtml(correctedStatusLabel(monitoringStatus))}</div>
          <div style="margin-top:5px;color:#64748b;font-size:11px">ارتفاع چاه: ${formatNumber(well.elevation, " متر")}</div>
          <div style="margin-top:5px;color:#64748b;font-size:11px">تراز اصلاحی آخر: ${formatNumber(well.latest_corrected_value, " متر")}</div>
          ${well.latest_measurement_limit == null ? "" : `<div style="margin-top:5px;color:#E76F51;font-size:11px">حد اندازه‌گیری: ${formatNumber(well.latest_measurement_limit, " متر")}</div>`}
          ${well.latest_uncertainty == null ? "" : `<div style="margin-top:5px;color:#D97706;font-size:11px">عدم قطعیت: ${formatNumber(well.latest_uncertainty, " متر")}</div>`}
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

  function syncAquiferPanelHeights() {
    const mapElement = document.getElementById("map");
    const mapPanel = document.querySelector("[data-aquifer-map-panel]");
    const mapHeading = document.querySelector("[data-aquifer-map-heading]");
    const analysisPanel = document.querySelector("[data-aquifer-analysis-panel]");
    if (!mapElement || !mapPanel || !mapHeading || !analysisPanel) return;

    mapElement.style.height = "";
    window.requestAnimationFrame(() => {
      if (window.innerWidth >= 1280) {
        const mapChromeHeight = Array.from(mapPanel.children)
          .filter(element => element !== mapElement)
          .reduce((sum, element) => sum + element.getBoundingClientRect().height, 0);
        const panelHeight = Math.max(
          mapPanel.getBoundingClientRect().height,
          analysisPanel.getBoundingClientRect().height
        );
        const mapHeight = Math.max(
          460,
          panelHeight - mapChromeHeight
        );
        mapElement.style.height = `${mapHeight}px`;
      }
      window.requestAnimationFrame(() => {
        if (!state.map) return;
        state.map.invalidateSize({ animate: false, pan: false });
        refreshLeafletMinimumZoom(state.map);
      });
    });
  }

  function renderAquiferChart(data) {
    const chart = echarts.init(document.getElementById("aquiferChart"));
    const option = baseChartOption();
    const categories = data.hydrographs.arithmetic.map(item => item[0]);
    const comparisonEnabled = data.filters.comparison_enabled;
    const surfaceMethods = selectedSurfaceMethods(data);
    const surfacePayloads = surfaceMethods
      .map(method => [method, surfaceMethodPayload(data, method)])
      .filter(([, payload]) => Boolean(payload));
    const legendSelected = {};
    surfacePayloads.forEach(([method, payload]) => {
      const label = surfaceMethodLabel(data, method, true);
      legendSelected[label] = method === "idw";
      legendSelected[`روند ${label} (بازه اصلی)`] = false;
      if (comparisonEnabled && payload?.comparison_trend) {
        legendSelected[`روند ${label} (مقایسه‌ای)`] = false;
      }
    });
    const correctedLegendSelected = {
      "اصلاح‌شده حسابی": false,
      "اصلاح‌شده تیسن": false,
      "اصلاح‌شده IDW": true,
      "اصلاح‌شده Ordinary Kriging": false,
      "اصلاح‌شده Thin Plate Spline": false,
      [`روند اصلاح‌شده ${correctedPrimaryLabel(data, true)}`]: false,
      "اختلاف خام-اصلاح‌شده": false,
      "وضعیت: اندازه‌گیری": true,
      "وضعیت: بازنشسته": true,
      "وضعیت: چاه جدید": true,
      "وضعیت: برآورد": true
    };
    option.xAxis.data = categories;
    option.yAxis[2] = {
      type: "value",
      name: "وضعیت شبکه",
      min: 0,
      position: "left",
      offset: 48,
      splitLine: { show: false },
      axisLabel: {
        formatter: value => faNumber.format(value),
        fontSize: 9,
        color: "#64748B"
      },
      nameTextStyle: {
        fontFamily: "Vazirmatn",
        fontSize: 9,
        color: "#64748B",
        padding: [0, 0, 8, 0]
      }
    };
    option.legend = {
      type: "scroll",
      orient: "horizontal",
      top: 8,
      left: 24,
      right: 24,
      height: 54,
      pageButtonPosition: "end",
      pageIconColor: "#087E8B",
      pageIconInactiveColor: "#CBD5E1",
      pageTextStyle: { color: "#64748B", fontFamily: "Vazirmatn", fontSize: 10 },
      textStyle: { fontFamily: "Vazirmatn", fontSize: 10, color: "#64748B" },
      itemWidth: 14,
      itemHeight: 8,
      selected: {
        "میانگین حسابی": false,
        "روند حسابی (بازه اصلی)": false,
        "میانگین تیسن": false,
        "روند تیسن (بازه اصلی)": false,
        ...(comparisonEnabled ? {
          "روند حسابی (مقایسه‌ای)": false,
          "روند تیسن (مقایسه‌ای)": false
        } : {}),
        ...legendSelected,
        ...correctedLegendSelected,
        "بارش ماهانه": false
      }
    };
    option.grid.top = 86;
    option.series = [
      precipitationBarSeries(data.precipitation),
      ...correctedStatusAreaSeries(data),
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
      ...(comparisonEnabled ? [{
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
        }] : []),
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
      ...(comparisonEnabled ? [{
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
        }] : []),
      ...surfacePayloads.flatMap(([method, payload]) => (
        surfaceLineSeries(data, method, payload, categories, comparisonEnabled)
      )),
      ...correctedHydrographSeries(data)
    ];
    chart.setOption(option);
    state.charts.push(chart);
    renderAquiferTrendSummary(data, surfacePayloads, option.legend.selected);
    chart.on("legendselectchanged", parameters => {
      renderAquiferTrendSummary(data, surfacePayloads, parameters.selected || option.legend.selected);
    });
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
    const groundwaterSelect = document.getElementById("ndviGroundwaterMethod");
    if (!element || !metricSelect || !groundwaterSelect || element.closest(".hidden")) return;
    const metric = metricSelect.value || data.ndvi.default_metric;
    const groundwaterMethod = groundwaterChartMethod(data, groundwaterSelect.value);
    if (!groundwaterMethod) return;
    groundwaterSelect.value = groundwaterMethod.key;
    state.ndviGroundwaterMethod = groundwaterMethod.key;
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
        [groundwaterMethod.label]: true,
        [`NDVI ${ndviMetricLabel(metric)}`]: true
      }
    };
    option.grid.top = 76;
    option.series = [
      ndviBarSeries(data.ndvi, metric),
      groundwaterLineSeries(groundwaterMethod)
    ];
    state.aquiferNdviChart.setOption(option, true);
    state.aquiferNdviChart.resize();
  }

  function renderAquiferAetChart(data) {
    const element = document.getElementById("aquiferAetChart");
    const groundwaterSelect = document.getElementById("aetGroundwaterMethod");
    if (!element || !groundwaterSelect || element.closest(".hidden")) return;
    const groundwaterMethod = groundwaterChartMethod(data, groundwaterSelect.value);
    if (!groundwaterMethod) return;
    groundwaterSelect.value = groundwaterMethod.key;
    state.aetGroundwaterMethod = groundwaterMethod.key;
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
        [groundwaterMethod.label]: true,
        "AET ماهانه": true
      }
    };
    option.grid.top = 76;
    option.series = [
      aetBarSeries(data.aet),
      groundwaterLineSeries(groundwaterMethod)
    ];
    state.aquiferAetChart.setOption(option, true);
    state.aquiferAetChart.resize();
  }

  function renderAquiferAnnualChanges(data) {
    const element = document.getElementById("aquiferAnnualChangesChart");
    const methodSelect = document.getElementById("annualSurfaceMethod");
    const ndviSelect = document.getElementById("annualNdviMetric");
    const ndviPeriodSelect = document.getElementById("annualNdviPeriod");
    if (
      !element
      || !methodSelect
      || !ndviSelect
      || !ndviPeriodSelect
      || element.closest(".hidden")
    ) return;
    const selectedMethod = annualDeclineMethod(data, methodSelect.value)
      || annualDeclineMethod(data, currentAnnualSurfaceMethod(data));
    if (!selectedMethod) return;
    methodSelect.value = selectedMethod.key;
    state.annualSurfaceMethod = selectedMethod.key;
    const ndviMetric = ndviSelect.value || "median";
    const ndviPeriod = ndviPeriodSelect.value || "warm_months";
    const rows = data.annual_changes || [];
    const annualRowsByWaterYear = new Map(
      (selectedMethod.rows || [])
        .filter(row => row?.water_year)
        .map(row => [row.water_year, row])
    );
    const ndviLabel = ndviMetric === "median" ? "میانه" : "میانگین";
    const ndviPeriodLabel = ndviPeriod === "warm_months"
      ? "ماه‌های ۳ تا ۶"
      : "کل سال";
    const ndviPeriodData = row => row.ndvi_periods?.[ndviPeriod] || {
      expected_month_count: 12,
      selected_month_count: row.selected_month_count,
      is_complete: row.is_complete,
      [`${ndviMetric}_month_count`]: row[`ndvi_${ndviMetric}_month_count`],
      [ndviMetric]: row[`ndvi_${ndviMetric}`]
    };
    if (!state.aquiferAnnualChangesChart) {
      state.aquiferAnnualChangesChart = echarts.init(element);
      state.charts.push(state.aquiferAnnualChangesChart);
    }
    const surfaceSeries = [{
      name: `افت ${selectedMethod.label}`,
      type: "bar",
      yAxisIndex: 0,
      data: rows.map(row => (
        annualRowsByWaterYear.get(row.water_year)?.decline ?? null
      )),
      barMaxWidth: 18,
      itemStyle: {
        color: selectedMethod.color,
        borderRadius: [4, 4, 0, 0]
      },
      tooltip: {
        valueFormatter: value => value == null
          ? "بدون داده"
          : `${faNumber.format(value)} متر`
      }
    }];

    state.aquiferAnnualChangesChart.setOption({
      animationDuration: 450,
      textStyle: { fontFamily: "Vazirmatn", color: "#475569" },
      tooltip: {
        trigger: "axis",
        textStyle: { fontFamily: "Vazirmatn" }
      },
      legend: {
        top: 8,
        right: 12,
        textStyle: { fontFamily: "Vazirmatn", fontSize: 10 },
        itemWidth: 16,
        selected: Object.fromEntries([
          [`افت ${selectedMethod.label}`, true],
          ["مجموع بارش", true],
          ["مجموع AET", true],
          [`NDVI ${ndviLabel} (${ndviPeriodLabel})`, true],
          ["سطح کشت آبی احتمالی", true]
        ])
      },
      grid: {
        top: 68,
        right: 196,
        bottom: 62,
        left: 64
      },
      xAxis: {
        type: "category",
        data: rows.map(row => row.water_year),
        axisLabel: {
          fontSize: 9,
          formatter: (value, index) => (
            rows[index]?.is_complete ? value : `${value}\nناقص`
          )
        },
        axisLine: { lineStyle: { color: "#CBD5E1" } }
      },
      yAxis: [
        {
          type: "value",
          name: "افت (متر)",
          min: range => Math.min(0, range.min),
          max: range => Math.max(0, range.max),
          nameTextStyle: { fontFamily: "Vazirmatn", fontSize: 9, color: "#DC2626" },
          axisLabel: { formatter: value => faNumber.format(value), fontSize: 9 },
          splitLine: { lineStyle: { color: "#E9EFF2", type: "dashed" } }
        },
        {
          type: "value",
          name: "بارش / AET (mm)",
          min: 0,
          position: "right",
          nameTextStyle: { fontFamily: "Vazirmatn", fontSize: 9, color: "#0284C7" },
          axisLabel: { formatter: value => faNumber.format(value), fontSize: 9 },
          splitLine: { show: false }
        },
        {
          type: "value",
          name: "NDVI",
          scale: true,
          position: "right",
          offset: 66,
          nameTextStyle: { fontFamily: "Vazirmatn", fontSize: 9, color: "#059669" },
          axisLabel: { formatter: value => faNumber.format(value), fontSize: 9 },
          splitLine: { show: false }
        },
        {
          type: "value",
          name: "مساحت (هکتار)",
          min: 0,
          position: "right",
          offset: 132,
          nameTextStyle: { fontFamily: "Vazirmatn", fontSize: 9, color: "#7C3AED" },
          axisLabel: { formatter: value => faNumber.format(value), fontSize: 9 },
          splitLine: { show: false }
        }
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: 0 },
        {
          type: "slider",
          xAxisIndex: 0,
          height: 16,
          bottom: 8,
          borderColor: "transparent",
          fillerColor: "rgba(8, 126, 139, 0.12)",
          handleStyle: { color: "#087E8B" }
        }
      ],
      series: [
        ...surfaceSeries,
        {
          name: "مجموع بارش",
          type: "bar",
          yAxisIndex: 1,
          data: rows.map(row => row.precipitation_total),
          barMaxWidth: 18,
          itemStyle: { color: "#38BDF8", borderRadius: [4, 4, 0, 0] },
          tooltip: {
            valueFormatter: value => value == null
              ? "بدون داده"
              : `${faNumber.format(value)} میلی‌متر`
          }
        },
        {
          name: "مجموع AET",
          type: "bar",
          yAxisIndex: 1,
          data: rows.map(row => row.aet_total),
          barMaxWidth: 18,
          itemStyle: { color: "#F59E0B", borderRadius: [4, 4, 0, 0] },
          tooltip: {
            valueFormatter: value => value == null
              ? "بدون داده"
              : `${faNumber.format(value)} میلی‌متر`
          }
        },
        {
          name: `NDVI ${ndviLabel} (${ndviPeriodLabel})`,
          type: "line",
          yAxisIndex: 2,
          data: rows.map(row => ndviPeriodData(row)[ndviMetric]),
          symbolSize: 7,
          connectNulls: false,
          lineStyle: { width: 2.5, color: "#059669" },
          itemStyle: { color: "#059669", borderColor: "#FFFFFF", borderWidth: 1.5 },
          tooltip: {
            valueFormatter: value => value == null
              ? "بدون داده"
              : faNumber.format(value)
          },
          z: 5
        },
        {
          name: "سطح کشت آبی احتمالی",
          type: "line",
          yAxisIndex: 3,
          data: rows.map(
            row => row.warm_season_irrigated_area?.probable_area_ha ?? null
          ),
          symbolSize: 7,
          connectNulls: false,
          lineStyle: { width: 2.5, color: "#7C3AED", type: "dashed" },
          itemStyle: { color: "#7C3AED", borderColor: "#FFFFFF", borderWidth: 1.5 },
          tooltip: {
            valueFormatter: value => value == null
              ? "بدون داده"
              : `${faNumber.format(value)} هکتار`
          },
          z: 4
        }
      ]
    }, true);
    state.aquiferAnnualChangesChart.resize();

    const table = document.getElementById("aquiferAnnualChangesTable");
    table.innerHTML = `
      <table class="data-table">
        <thead>
          <tr>
            <th>سال آبی</th>
            <th>بارش (میلی‌متر)</th>
            <th>AET (میلی‌متر)</th>
            <th>NDVI ${ndviLabel} (${ndviPeriodLabel})</th>
            <th>سطح کشت آبی احتمالی (هکتار)</th>
            <th>پوشش زمانی</th>
            <th>افت ${escapeHtml(selectedMethod.label)}</th>
            <th>ذخیره ${escapeHtml(selectedMethod.label)}</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(row => `
            <tr>
              <td dir="ltr" class="font-bold text-navy">${row.water_year}</td>
              <td>${numberCell(row.precipitation_total)}</td>
              <td>${numberCell(row.aet_total)}</td>
              <td>${numberCell(ndviPeriodData(row)[ndviMetric])}</td>
              <td>
                ${numberCell(
                  row.warm_season_irrigated_area?.probable_area_ha
                )}
                <div class="mt-1 text-[9px] text-slate-400">
                  سال ${faNumber.format(
                    row.warm_season_irrigated_area?.jalali_year
                  )} ·
                  ${row.warm_season_irrigated_area?.probable_percent == null
                    ? "درصد نامشخص"
                    : `${faNumber.format(
                      row.warm_season_irrigated_area.probable_percent
                    )}٪ از محدوده تحلیل`}
                </div>
              </td>
              <td>
                <span class="${row.is_complete ? "text-teal" : "text-amber-600"}">
                  ${row.is_complete ? "کامل" : "ناقص"} · ${faNumber.format(row.selected_month_count)} ماه
                </span>
                <div class="mt-1 text-[9px] text-slate-400">
                  بارش ${faNumber.format(row.precipitation_month_count)} ·
                  AET ${faNumber.format(row.aet_month_count)} ·
                  NDVI ${faNumber.format(ndviPeriodData(row)[`${ndviMetric}_month_count`])}
                  از ${faNumber.format(ndviPeriodData(row).expected_month_count)}
                </div>
                <div class="mt-1 text-[9px] text-slate-400">
                  پوشش معتبر سطح کشت:
                  ${row.warm_season_irrigated_area?.valid_percent == null
                    ? "—"
                    : `${faNumber.format(
                      row.warm_season_irrigated_area.valid_percent
                    )}٪`}
                </div>
              </td>
              <td>${numberCell(annualRowsByWaterYear.get(row.water_year)?.decline)}</td>
              <td>${numberCell(annualRowsByWaterYear.get(row.water_year)?.storage_change_mcm)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
  }

  function renderAquiferScenarioPanel(data) {
    const panel = document.getElementById("aquiferScenarioPanel");
    if (!panel || panel.closest(".hidden")) return;
    if (state.aquiferScenarioChart) {
      state.aquiferScenarioChart.dispose();
      state.charts = state.charts.filter(chart => chart !== state.aquiferScenarioChart);
      state.aquiferScenarioChart = null;
    }
    const methods = selectedSurfaceMethods(data);
    const scenarios = methods.map(method => ({
      method,
      label: surfaceMethodLabel(data, method, true),
      payload: surfaceMethodPayload(data, method)?.five_year_scenario || {}
    }));
    const primary = scenarios[0] || { method: "idw", label: "IDW", payload: {} };
    const primaryScenario = primary.payload || {};
    const declineRate = toNumber(primaryScenario.decline_per_year_m);
    const finalRow = primaryScenario.series?.at(-1);
    const finalDecline = finalRow?.cumulative_decline_m;
    const finalLevel = finalRow?.projected_level_m;
    const directionText = primaryScenario.direction === "decline"
      ? "ادامه روند افت"
      : primaryScenario.direction === "rise"
        ? "ادامه روند افزایش تراز"
        : primaryScenario.direction === "stable"
          ? "تراز تقریباً پایدار"
          : "روند نامشخص";

    panel.innerHTML = `
      <div class="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <section class="rounded-2xl border border-slate-200 bg-slate-50/60 p-4">
          <div class="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
            <div>
              <h4 class="text-base font-bold text-navy">سناریوی ۵ سال آینده</h4>
              <p class="mt-1 text-[10px] leading-5 text-slate-500">ادامه خطی روند فعلی در بازه منتخب؛ سال‌ها با سال آبی فارسی گزارش می‌شوند.</p>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <span class="rounded-xl border border-teal/15 bg-teal/5 px-3 py-2 text-[10px] font-medium text-navy">
                نمایش هم‌زمان ${faNumber.format(scenarios.length)} روش
              </span>
              <button id="scenarioReportButton" type="button" class="secondary-button h-9">گزارش PDF</button>
            </div>
          </div>

          <div class="mt-4 grid gap-3 sm:grid-cols-4">
            <div class="rounded-xl border border-slate-200 bg-white p-3">
              <div class="text-[10px] text-slate-500">روش مرجع کارت</div>
              <div class="mt-2 text-sm font-bold text-navy">${primary.label}</div>
              <div class="mt-1 text-[9px] text-slate-400">${directionText}</div>
            </div>
            <div class="rounded-xl border border-slate-200 bg-white p-3">
              <div class="text-[10px] text-slate-500">تراز مبنا</div>
              <div dir="ltr" class="mt-2 text-sm font-bold text-navy">${formatNumber(primaryScenario.baseline_level_m, " m")}</div>
              <div dir="ltr" class="mt-1 text-[9px] text-slate-400">${primaryScenario.baseline_month || "—"}</div>
            </div>
            <div class="rounded-xl border border-slate-200 bg-white p-3">
              <div class="text-[10px] text-slate-500">نرخ روندی</div>
              <div dir="ltr" class="mt-2 text-sm font-bold ${declineRate > 0 ? "text-coral" : declineRate < 0 ? "text-teal" : "text-slate-500"}">${formatSignedNumber(declineRate, " m/y")}</div>
              <div class="mt-1 text-[9px] text-slate-400">مثبت یعنی افت سالانه</div>
            </div>
            <div class="rounded-xl border border-slate-200 bg-white p-3">
              <div class="text-[10px] text-slate-500">نتیجه سال پنجم</div>
              <div dir="ltr" class="mt-2 text-sm font-bold text-coral">${formatSignedNumber(finalDecline, " m")}</div>
              <div dir="ltr" class="mt-1 text-[9px] text-slate-400">تراز: ${formatNumber(finalLevel, " m")}</div>
            </div>
          </div>

          <div id="aquiferScenarioChart" class="mt-4 h-[360px] w-full"></div>
        </section>

        <section class="rounded-2xl border border-slate-200 bg-white p-4">
          <h4 class="text-sm font-bold text-navy">جدول سناریو</h4>
          <p class="mt-1 text-[10px] leading-5 text-slate-500">مقادیر هر روش نسبت به آخرین تراز همان روش در بازه انتخابی محاسبه می‌شوند.</p>
          <div class="table-scroll mt-3 max-h-[430px]">
            <table class="data-table">
              <thead>
                <tr>
                  <th>افق</th>
                  <th>سال آبی</th>
                  ${scenarios.map(item => `
                    <th>تراز ${escapeHtml(item.label)}</th>
                    <th>افت ${escapeHtml(item.label)}</th>
                  `).join("")}
                </tr>
              </thead>
              <tbody>
                ${((primaryScenario.series || []).map(row => `
                  <tr>
                    <td>${faNumber.format(row.horizon_year)} سال</td>
                    <td dir="ltr" class="font-bold text-navy">${row.water_year}</td>
                    ${scenarios.map(item => {
                      const matched = (item.payload.series || []).find(candidate => (
                        candidate.horizon_year === row.horizon_year
                      ));
                      return `
                        <td>${numberCell(matched?.projected_level_m)}</td>
                        <td>${metricCell(matched?.cumulative_decline_m)}</td>
                      `;
                    }).join("")}
                  </tr>
                `).join("")) || `
                  <tr>
                    <td colspan="${2 + scenarios.length * 2}" class="text-center text-slate-400">داده کافی برای ساخت سناریو وجود ندارد.</td>
                  </tr>
                `}
              </tbody>
            </table>
          </div>
          <div class="mt-3 rounded-xl border border-amber-100 bg-amber-50/70 px-4 py-3 text-[10px] leading-6 text-slate-600">
            این سناریو قطعیت پیش‌بینی ندارد و فقط ادامه روند خطی فعلی را نشان می‌دهد؛ تغییر برداشت، تغذیه، خشکسالی یا ترسالی می‌تواند مسیر واقعی را عوض کند.
          </div>
        </section>
      </div>
    `;

    document.getElementById("scenarioReportButton").onclick = openPdfReport;

    const chartElement = document.getElementById("aquiferScenarioChart");
    if (!chartElement) return;
    const rows = primaryScenario.series || [];
    const categories = ["مبنا", ...rows.map(row => row.water_year)];
    state.aquiferScenarioChart = echarts.init(chartElement);
    state.charts.push(state.aquiferScenarioChart);
    state.aquiferScenarioChart.setOption({
      animationDuration: 450,
      textStyle: { fontFamily: "Vazirmatn", color: "#475569" },
      tooltip: {
        trigger: "axis",
        textStyle: { fontFamily: "Vazirmatn" }
      },
      legend: {
        top: 8,
        right: 12,
        textStyle: { fontFamily: "Vazirmatn", fontSize: 10 },
        itemWidth: 16,
        selected: Object.fromEntries(scenarios.flatMap(item => ([
          [`تراز ${item.label}`, true],
          [`افت ${item.label}`, true]
        ])))
      },
      grid: { top: 64, right: 76, bottom: 48, left: 64 },
      xAxis: {
        type: "category",
        data: categories,
        axisLabel: { fontSize: 9 },
        axisLine: { lineStyle: { color: "#CBD5E1" } }
      },
      yAxis: [
        {
          type: "value",
          name: "تراز (متر)",
          scale: true,
          nameTextStyle: { fontFamily: "Vazirmatn", fontSize: 9, color: "#11395B" },
          axisLabel: { formatter: value => faNumber.format(value), fontSize: 9 },
          splitLine: { lineStyle: { color: "#E9EFF2", type: "dashed" } }
        },
        {
          type: "value",
          name: "افت تجمعی",
          position: "right",
          nameTextStyle: { fontFamily: "Vazirmatn", fontSize: 9, color: "#E76F51" },
          axisLabel: { formatter: value => faNumber.format(value), fontSize: 9 },
          splitLine: { show: false }
        }
      ],
      series: [
        ...scenarios.map(item => ({
          name: `تراز ${item.label}`,
          type: "line",
          yAxisIndex: 0,
          data: [
            item.payload.baseline_level_m ?? null,
            ...(item.payload.series || []).map(row => row.projected_level_m)
          ],
          symbolSize: 8,
          lineStyle: { width: 3, color: surfaceMethodColor(item.method) },
          itemStyle: {
            color: surfaceMethodColor(item.method),
            borderColor: "#FFFFFF",
            borderWidth: 1.5
          },
          tooltip: {
            valueFormatter: value => value == null ? "بدون داده" : `${faNumber.format(value)} متر`
          },
          z: 5
        })),
        ...scenarios.map(item => ({
          name: `افت ${item.label}`,
          type: "bar",
          yAxisIndex: 1,
          data: [0, ...(item.payload.series || []).map(row => row.cumulative_decline_m)],
          barMaxWidth: 18,
          itemStyle: {
            color: surfaceMethodColor(item.method),
            borderRadius: [5, 5, 0, 0],
            opacity: 0.55
          },
          tooltip: {
            valueFormatter: value => value == null ? "بدون داده" : `${faNumber.format(value)} متر`
          }
        }))
      ]
    }, true);
    state.aquiferScenarioChart.resize();
  }

  function renderAquiferRiskPanel(data) {
    const panel = document.getElementById("aquiferRiskPanel");
    if (!panel || panel.closest(".hidden")) return;
    if (state.aquiferRiskSignalChart) {
      state.aquiferRiskSignalChart.dispose();
      state.charts = state.charts.filter(chart => chart !== state.aquiferRiskSignalChart);
      state.aquiferRiskSignalChart = null;
    }

    const analysis = data.time_series_analysis || {};
    const risk = analysis.risk_assessment || {};
    const driver = analysis.driver_classification || {};
    const stress = analysis.stress_indicators || {};
    const factors = risk.factors || {};
    const level = risk.level || "insufficient";
    const score = toNumber(risk.score);
    const color = riskLevelColor(level);
    const period = analysis.period || {};
    const climateScore = toNumber(driver.climate_score);
    const humanScore = toNumber(driver.human_score);
    const precipitationStrength = toNumber(driver.signals?.precipitation_strength);
    const declinePersistence = factors.decline_persistence || {};
    const meanDecline = factors.mean_decline || {};
    const maxDecline = factors.max_decline || {};
    const anomalyFactor = factors.anomaly_frequency || {};
    const pressureFactor = factors.agricultural_pressure || {};
    const anomalyYears = anomalyFactor.years || [];
    const pressureYears = pressureFactor.years || [];
    const declinePeriods = stress.consecutive_decline_periods || [];
    const driverSummary = {
      "Climate Dominated": "پاسخ آبخوان به بارش پررنگ‌تر از سیگنال‌های کشاورزی دیده شده است.",
      "Human Dominated": "افت پایدار است و همزمان شاخص‌های کشاورزی یا سطح کشت آبی سیگنال افزایشی دارند.",
      "Mixed Influence": "هم اقلیم و هم فشار کشاورزی در تغییرات تراز نقش قابل مشاهده دارند."
    }[driver.label] || "برای تفکیک محرک غالب، داده کافی یا سیگنال روشن وجود ندارد.";

    const factorRows = [
      scoreBar(
        "پایداری افت",
        declinePersistence.score,
        `${faNumber.format(declinePersistence.declining_year_count || 0)} سال افت از ${faNumber.format(declinePersistence.water_year_count || period.water_year_count || 0)} سال آبی`,
        color
      ),
      scoreBar(
        "میانگین افت سالانه",
        meanDecline.score,
        `${formatNumber(meanDecline.value_m, " متر")} در سال آبی`,
        "#E76F51"
      ),
      scoreBar(
        "بیشینه افت سالانه",
        maxDecline.score,
        `${formatNumber(maxDecline.value_m, " متر")} در شدیدترین سال`,
        "#DC2626"
      ),
      scoreBar(
        "سال‌های نابهنجار",
        anomalyFactor.score,
        `${faNumber.format(anomalyFactor.count || 0)} سال با افت غیرعادی`,
        "#7C3AED"
      ),
      scoreBar(
        "فشار کشاورزی همزمان",
        pressureFactor.score,
        `${faNumber.format(pressureFactor.simultaneous_pressure_year_count || 0)} سال با رشد کشت/NDVI و افت همزمان`,
        "#D97706"
      )
    ].join("");

    const correlations = [
      ["بارش همان سال", analysis.correlations?.precipitation],
      ["بارش با تاخیر ۱ سال", analysis.lag_analysis?.lag_1],
      ["بارش با تاخیر ۲ سال", analysis.lag_analysis?.lag_2],
      ["AET", analysis.correlations?.aet],
      ["NDVI", analysis.correlations?.ndvi],
      ["سطح کشت آبی", analysis.correlations?.irrigated_area]
    ];
    const correlationCards = correlations.map(([label, item]) => {
      const coefficient = toNumber(
        item?.spearman?.coefficient ?? item?.pearson?.coefficient
      );
      const count = item?.n ?? 0;
      const tone = coefficient === null
        ? "text-slate-400"
        : coefficient < 0
          ? "text-teal"
          : "text-coral";
      return `
        <div class="rounded-xl border border-slate-200 bg-white px-3 py-2.5">
          <div class="text-[10px] text-slate-500">${label}</div>
          <div dir="ltr" class="mt-1 text-base font-bold ${tone}">
            ${coefficient === null ? "—" : faNumber.format(coefficient)}
          </div>
          <div class="mt-1 text-[9px] text-slate-400">${faNumber.format(count)} سال مشترک</div>
        </div>
      `;
    }).join("");

    const yearPills = (items, emptyText, formatter) => (
      items.length
        ? items.map(formatter).join("")
        : `<span class="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[10px] text-slate-400">${emptyText}</span>`
    );

    panel.innerHTML = `
      <div class="grid gap-4 xl:grid-cols-[1.1fr_1.4fr]">
        <section class="rounded-2xl border border-slate-200 bg-slate-50/60 p-4">
          <div class="flex flex-col items-start gap-4 sm:flex-row sm:items-center">
            <div class="flex h-32 w-32 shrink-0 items-center justify-center rounded-full p-2" style="background:conic-gradient(${color} ${score || 0}%, #E2E8F0 0)">
              <div class="flex h-full w-full flex-col items-center justify-center rounded-full bg-white text-center shadow-sm">
                <div dir="ltr" class="text-3xl font-bold text-navy">${score === null ? "—" : faNumber.format(score)}</div>
                <div class="mt-1 text-[10px] text-slate-400">از ۱۰۰</div>
              </div>
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <span class="rounded-full border px-3 py-1 text-[10px] font-bold ${riskBadgeClass(level)}">ریسک ${riskLevelLabel(level)}</span>
                <span class="rounded-full border border-slate-200 bg-white px-3 py-1 text-[10px] text-slate-500">اطمینان ${confidenceLabel(risk.confidence || driver.confidence)}</span>
              </div>
              <h4 class="mt-3 text-lg font-bold text-navy">محرک غالب: ${driverLabel(driver.label)}</h4>
              <p class="mt-2 text-xs leading-6 text-slate-600">${driverSummary}</p>
              <div class="mt-4 grid grid-cols-3 gap-2">
                <div class="rounded-xl bg-white px-3 py-2 text-center">
                  <div class="text-[9px] text-slate-400">اقلیم</div>
                  <div dir="ltr" class="mt-1 text-sm font-bold text-sky-700">${scorePercent(climateScore === null ? null : climateScore * 100)}</div>
                </div>
                <div class="rounded-xl bg-white px-3 py-2 text-center">
                  <div class="text-[9px] text-slate-400">کشاورزی/انسانی</div>
                  <div dir="ltr" class="mt-1 text-sm font-bold text-amber-700">${scorePercent(humanScore === null ? null : humanScore * 100)}</div>
                </div>
                <div class="rounded-xl bg-white px-3 py-2 text-center">
                  <div class="text-[9px] text-slate-400">ارتباط بارش</div>
                  <div dir="ltr" class="mt-1 text-sm font-bold text-teal">${scorePercent(precipitationStrength === null ? null : precipitationStrength * 100)}</div>
                </div>
              </div>
            </div>
          </div>
          <div id="aquiferRiskSignalChart" class="mt-5 h-56 w-full"></div>
        </section>

        <section class="grid gap-3 sm:grid-cols-2">
          ${factorRows}
        </section>
      </div>

      <div class="mt-4 grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <section class="rounded-2xl border border-slate-200 bg-white p-4">
          <div class="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
            <div>
              <h4 class="text-sm font-bold text-navy">سال‌های هشدار و دوره‌های افت</h4>
              <p class="mt-1 text-[10px] leading-5 text-slate-500">همه سال‌ها بر اساس سال آبی فارسی مهر تا شهریور گزارش می‌شوند.</p>
            </div>
            <span dir="ltr" class="rounded-lg bg-slate-50 px-3 py-2 text-[10px] font-bold text-slate-500">
              ${period.start_water_year || "—"} تا ${period.end_water_year || "—"}
            </span>
          </div>
          <div class="mt-4 grid gap-3 md:grid-cols-3">
            <div>
              <div class="mb-2 text-[10px] font-bold text-slate-500">افت نابهنجار</div>
              <div class="flex flex-wrap gap-2">
                ${yearPills(anomalyYears, "سال نابهنجار دیده نشد", item => `
                  <span class="rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-[10px] text-red-700">
                    <b dir="ltr">${item.water_year}</b>
                    <span dir="ltr" class="block">${formatNumber(item.value_m, " m")}</span>
                  </span>
                `)}
              </div>
            </div>
            <div>
              <div class="mb-2 text-[10px] font-bold text-slate-500">فشار کشاورزی همزمان</div>
              <div class="flex flex-wrap gap-2">
                ${yearPills(pressureYears, "سال همزمان شناسایی نشد", item => `
                  <span class="rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-[10px] text-amber-700">
                    <b dir="ltr">${item.water_year}</b>
                    <span dir="ltr" class="block">${formatNumber(item.groundwater_decline_m, " m")}</span>
                  </span>
                `)}
              </div>
            </div>
            <div>
              <div class="mb-2 text-[10px] font-bold text-slate-500">طولانی‌ترین دوره‌های افت</div>
              <div class="flex flex-wrap gap-2">
                ${yearPills(
                  [...declinePeriods].sort((a, b) => (
                    (b.length_years || 0) - (a.length_years || 0)
                  )).slice(0, 3),
                  "دوره پیوسته‌ای ثبت نشد",
                  item => `
                    <span class="rounded-lg border border-coral/20 bg-coral/10 px-3 py-2 text-[10px] text-coral">
                      <b dir="ltr">${item.start_water_year}</b>
                      <span class="block">${faNumber.format(item.length_years || 0)} سال · ${formatNumber(item.total_decline_m, " متر")}</span>
                    </span>
                  `
                )}
              </div>
            </div>
          </div>
        </section>

        <section class="rounded-2xl border border-slate-200 bg-slate-50/60 p-4">
          <h4 class="text-sm font-bold text-navy">همبستگی با افت سالانه</h4>
          <p class="mt-1 text-[10px] leading-5 text-slate-500">عددها ضریب همبستگی رتبه‌ای/پیرسون قابل محاسبه برای سال‌های مشترک هستند.</p>
          <div class="mt-4 grid grid-cols-2 gap-2">
            ${correlationCards}
          </div>
        </section>
      </div>
    `;

    const chartElement = document.getElementById("aquiferRiskSignalChart");
    if (!chartElement) return;
    const chartScores = [
      ["پایداری افت", toNumber(declinePersistence.score)],
      ["میانگین افت", toNumber(meanDecline.score)],
      ["بیشینه افت", toNumber(maxDecline.score)],
      ["سال نابهنجار", toNumber(anomalyFactor.score)],
      ["فشار کشاورزی", toNumber(pressureFactor.score)]
    ];
    state.aquiferRiskSignalChart = echarts.init(chartElement);
    state.charts.push(state.aquiferRiskSignalChart);
    state.aquiferRiskSignalChart.setOption({
      animationDuration: 450,
      textStyle: { fontFamily: "Vazirmatn", color: "#475569" },
      grid: { top: 12, right: 18, bottom: 24, left: 92 },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        textStyle: { fontFamily: "Vazirmatn" },
        valueFormatter: value => value == null ? "بدون داده" : `${faNumber.format(value)}٪`
      },
      xAxis: {
        type: "value",
        min: 0,
        max: 100,
        axisLabel: { formatter: value => faNumber.format(value), fontSize: 9 },
        splitLine: { lineStyle: { color: "#E9EFF2", type: "dashed" } }
      },
      yAxis: {
        type: "category",
        data: chartScores.map(item => item[0]),
        axisLabel: { fontSize: 10 },
        axisLine: { show: false },
        axisTick: { show: false }
      },
      series: [{
        name: "امتیاز عامل",
        type: "bar",
        data: chartScores.map(item => item[1]),
        barMaxWidth: 14,
        itemStyle: {
          color,
          borderRadius: [0, 5, 5, 0]
        }
      }]
    }, true);
    state.aquiferRiskSignalChart.resize();
  }

  function renderAquiferAnnualTable(data) {
    const container = document.getElementById("aquiferAnnualTable");
    const methods = annualDeclineMethods(data);
    const years = (data.annual_decline || []).map(row => row.water_year);
    const rowsByMethod = new Map(
      methods.map(method => [
        method.key,
        new Map((method.rows || []).map(row => [row.water_year, row]))
      ])
    );
    const rows = years.map(waterYear => `
      <tr>
        <td dir="ltr" class="sticky right-0 z-10 bg-white font-bold text-navy">${waterYear}</td>
        ${methods.map(method => {
          const row = rowsByMethod.get(method.key)?.get(waterYear) || {};
          return `
            <td>${numberCell(row.start_level)}</td>
            <td>${endpointCell(row.end_level, row.end_month)}</td>
            <td>${metricCell(row.decline)}</td>
            <td>${metricCell(row.cumulative_decline)}</td>
            <td>${metricCell(row.storage_change_mcm)}</td>
          `;
        }).join("")}
      </tr>
    `).join("");
    container.innerHTML = `
      <table class="data-table">
        <thead>
          <tr>
            <th rowspan="2">سال آبی</th>
            ${methods.map(method => `
              <th colspan="5" class="group-heading">${escapeHtml(method.label)}</th>
            `).join("")}
          </tr>
          <tr>
            ${methods.map(() => `
              <th>تراز مهر شروع</th>
              <th>تراز پایان</th>
              <th>افت سالانه</th>
              <th>افت تجمعی</th>
              <th>تغییر ذخیره</th>
            `).join("")}
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="border-t border-slate-100 bg-slate-50 px-5 py-3 text-[10px] leading-5 text-slate-500">
        پایان سال مهر بعد است؛ برای آخرین سال ناقص، آخرین مقدار موجود تا شهریور به‌عنوان پایان استفاده می‌شود. تغییر ذخیره بر حسب میلیون مترمکعب و با ضریب ذخیره/آبدهی ویژه واردشده محاسبه شده است.
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
      ...(state.currentData.filters.comparison_enabled ? [
        trendChip("شیب بازه مقایسه‌ای", well.comparison_trend, "comparison")
      ] : [])
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
        ...(state.currentData.filters.comparison_enabled ? [{
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
          }] : [])
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
    document.querySelectorAll("[data-close-ai-modal]").forEach(button => {
      button.onclick = closeAiModal;
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
              ${state.currentData.filters.comparison_enabled
                ? trendChip("روند مقایسه‌ای", well.comparison_trend, "comparison")
                : ""}
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
          ...(data.filters.comparison_enabled ? [{
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
            }] : [])
        ];
        chart.setOption(option);
        state.charts.push(chart);
        state.observer.unobserve(element);
      });
    }, { rootMargin: "500px 0px" });
    container.querySelectorAll("[data-well-chart]").forEach(element => state.observer.observe(element));
  }

  function activeAquiferTab() {
    return document.querySelector(
      '[data-tab-group="aquifer"].is-active'
    )?.dataset.tab || "chart";
  }

  function restoreAquiferTab(tab) {
    const button = document.querySelector(
      `[data-tab-group="aquifer"][data-tab="${tab}"]`
    );
    if (button) switchTab(button);
  }

  function dashboardFilterParams(data) {
    const filters = data?.filters || {};
    const params = new URLSearchParams();
    [
      "start_year",
      "start_month",
      "end_year",
      "end_month",
      "comparison_start_year",
      "comparison_start_month",
      "comparison_end_year",
      "comparison_end_month"
    ].forEach(key => {
      if (filters[key] !== null && filters[key] !== undefined) {
        params.set(key, filters[key]);
      }
    });
    params.set("comparison_enabled", String(Boolean(filters.comparison_enabled)));
    params.set("continuous_only", String(Boolean(filters.continuous_only)));
    params.set("manual_selection", String(Boolean(filters.manual_selection)));
    if (filters.storage_coefficient !== null && filters.storage_coefficient !== undefined) {
      params.set("storage_coefficient", filters.storage_coefficient);
    }
    (filters.surface_interpolation_methods || [filters.surface_interpolation_method])
      .filter(Boolean)
      .forEach(method => {
        params.append("surface_interpolation_methods", method);
      });
    if (filters.corrected_support_method) {
      params.set("corrected_support_method", filters.corrected_support_method);
    }
    (filters.selected_well_ids || []).forEach(wellId => {
      params.append("selected_well_ids", wellId);
    });
    return params;
  }

  function openPdfReport() {
    const data = state.currentData;
    if (!data?.id) return;
    const params = dashboardFilterParams(data);
    const query = params.toString() ? `?${params}` : "";
    window.open(`/reports/aquifer/${encodeURIComponent(data.id)}${query}`, "_blank", "noopener");
  }

  function renderDashboardData(data, activeTab = "chart") {
    disposeVisuals();
    renderFilterControls(data);
    resetAquiferChat(data);
    renderStats(data);
    resetAiAnalysisCard();
    bindWellModal();
    renderMap(data);
    renderAquiferChart(data);
    const ndviMetric = document.getElementById("ndviMetric");
    if (ndviMetric) {
      ndviMetric.value = data.ndvi.default_metric;
      ndviMetric.onchange = () => renderAquiferNdviChart(data);
    }
    const ndviGroundwaterMethod = document.getElementById("ndviGroundwaterMethod");
    if (ndviGroundwaterMethod) {
      ndviGroundwaterMethod.onchange = () => renderAquiferNdviChart(data);
    }
    const aetGroundwaterMethod = document.getElementById("aetGroundwaterMethod");
    if (aetGroundwaterMethod) {
      aetGroundwaterMethod.onchange = () => renderAquiferAetChart(data);
    }
    const annualSurfaceMethod = document.getElementById("annualSurfaceMethod");
    const annualNdviMetric = document.getElementById("annualNdviMetric");
    const annualNdviPeriod = document.getElementById("annualNdviPeriod");
    if (annualSurfaceMethod) {
      annualSurfaceMethod.onchange = () => renderAquiferAnnualChanges(data);
    }
    if (annualNdviMetric) {
      annualNdviMetric.onchange = () => renderAquiferAnnualChanges(data);
    }
    if (annualNdviPeriod) {
      annualNdviPeriod.onchange = () => renderAquiferAnnualChanges(data);
    }
    renderAquiferAnnualTable(data);
    renderSpatialAnalysis(data);
    renderWellCharts(data);
    if (activeTab !== "chart") {
      window.requestAnimationFrame(() => restoreAquiferTab(activeTab));
    } else {
      syncAquiferPanelHeights();
    }
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
    if (tab === "chart" || tab === "ndvi" || tab === "aet" || tab === "annual" || tab === "scenario" || tab === "risk") {
      const chartElement = scope.querySelector("[data-well-chart]");
      if (chartElement && state.observer) state.observer.observe(chartElement);
      if (group === "aquifer" && tab === "ndvi") {
        window.requestAnimationFrame(() => renderAquiferNdviChart(state.currentData));
      }
      if (group === "aquifer" && tab === "aet") {
        window.requestAnimationFrame(() => renderAquiferAetChart(state.currentData));
      }
      if (group === "aquifer" && tab === "annual") {
        window.requestAnimationFrame(() => renderAquiferAnnualChanges(state.currentData));
      }
      if (group === "aquifer" && tab === "scenario") {
        window.requestAnimationFrame(() => renderAquiferScenarioPanel(state.currentData));
      }
      if (group === "aquifer" && tab === "risk") {
        window.requestAnimationFrame(() => renderAquiferRiskPanel(state.currentData));
      }
      window.setTimeout(() => state.charts.forEach(chart => chart.resize()), 50);
      window.setTimeout(() => state.modalChart?.resize(), 50);
    }
    if (group === "aquifer") {
      const viewSelect = document.getElementById("aquiferViewSelect");
      if (viewSelect) viewSelect.value = tab;
      syncAquiferPanelHeights();
    }
  }

  async function loadDashboard(root, filters = null) {
    const aquiferId = root.dataset.aquiferId;
    if (!aquiferId) return;
    const token = ++state.requestToken;
    const activeTab = activeAquiferTab();
    const button = root.querySelector("#applyAnalysisFilters");
    if (button) {
      button.disabled = true;
      button.textContent = "در حال محاسبه...";
    }
    try {
      const params = new URLSearchParams();
      const storageInput = root.querySelector("#storageCoefficient");
      const storageCoefficient = Number(storageInput?.value);
      if (!Number.isFinite(storageCoefficient) || storageCoefficient <= 0) {
        window.alert("ضریب ذخیره/آبدهی ویژه باید عددی مثبت باشد.");
        storageInput?.focus();
        return;
      }
      params.set("storage_coefficient", String(storageCoefficient));
      selectedSurfaceMethodsFromForm(root).forEach(method => {
        params.append("surface_interpolation_methods", method);
      });
      const correctedSupport = root.querySelector("#correctedSupportMethod")?.value || "fixed_thiessen";
      params.set("corrected_support_method", correctedSupport);
      if (filters) {
        params.set("start_year", filters.startYear);
        params.set("start_month", filters.startMonth);
        params.set("end_year", filters.endYear);
        params.set("end_month", filters.endMonth);
        params.set("comparison_enabled", String(filters.comparisonEnabled));
        if (filters.comparisonEnabled) {
          params.set("comparison_start_year", filters.comparisonStartYear);
          params.set("comparison_start_month", filters.comparisonStartMonth);
          params.set("comparison_end_year", filters.comparisonEndYear);
          params.set("comparison_end_month", filters.comparisonEndMonth);
        }
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
      renderDashboardData(data, activeTab);
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
    root.querySelector("#reportPdfButton")?.addEventListener("click", openPdfReport);
    root.querySelector("#aiOpenModalButton")?.addEventListener("click", openAiModal);
    root.querySelector("#aiAnalyzeButton")?.addEventListener("click", () => {
      analyzeWithAi(root);
    });
    root.querySelector("#aquiferViewSelect")?.addEventListener("change", event => {
      const tab = event.target.value;
      const button = root.querySelector(
        `[data-tab-group="aquifer"][data-tab="${tab}"]`
      );
      if (button) switchTab(button);
    });
    root.querySelector("#aiProvider")?.addEventListener("change", syncAiModelOptions);
    root.querySelector("#aiModel")?.addEventListener("change", updateAiModelHint);
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
    root.querySelector("#comparisonTrendEnabled").addEventListener(
      "change",
      syncComparisonTrendUI
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
      const comparisonEnabled = root.querySelector(
        "#comparisonTrendEnabled"
      ).checked;
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
      if (comparisonEnabled && comparisonStartIndex > comparisonEndIndex) {
        window.alert("تاریخ شروع بازه مقایسه باید قبل از تاریخ پایان باشد.");
        return;
      }
      if (comparisonEnabled && (
        comparisonEndIndex < analysisStartIndex
        || comparisonStartIndex > analysisEndIndex
      )) {
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
        comparisonEnabled,
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
    syncAquiferPanelHeights();
    state.charts.forEach(chart => chart.resize());
    state.modalChart?.resize();
    state.precipitationModalChart?.resize();
    if (state.map) {
      state.map.invalidateSize();
      refreshLeafletMinimumZoom(state.map);
    }
    if (state.selectionMap) {
      resizeSelectionMap();
    }
    window.requestAnimationFrame(applyHeatmapClip);
  });

  document.addEventListener("DOMContentLoaded", () => {
    initializeSelectionTabs();
    initializeAquiferSelection();
    initializeAquiferChat();
  });

  document.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      closeAiModal();
      closeWellModal();
      closePrecipitationModal();
    }
  });
})();
