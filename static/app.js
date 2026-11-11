const state = {
  dataset: null,
  history: [],
  busy: false,
  toastTimer: null,
  resultCounter: 0,
};

const elements = {
  welcome: document.querySelector("#welcome"),
  conversation: document.querySelector("#conversation"),
  form: document.querySelector("#question-form"),
  input: document.querySelector("#question-input"),
  file: document.querySelector("#file-input"),
  send: document.querySelector("#send-button"),
  loading: document.querySelector("#loading"),
  toast: document.querySelector("#toast"),
  sidebar: document.querySelector("#sidebar"),
  settings: document.querySelector("#modal-backdrop"),
};

const chartColors = ["#4c7dde", "#70b995", "#e7a772", "#9d8bd2", "#e17f85",
  "#55a5b8", "#cf9c4c", "#7487a2", "#7bb3a0", "#aa83a8"];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function numberValue(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string" || !value.trim()) return null;
  const negative = /^\(.*\)$/.test(value.trim());
  const normalized = value.trim().replace(/^\(|\)$/g, "")
    .replace(/,/g, "")
    .replace(/^(?:[$€£₹¥]\s*)+/g, "")
    .replace(/\s*(?:USD|EUR|GBP|INR|dollars?)$/i, "");
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(normalized)) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? (negative ? -Math.abs(parsed) : parsed) : null;
}

function formatNumber(value) {
  const number = numberValue(value);
  if (number === null) return escapeHtml(value);
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: Number.isInteger(number) ? 0 : 2,
  }).format(number);
}

async function requestJson(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || `Request failed (${response.status}).`);
    return body;
  }
  if (!response.ok) throw new Error(`Request failed (${response.status}).`);
  return response;
}

function notify(message) {
  elements.toast.textContent = message;
  elements.toast.classList.remove("hidden");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => elements.toast.classList.add("hidden"), 3600);
}

function setBusy(isBusy) {
  state.busy = isBusy;
  elements.send.disabled = isBusy;
  elements.input.disabled = isBusy;
  elements.loading.classList.toggle("hidden", !isBusy);
}

function updateDataset(dataset) {
  state.dataset = dataset;
  const name = dataset?.filename || "No dataset";
  const size = dataset ? `${dataset.rowCount.toLocaleString()} rows · ${dataset.columnCount} columns` : "Load a dataset to begin";
  document.querySelector("#sidebar-dataset-name").textContent = name;
  document.querySelector("#sidebar-dataset-size").textContent = size;
  document.querySelector("#composer-dataset").textContent = dataset ? name : "No dataset loaded";
  document.querySelector("#settings-dataset").textContent = dataset ? `${name} · ${size}` : "No dataset loaded";
  document.querySelector("#dataset-dot").style.visibility = dataset ? "visible" : "hidden";
}

function setHistory(history) {
  state.history = Array.isArray(history) ? history : [];
  document.querySelector("#history-count").textContent = String(state.history.length);
}

function addUserMessage(question) {
  const message = document.createElement("div");
  message.className = "message user-message";
  message.textContent = question;
  elements.conversation.append(message);
  message.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function resultTable(result, resultId) {
  const columns = result.columns || [];
  const rows = result.rows || [];
  const heading = columns.map((column, index) =>
    `<th scope="col"><button class="sort-head" type="button" data-sort="${index}" data-result="${resultId}">${escapeHtml(column)} ↕</button></th>`
  ).join("");
  const body = rows.map((row) => `<tr>${columns.map((column) =>
    `<td>${formatNumber(row[column])}</td>`).join("")}</tr>`).join("");
  return `<div class="table-scroll"><table class="result-table"><thead><tr>${heading}</tr></thead><tbody data-table-body="${resultId}">${body || `<tr><td class="table-empty" colspan="${Math.max(columns.length, 1)}">No matching records.</td></tr>`}</tbody></table></div>`;
}

function svgEscape(text) {
  return escapeHtml(text);
}

function chartMarkup(chart, result) {
  if (chart.type === "scatter") {
    const points = chart.points || [];
    if (!points.length) return '<div class="chart-empty">No numeric pairs available to chart.</div>';
    const width = 620, height = 210, left = 60, right = 18, top = 14, bottom = 40;
    const plotWidth = width - left - right, plotHeight = height - top - bottom;
    const xMin = Math.min(...points.map((point) => point.x));
    const xMax = Math.max(...points.map((point) => point.x));
    const yMin = Math.min(...points.map((point) => point.y));
    const yMax = Math.max(...points.map((point) => point.y));
    const xScale = (value) => left + ((value - xMin) / (xMax - xMin)) * plotWidth;
    const yScale = (value) => top + plotHeight - ((value - yMin) / (yMax - yMin)) * plotHeight;
    const grid = Array.from({ length: 4 }, (_, index) => {
      const ratio = index / 3;
      const x = left + ratio * plotWidth, y = top + ratio * plotHeight;
      return `<line x1="${x}" y1="${top}" x2="${x}" y2="${top + plotHeight}" class="grid-line"/><line x1="${left}" y1="${y}" x2="${left + plotWidth}" y2="${y}" class="grid-line"/><text x="${x}" y="${height - 20}" text-anchor="middle" class="axis-label">${formatNumber(xMin + ratio * (xMax - xMin))}</text><text x="${left - 8}" y="${y + 3}" text-anchor="end" class="axis-label">${formatNumber(yMax - ratio * (yMax - yMin))}</text>`;
    }).join("");
    const marks = points.map((point) =>
      `<circle cx="${xScale(point.x)}" cy="${yScale(point.y)}" r="4" fill="#4c7dde" fill-opacity=".72" class="chart-mark"><title>${svgEscape(chart.xLabel)}: ${formatNumber(point.x)}, ${svgEscape(chart.yLabel)}: ${formatNumber(point.y)}</title></circle>`
    ).join("");
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Scatter plot comparing ${svgEscape(chart.xLabel)} and ${svgEscape(chart.yLabel)}">${grid}${marks}<text x="${left + plotWidth / 2}" y="${height - 3}" text-anchor="middle" class="axis-label">${svgEscape(chart.xLabel)}</text><text x="13" y="${top + plotHeight / 2}" text-anchor="middle" class="axis-label" transform="rotate(-90 13 ${top + plotHeight / 2})">${svgEscape(chart.yLabel)}</text></svg>`;
  }
  const values = (chart.series || []).filter((item) => Number.isFinite(Number(item.value)));
  if (!values.length) return '<div class="chart-empty">No numeric values available to chart.</div>';
  if (chart.type === "kpi") {
    const value = values[0].value;
    return `<div class="chart-empty kpi-visual"><span><strong>${formatNumber(value)}</strong><small>${escapeHtml(result.columns?.[0] || "Result")}</small></span></div>`;
  }
  const width = 620;
  const height = 210;
  const left = 51;
  const right = 12;
  const top = 12;
  const bottom = 38;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const maxValue = Math.max(...values.map((item) => Number(item.value)), 0);
  const minValue = Math.min(...values.map((item) => Number(item.value)), 0);
  const chartMax = maxValue === minValue ? maxValue + 1 : maxValue + (maxValue - minValue) * 0.1;
  const chartMin = Math.min(0, minValue);
  const valueY = (value) => top + plotHeight - ((Number(value) - chartMin) / (chartMax - chartMin)) * plotHeight;
  const baseline = valueY(0);
  const tooltipPoints = values.map((item) =>
    `${svgEscape(item.label)}: ${formatNumber(item.value)}`).join(" · ");

  if (chart.type === "donut") {
    const positive = values.filter((item) => Number(item.value) > 0);
    const total = positive.reduce((sum, item) => sum + Number(item.value), 0);
    if (!positive.length || total <= 0) return '<div class="chart-empty">A distribution chart needs positive values.</div>';
    const cx = 180, cy = 105, radius = 62, stroke = 22;
    const circumference = 2 * Math.PI * radius;
    let offset = 0;
    const arcs = positive.map((item, index) => {
      const length = (Number(item.value) / total) * circumference;
      const path = `<circle cx="${cx}" cy="${cy}" r="${radius}" fill="none" stroke="${chartColors[index % chartColors.length]}" stroke-width="${stroke}" stroke-dasharray="${length} ${circumference - length}" stroke-dashoffset="${-offset}" transform="rotate(-90 ${cx} ${cy})"><title>${svgEscape(item.label)}: ${formatNumber(item.value)}</title></circle>`;
      offset += length;
      return path;
    }).join("");
    const legend = positive.slice(0, 7).map((item, index) =>
      `<div class="legend-row"><i style="background:${chartColors[index % chartColors.length]}"></i><span>${svgEscape(item.label)}</span><strong>${Math.round(Number(item.value) / total * 100)}%</strong></div>`
    ).join("");
    return `<div class="donut-wrap"><svg viewBox="0 0 360 210" role="img" aria-label="Donut chart showing category distribution">${arcs}<text x="${cx}" y="${cy - 2}" text-anchor="middle" class="donut-total">${formatNumber(total)}</text><text x="${cx}" y="${cy + 16}" text-anchor="middle" class="donut-caption">TOTAL</text></svg><div class="chart-legend">${legend}</div></div>`;
  }

  if (chart.type === "bar") {
    const labelWidth = Math.min(170, Math.max(100, ...values.map((item) => String(item.label).length * 6.2)));
    const innerWidth = width - left - right;
    const rowsAvailable = Math.max(1, Math.min(8, values.length));
    const rowHeight = Math.min(28, (height - top - bottom) / rowsAvailable);
    const actualHeight = top + rowHeight * values.length + bottom;
    const max = Math.max(maxValue, 1);
    const bars = values.map((item, index) => {
      const y = top + index * rowHeight + 4;
      const valueWidth = Math.max(1, (Number(item.value) / max) * (innerWidth - labelWidth - 37));
      const color = chartColors[index % chartColors.length];
      return `<text x="${labelWidth - 8}" y="${y + 11}" text-anchor="end" class="axis-label">${svgEscape(String(item.label).slice(0, 25))}</text><rect x="${labelWidth}" y="${y}" width="${valueWidth}" height="${Math.max(7, rowHeight - 8)}" rx="4" fill="${color}" class="chart-mark"><title>${svgEscape(item.label)}: ${formatNumber(item.value)}</title></rect><text x="${Math.min(width - 6, labelWidth + valueWidth + 6)}" y="${y + 11}" class="value-label">${formatNumber(item.value)}</text>`;
    }).join("");
    return `<svg viewBox="0 0 ${width} ${actualHeight}" role="img" aria-label="Horizontal bar chart">${bars}</svg>`;
  }

  const points = values.map((item, index) => ({
    x: left + (values.length === 1 ? plotWidth / 2 : (index / (values.length - 1)) * plotWidth),
    y: valueY(item.value),
    item,
  }));
  const grid = Array.from({ length: 4 }, (_, index) => {
    const y = top + (plotHeight / 3) * index;
    const value = chartMax - ((chartMax - chartMin) / 3) * index;
    return `<line x1="${left}" y1="${y}" x2="${width - right}" y2="${y}" class="grid-line"/><text x="${left - 7}" y="${y + 3}" text-anchor="end" class="axis-label">${formatNumber(value)}</text>`;
  }).join("");
  const line = points.map((point) => `${point.x},${point.y}`).join(" ");
  const area = `${left},${baseline} ${line} ${points.at(-1).x},${baseline}`;
  const labelStep = Math.max(1, Math.ceil(points.length / 8));
  const mark = points.map((point, index) =>
    `<circle cx="${point.x}" cy="${point.y}" r="4" fill="#4c7dde" stroke="#fff" stroke-width="2" class="chart-mark"><title>${svgEscape(point.item.label)}: ${formatNumber(point.item.value)}</title></circle>${index % labelStep === 0 || index === points.length - 1 ? `<text x="${point.x}" y="${height - 13}" text-anchor="middle" class="axis-label">${svgEscape(String(point.item.label).slice(0, 11))}</text>` : ""}`
  ).join("");
  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${chart.type} chart showing ${tooltipPoints}">${grid}${chart.type === "area" ? `<polygon points="${area}" fill="#4c7dde" fill-opacity=".12"/>` : ""}<polyline points="${line}" fill="none" stroke="#4c7dde" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>${mark}</svg>`;
}

function renderAnswer(result, options = {}) {
  const resultId = `result-${++state.resultCounter}`;
  const chartType = result.chart?.type || "none";
  const grouped = result.columns?.length > 1 && chartType !== "kpi";
  const chartOptions = chartType === "scatter"
    ? ["scatter", "none"]
    : grouped
    ? ["bar", "line", "area", "donut", "none"]
    : ["kpi", "none"];
  const optionsHtml = chartOptions.map((type) =>
    `<option value="${type}" ${type === chartType ? "selected" : ""}>${type === "none" ? "Hide chart" : type.charAt(0).toUpperCase() + type.slice(1)}</option>`
  ).join("");
  const card = document.createElement("article");
  card.className = "message answer-card";
  card.dataset.resultId = resultId;
  card._result = result;
  card.innerHTML = `
    <div class="answer-head">
      <span class="assistant-mark" aria-hidden="true">✦</span>
      <div class="answer-intro">
        <p>${escapeHtml(result.statement)}</p>
        <div class="answer-meta">Based on <strong>${escapeHtml(result.datasetName)}</strong> · ${Number(result.datasetRows || 0).toLocaleString()} source rows</div>
      </div>
      <div class="answer-actions">
        <button type="button" data-view-dataset="${resultId}" aria-label="View dataset used">
          <svg viewBox="0 0 24 24"><path d="M3 5h18M3 12h18M3 19h18M8 3v4m8 3v4m-5 3v4"/></svg><span>Dataset</span>
        </button>
        <button type="button" data-download-chart="${resultId}" aria-label="Download chart as PNG">
          <svg viewBox="0 0 24 24"><path d="M12 3v12m-5-5 5 5 5-5"/><path d="M4 17v3h16v-3"/></svg><span>PNG</span>
        </button>
      </div>
    </div>
    ${result.warning ? `<div class="answer-warning">${escapeHtml(result.warning)}</div>` : ""}
    <div class="answer-content ${chartType === "none" ? "single" : ""}">
      <section class="panel table-panel">
        <div class="panel-head"><h3>Results</h3><div class="table-tools">
          <input class="table-search" type="search" placeholder="Search…" aria-label="Search results" data-search="${resultId}">
          <button type="button" class="export-button" data-export="csv" data-result="${resultId}" title="Export CSV"><svg viewBox="0 0 24 24"><path d="M12 3v12m-5-5 5 5 5-5"/><path d="M4 17v3h16v-3"/></svg>CSV</button>
          <button type="button" class="export-button" data-export="xlsx" data-result="${resultId}" title="Export Excel"><svg viewBox="0 0 24 24"><path d="M12 3v12m-5-5 5 5 5-5"/><path d="M4 17v3h16v-3"/></svg>Excel</button>
        </div></div>
        ${resultTable(result, resultId)}
      </section>
      ${chartType === "none" ? "" : `<section class="panel chart-panel"><div class="panel-head"><h3>Visualization</h3>${grouped ? `<select class="chart-select" aria-label="Chart type" data-chart-select="${resultId}">${optionsHtml}</select>` : ""}</div><div class="chart-area" data-chart-area="${resultId}">${chartMarkup(result.chart, result)}</div></section>`}
    </div>
    <details class="methodology"><summary>How was this calculated?</summary><p>${escapeHtml(result.method)}</p></details>`;
  elements.conversation.append(card);
  if (!options.keepScroll) card.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return card;
}

function sortedRows(result, index, direction) {
  const column = result.columns[index];
  return [...result.rows].sort((a, b) => {
    const left = numberValue(a[column]), right = numberValue(b[column]);
    const comparison = left !== null && right !== null
      ? left - right
      : String(a[column] ?? "").localeCompare(String(b[column] ?? ""), undefined, { numeric: true });
    return direction === "asc" ? comparison : -comparison;
  });
}

function updateTable(card, rows) {
  const body = card.querySelector("tbody");
  const columns = card.querySelectorAll("thead th").length;
  if (!rows.length) {
    body.innerHTML = `<tr><td class="table-empty" colspan="${columns}">No matching results.</td></tr>`;
    return;
  }
  const keys = [...card.querySelectorAll("thead th")].map((th) => th.textContent.replace(/\s+↕$/, ""));
  body.innerHTML = rows.map((row) => `<tr>${keys.map((key) => `<td>${formatNumber(row[key])}</td>`).join("")}</tr>`).join("");
}

function showDatasetPreview(card) {
  const existing = card.querySelector(".dataset-preview");
  if (existing) {
    existing.remove();
    return;
  }
  if (!state.dataset) {
    notify("There is no dataset loaded to preview.");
    return;
  }
  const dataset = state.dataset;
  const preview = document.createElement("section");
  preview.className = "dataset-preview panel";
  preview.innerHTML = `<div class="panel-head"><h3>${escapeHtml(dataset.filename)} · ${dataset.rowCount.toLocaleString()} rows</h3><button class="text-button preview-close" type="button">Close</button></div><div class="dataset-summary">${dataset.columns.map((column) => `<span><strong>${escapeHtml(column.name)}</strong><small>${escapeHtml(column.type)} · ${column.missing} missing</small></span>`).join("")}<span><strong>${dataset.duplicateRows}</strong><small>duplicate rows</small></span></div><div class="table-scroll"><table class="result-table"><thead><tr>${dataset.columns.map((column) => `<th>${escapeHtml(column.name)}</th>`).join("")}</tr></thead><tbody>${dataset.preview.map((row) => `<tr>${dataset.columns.map((column) => `<td>${formatNumber(row[column.name])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  card.append(preview);
  preview.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function updateChart(card, result, type) {
  const area = card.querySelector(".chart-area");
  const panel = card.querySelector(".chart-panel");
  const layout = card.querySelector(".answer-content");
  if (type === "none") {
    panel.classList.add("hidden");
    layout.classList.add("single");
    area.replaceChildren();
    return;
  }
  panel.classList.remove("hidden");
  layout.classList.remove("single");
  area.innerHTML = chartMarkup({ ...result.chart, type }, result);
  const select = card.querySelector(".chart-select");
  if (select) select.value = type;
}

function saveBlob(blob, filename) {
  const link = document.createElement("a");
  const url = URL.createObjectURL(blob);
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function exportResult(result, format) {
  const response = await requestJson("/api/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ columns: result.columns, rows: result.rows, format }),
  });
  const blob = await response.blob();
  saveBlob(blob, `analysis.${format}`);
}

async function downloadChart(card) {
  const svg = card.querySelector(".chart-area svg");
  if (!svg) {
    notify("There is no chart to download for this answer.");
    return;
  }
  const markup = new XMLSerializer().serializeToString(svg);
  const image = new Image();
  const source = URL.createObjectURL(new Blob([markup], { type: "image/svg+xml;charset=utf-8" }));
  image.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(900, image.width * 2);
    canvas.height = Math.max(520, image.height * 2);
    const context = canvas.getContext("2d");
    if (!context) {
      URL.revokeObjectURL(source);
      notify("Your browser could not create a PNG image.");
      return;
    }
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      if (blob) saveBlob(blob, "data-desk-chart.png");
      else notify("Your browser could not export this chart.");
      URL.revokeObjectURL(source);
    }, "image/png");
  };
  image.onerror = () => {
    URL.revokeObjectURL(source);
    notify("The chart could not be converted to PNG.");
  };
  image.src = source;
}

async function ask(question) {
  const trimmed = question.trim();
  if (!trimmed || state.busy) return;
  elements.welcome.classList.add("hidden");
  addUserMessage(trimmed);
  elements.input.value = "";
  resizeInput();
  setBusy(true);
  try {
    const response = await requestJson("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: trimmed }),
    });
    renderAnswer(response.result);
    const refreshed = await requestJson("/api/state");
    setHistory(refreshed.history);
  } catch (error) {
    const errorCard = document.createElement("div");
    errorCard.className = "answer-card answer-warning message";
    errorCard.textContent = error.message || "The question could not be analyzed.";
    elements.conversation.append(errorCard);
    errorCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } finally {
    setBusy(false);
    elements.input.focus();
  }
}

async function loadSample() {
  try {
    const response = await requestJson("/api/sample");
    updateDataset(response.dataset);
    setHistory([]);
    elements.conversation.replaceChildren();
    elements.welcome.classList.remove("hidden");
    closeSettings();
    notify("Sample CRM dataset loaded.");
  } catch (error) {
    notify(error.message);
  }
}

async function uploadFile(file) {
  if (!file) return;
  if (file.size > 12 * 1024 * 1024) {
    notify("Choose a file smaller than 12 MB.");
    return;
  }
  const extension = file.name.split(".").pop().toLowerCase();
  if (!["csv", "xlsx", "json"].includes(extension)) {
    notify("Choose a CSV, XLSX, or JSON file.");
    return;
  }
  setBusy(true);
  try {
    const buffer = await file.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    let binary = "";
    const chunkSize = 0x8000;
    for (let offset = 0; offset < bytes.length; offset += chunkSize) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
    }
    const response = await requestJson("/api/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: file.name, contentBase64: btoa(binary) }),
    });
    updateDataset(response.dataset);
    setHistory([]);
    elements.conversation.replaceChildren();
    elements.welcome.classList.remove("hidden");
    notify(`Loaded ${file.name} with ${response.dataset.rowCount.toLocaleString()} rows.`);
  } catch (error) {
    notify(error.message || "The file could not be uploaded.");
  } finally {
    setBusy(false);
    elements.file.value = "";
  }
}

async function downloadOriginal() {
  try {
    const response = await fetch("/api/original");
    if (!response.ok) {
      const body = await response.json();
      throw new Error(body.error || "The source dataset could not be downloaded.");
    }
    const disposition = response.headers.get("content-disposition") || "";
    const filename = disposition.match(/filename="([^"]+)"/)?.[1] || "dataset";
    saveBlob(await response.blob(), filename);
  } catch (error) {
    notify(error.message);
  }
}

function openSettings() {
  elements.settings.classList.remove("hidden");
  elements.settings.querySelector("#modal-close").focus();
}

function closeSettings() {
  elements.settings.classList.add("hidden");
}

function resizeInput() {
  elements.input.style.height = "auto";
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 110)}px`;
}

function restoreHistory(item) {
  if (!item?.result) return;
  elements.welcome.classList.add("hidden");
  elements.conversation.replaceChildren();
  addUserMessage(item.question);
  renderAnswer(item.result, { keepScroll: true });
  elements.conversation.scrollIntoView({ behavior: "smooth", block: "end" });
  elements.sidebar.classList.remove("open");
}

document.addEventListener("click", async (event) => {
  const action = event.target.closest("[data-action]");
  if (action) {
    switch (action.dataset.action) {
      case "upload": elements.file.click(); break;
      case "settings": openSettings(); break;
      case "sample": await loadSample(); break;
      case "download-original": await downloadOriginal(); break;
    }
  }
  const suggestion = event.target.closest("[data-question]");
  if (suggestion) ask(suggestion.dataset.question);

  const nav = event.target.closest("[data-nav]");
  if (nav?.dataset.nav === "dashboard") {
    elements.welcome.classList.remove("hidden");
    elements.conversation.replaceChildren();
    elements.sidebar.classList.remove("open");
  } else if (nav?.dataset.nav === "history") {
    elements.sidebar.classList.remove("open");
    if (state.history.length) restoreHistory(state.history[0]);
    else notify("Your questions will appear here after your first analysis.");
  }

  const viewButton = event.target.closest("[data-view-dataset]");
  if (viewButton) showDatasetPreview(viewButton.closest(".answer-card"));
  if (event.target.closest(".preview-close")) {
    event.target.closest(".dataset-preview").remove();
  }
  const exportButton = event.target.closest("[data-export]");
  if (exportButton) {
    const card = exportButton.closest(".answer-card");
    const item = state.history.find((entry) => entry.result.question ===
      card.querySelector(".answer-intro p")?.textContent);
    const result = card._result || item?.result;
    if (result) {
      try { await exportResult(result, exportButton.dataset.export); }
      catch (error) { notify(error.message); }
    } else notify("The result could not be found for export.");
  }
  const pngButton = event.target.closest("[data-download-chart]");
  if (pngButton) downloadChart(pngButton.closest(".answer-card"));

  const sortButton = event.target.closest("[data-sort]");
  if (sortButton) {
    const card = sortButton.closest(".answer-card");
    const result = card._result;
    if (result) {
      card._sortDirection = card._sortDirection === "asc" ? "desc" : "asc";
      updateTable(card, sortedRows(result, Number(sortButton.dataset.sort), card._sortDirection));
    }
  }

  if (event.target === elements.settings) closeSettings();
});

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  ask(elements.input.value);
});
elements.input.addEventListener("input", resizeInput);
elements.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    ask(elements.input.value);
  }
});
elements.file.addEventListener("change", () => uploadFile(elements.file.files?.[0]));
document.querySelector("#menu-button").addEventListener("click", () => elements.sidebar.classList.toggle("open"));
document.querySelector("#modal-close").addEventListener("click", closeSettings);

elements.conversation.addEventListener("input", (event) => {
  const input = event.target.closest("[data-search]");
  if (!input) return;
  const card = input.closest(".answer-card");
  const result = card?._result;
  if (!result) return;
  const term = input.value.toLocaleLowerCase();
  const matching = result.rows.filter((row) =>
    result.columns.some((column) => String(row[column] ?? "").toLocaleLowerCase().includes(term)));
  updateTable(card, matching);
});

elements.conversation.addEventListener("change", (event) => {
  const select = event.target.closest("[data-chart-select]");
  if (!select) return;
  const card = select.closest(".answer-card");
  if (card?._result) updateChart(card, card._result, select.value);
});

async function initialize() {
  try {
    const response = await requestJson("/api/state");
    updateDataset(response.dataset);
    setHistory(response.history);
    const status = document.querySelector("#ai-status");
    const pill = document.querySelector("#ai-status-pill");
    if (response.aiAvailable) {
      status.textContent = "Gemini is configured on the local server";
      pill.textContent = "AI enabled";
      pill.classList.add("enabled");
    } else {
      status.textContent = "Using local question interpretation";
      pill.textContent = "Local";
      pill.classList.add("local");
    }
  } catch (error) {
    notify(`Could not connect to the local app: ${error.message}`);
  }
}

initialize();
