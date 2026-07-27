"use strict";

const GRAPH_CONFIG_KEY = "experiment-graph-config";
const HPBW_KEY = "experiment-hpbw-enabled";

const GRAPH_DEFINITIONS = [
    { id: "az-peak", title: "Azimuth · Peak Power", kind: "polar", direction: "horizontal", angle: "azimuth_angles", power: "peak", compass: true },
    { id: "az-center", title: "Azimuth · Center Power", kind: "polar", direction: "horizontal", angle: "azimuth_angles", power: "center", compass: true },
    { id: "el-peak", title: "Elevation · Peak Power", kind: "polar", direction: "vertical", angle: "elevation_angles", power: "peak", compass: false },
    { id: "el-center", title: "Elevation · Center Power", kind: "polar", direction: "vertical", angle: "elevation_angles", power: "center", compass: false },
    { id: "path-pan-tilt", title: "Path of Travel · Pan / Tilt", kind: "path", frame: "pan-tilt" },
    { id: "power-time", title: "Power vs. Time", kind: "time", series: "power" },
    { id: "pan-peak", title: "Pan · Peak Power", kind: "polar", direction: "horizontal", angle: "pan_angles", power: "peak", compass: true },
    { id: "pan-center", title: "Pan · Center Power", kind: "polar", direction: "horizontal", angle: "pan_angles", power: "center", compass: true },
    { id: "tilt-peak", title: "Tilt · Peak Power", kind: "polar", direction: "vertical", angle: "tilt_angles", power: "peak", compass: false },
    { id: "tilt-center", title: "Tilt · Center Power", kind: "polar", direction: "vertical", angle: "tilt_angles", power: "center", compass: false },
    { id: "path-az-el", title: "Path of Travel · Azimuth / Elevation", kind: "path", frame: "az-el" },
    { id: "freq-time", title: "Frequency vs. Time", kind: "time", series: "frequency" },
    { id: "az-el-peak-heat", title: "Azimuth / Elevation · Peak Power Heatmap", kind: "heatmap", frame: "az-el", power: "peak_amplitude" },
    { id: "az-el-center-heat", title: "Azimuth / Elevation · Center Power Heatmap", kind: "heatmap", frame: "az-el", power: "center_amplitude" },
    { id: "pan-tilt-peak-heat", title: "Pan / Tilt · Peak Power Heatmap", kind: "heatmap", frame: "pan-tilt", power: "peak_amplitude" },
    { id: "pan-tilt-center-heat", title: "Pan / Tilt · Center Power Heatmap", kind: "heatmap", frame: "pan-tilt", power: "center_amplitude" },
];

const GRAPH_GROUPS = [
    { id: "all", label: "All", members: GRAPH_DEFINITIONS.map((graph) => graph.id) },
    { id: "az-el", label: "Az/El", members: ["az-peak", "az-center", "el-peak", "el-center", "path-az-el", "az-el-peak-heat", "az-el-center-heat"] },
    { id: "pan-tilt", label: "Pan/Tilt", members: ["pan-peak", "pan-center", "tilt-peak", "tilt-center", "path-pan-tilt", "pan-tilt-peak-heat", "pan-tilt-center-heat"] },
    { id: "peak", label: "Peak Power", members: ["az-peak", "el-peak", "pan-peak", "tilt-peak", "power-time", "freq-time", "az-el-peak-heat", "pan-tilt-peak-heat"] },
    { id: "center", label: "Center Power", members: ["az-center", "el-center", "pan-center", "tilt-center", "power-time", "az-el-center-heat", "pan-tilt-center-heat"] },
];

let latestStatus = null;
let latestTurntable = null;
let pathPlan = null;
let resultsPayload = null;
let planVersion = null;
let resultsKey = null;
let visitedPointKeys = new Set();
let requestInFlight = false;
let graphConfig = loadGraphConfig();
let hpbwEnabled = loadBoolean(HPBW_KEY, false);
let graphConfigRevision = 0;
let renderedGraphKey = null;
let renderGeneration = 0;

function cssColor(name, fallback) {
    return window.getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function readStorage(key) {
    try {
        return window.localStorage.getItem(key);
    } catch {
        return null;
    }
}

function writeStorage(key, value) {
    try {
        window.localStorage.setItem(key, value);
    } catch {
        // Settings remain active for this page load.
    }
}

function loadBoolean(key, fallback) {
    const stored = readStorage(key);
    return stored === null ? fallback : stored === "true";
}

function loadGraphConfig() {
    let stored = [];
    try {
        stored = JSON.parse(readStorage(GRAPH_CONFIG_KEY) || "[]");
    } catch {
        stored = [];
    }
    const knownIds = new Set(GRAPH_DEFINITIONS.map((graph) => graph.id));
    const normalized = Array.isArray(stored)
        ? stored
            .filter((item) => item && knownIds.has(item.id))
            .map((item, index) => ({
                id: item.id,
                enabled: item.enabled !== false,
                order: Number.isFinite(item.order) ? item.order : index,
            }))
        : [];
    const existing = new Set(normalized.map((item) => item.id));
    GRAPH_DEFINITIONS.forEach((graph, index) => {
        if (!existing.has(graph.id)) {
            normalized.push({ id: graph.id, enabled: true, order: normalized.length + index });
        }
    });
    normalized.sort((left, right) => left.order - right.order);
    normalized.forEach((item, index) => { item.order = index; });
    return normalized;
}

function persistGraphConfig() {
    writeStorage(GRAPH_CONFIG_KEY, JSON.stringify(graphConfig));
}

function graphDefinition(id) {
    return GRAPH_DEFINITIONS.find((graph) => graph.id === id);
}

function pointKey(cutId, pointIndex) {
    return `${cutId}:${pointIndex}`;
}

function angle(value) {
    return Number.isFinite(value) ? `${value.toFixed(2).replace(/\.?0+$/, "")}°` : "—";
}

function humanize(value) {
    return String(value || "empty").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

async function requestJson(url) {
    const response = await window.fetch(url, { headers: { Accept: "application/json" } });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "The request failed.");
    return payload;
}

function setFeedback(message, error = false) {
    const feedback = document.querySelector("[data-feedback]");
    feedback.textContent = message;
    feedback.classList.toggle("is-error", error);
}

function setMenuOpen(isOpen) {
    const toggle = document.getElementById("menu-toggle");
    const menu = document.getElementById("application-menu");
    if (!toggle || !menu) return;
    toggle.setAttribute("aria-expanded", String(isOpen));
    menu.hidden = !isOpen;
}

function setColorMode(mode, persist = true) {
    if (mode !== "light" && mode !== "dark") return;
    document.documentElement.dataset.colorMode = mode;
    const input = document.querySelector(`input[name="color_mode"][value="${mode}"]`);
    if (input) input.checked = true;
    if (persist) writeStorage("grid-designer-color-mode", mode);
    renderedGraphKey = null;
    renderAll();
}

function convertPanTilt(pan, tilt) {
    const panRadians = pan * Math.PI / 180;
    const tiltRadians = tilt * Math.PI / 180;
    const x = Math.cos(tiltRadians) * Math.cos(panRadians);
    const y = Math.sin(panRadians);
    const z = Math.sin(tiltRadians) * Math.cos(panRadians);
    return {
        azimuth: Math.atan2(y, x) * 180 / Math.PI,
        elevation: Math.asin(z) * 180 / Math.PI,
    };
}

function degreeAxis(title, anchor = null) {
    const tickvals = Array.from({ length: 25 }, (_, index) => -180 + index * 15);
    return {
        title,
        tickmode: "array",
        tickvals,
        ticktext: tickvals.map((value) => value % 45 === 0 ? `${value}°` : ""),
        range: [-180, 180],
        gridcolor: cssColor("--plot-grid", "#8fa6d2"),
        zerolinecolor: cssColor("--plot-zero", "#5f79ad"),
        ...(anchor ? { scaleanchor: anchor, scaleratio: 1 } : {}),
    };
}

function baseLayout(plot, extra = {}) {
    return {
        autosize: false,
        width: plot.clientWidth,
        height: Math.max(430, plot.clientHeight),
        margin: { t: 25, r: 30, b: 55, l: 55 },
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: cssColor("--plot-background", "#d1e0ff"),
        font: { color: cssColor("--text", "#000") },
        ...extra,
    };
}

function emptyPlot(plot, message) {
    window.Plotly.react(
        plot,
        [],
        baseLayout(plot, {
            xaxis: { visible: false },
            yaxis: { visible: false },
            annotations: [{
                text: message,
                x: 0.5,
                y: 0.5,
                xref: "paper",
                yref: "paper",
                showarrow: false,
            }],
        }),
        { responsive: true, displaylogo: false },
    );
}

function pathCoordinates(frame, visited) {
    const x = [];
    const y = [];
    const customdata = [];
    (pathPlan?.cuts || []).forEach((cut) => {
        cut.points.forEach((point) => {
            if (visitedPointKeys.has(pointKey(point.cut_id, point.point_index)) !== visited) return;
            x.push(frame === "pan-tilt" ? point.pan : point.azimuth);
            y.push(frame === "pan-tilt" ? point.tilt : point.elevation);
            customdata.push([point.cut_id, point.point_index, point.point_in_cut]);
        });
    });
    return { x, y, customdata };
}

function routeCoordinates(frame, visited) {
    const x = [];
    const y = [];
    (pathPlan?.cuts || []).forEach((cut) => {
        for (let index = 1; index < cut.points.length; index += 1) {
            const previous = cut.points[index - 1];
            const current = cut.points[index];
            if (visitedPointKeys.has(pointKey(current.cut_id, current.point_index)) !== visited) continue;
            x.push(
                frame === "pan-tilt" ? previous.pan : previous.azimuth,
                frame === "pan-tilt" ? current.pan : current.azimuth,
                null,
            );
            y.push(
                frame === "pan-tilt" ? previous.tilt : previous.elevation,
                frame === "pan-tilt" ? current.tilt : current.elevation,
                null,
            );
        }
    });
    return { x, y };
}

function renderPath(definition, plot) {
    if (!pathPlan) {
        emptyPlot(plot, "No experiment path is loaded.");
        return;
    }
    const frame = definition.frame;
    const pendingColor = "#aeb6c2";
    const visitedColor = "#555e6b";
    const traces = [
        { type: "scatter", mode: "lines", name: "Pending route", ...routeCoordinates(frame, false), line: { color: pendingColor, width: 2 }, hoverinfo: "skip" },
        { type: "scatter", mode: "lines", name: "Visited route", ...routeCoordinates(frame, true), line: { color: visitedColor, width: 3 }, hoverinfo: "skip" },
        {
            type: "scatter", mode: "markers", name: "Pending points", ...pathCoordinates(frame, false),
            marker: { color: pendingColor, size: 6 },
            hovertemplate: "Pending point %{customdata[1]}<br>Cut %{customdata[0]}<br>x %{x:.2f}°<br>y %{y:.2f}°<extra></extra>",
        },
        {
            type: "scatter", mode: "markers", name: "Visited points", ...pathCoordinates(frame, true),
            marker: { color: visitedColor, size: 7 },
            hovertemplate: "Visited point %{customdata[1]}<br>Cut %{customdata[0]}<br>x %{x:.2f}°<br>y %{y:.2f}°<extra></extra>",
        },
    ];
    const target = latestStatus?.state === "running" ? latestStatus.progress?.target : null;
    if (target && Number.isFinite(target.pan) && Number.isFinite(target.tilt)) {
        const converted = convertPanTilt(target.pan, target.tilt);
        traces.push({
            type: "scatter", mode: "markers", name: "Travelling to",
            x: [frame === "pan-tilt" ? target.pan : converted.azimuth],
            y: [frame === "pan-tilt" ? target.tilt : converted.elevation],
            marker: { color: cssColor("--plot-origin", "#d62728"), size: 16, symbol: "diamond", line: { color: cssColor("--text", "#fff"), width: 2 } },
        });
    }
    const actual = latestTurntable?.state?.corrected_position;
    if (actual && Number.isFinite(actual.pan) && Number.isFinite(actual.tilt)) {
        const converted = convertPanTilt(actual.pan, actual.tilt);
        traces.push({
            type: "scatter", mode: "markers", name: "Actual position",
            x: [frame === "pan-tilt" ? actual.pan : converted.azimuth],
            y: [frame === "pan-tilt" ? actual.tilt : converted.elevation],
            marker: { color: cssColor("--plot-source", "#2ca02c"), size: 15, line: { color: cssColor("--text", "#fff"), width: 2 } },
        });
    }
    window.Plotly.react(plot, traces, baseLayout(plot, {
        margin: { t: 15, r: 25, b: 65, l: 65 },
        legend: { orientation: "h", x: 0.5, xanchor: "center", y: -0.18 },
        uirevision: `${definition.id}-${pathPlan.version}`,
        xaxis: degreeAxis(frame === "pan-tilt" ? "Pan" : "Azimuth"),
        yaxis: degreeAxis(frame === "pan-tilt" ? "Tilt" : "Elevation", "x"),
    }), { responsive: true, displaylogo: false });
}

function polarTicks() {
    const values = Array.from({ length: 24 }, (_, index) => index * 15);
    return {
        values,
        text: values.map((value) => {
            if (value % 45 !== 0) return "";
            return `${value > 180 ? value - 360 : value}°`;
        }),
    };
}

function computeHpbw(thetas, powers) {
    const pairs = thetas
        .map((theta, index) => [theta, powers[index]])
        .filter(([theta, power]) => Number.isFinite(theta) && Number.isFinite(power))
        .sort((left, right) => left[0] - right[0]);
    if (pairs.length < 3) return null;
    const maximum = Math.max(...pairs.map((pair) => pair[1]));
    const peakIndexes = pairs
        .map((pair, index) => pair[1] === maximum ? index : -1)
        .filter((index) => index >= 0);
    const peakIndex = peakIndexes[Math.floor(peakIndexes.length / 2)];
    const halfPower = maximum - 3.01;
    let leftIndex = 0;
    let rightIndex = pairs.length - 1;
    for (let index = peakIndex - 1; index >= 0; index -= 1) {
        if (pairs[index][1] < halfPower) {
            leftIndex = index + 1;
            break;
        }
    }
    for (let index = peakIndex + 1; index < pairs.length; index += 1) {
        if (pairs[index][1] < halfPower) {
            rightIndex = index - 1;
            break;
        }
    }
    return {
        maximum,
        peakTheta: pairs[peakIndex][0],
        halfPower,
        leftTheta: pairs[leftIndex][0],
        rightTheta: pairs[rightIndex][0],
        width: pairs[rightIndex][0] - pairs[leftIndex][0],
    };
}

function hpbwTraces(result, floor, cutId) {
    const circleThetas = Array.from({ length: 361 }, (_, index) => index);
    const radius = (value) => Math.max(value, floor) - floor;
    const line = { color: "#111111", width: 3 };
    return [
        {
            type: "scatterpolar", theta: circleThetas, r: circleThetas.map(() => radius(result.maximum)),
            mode: "lines", line, name: `HPBW ${cutId}: ${result.width.toFixed(1)}° (${result.leftTheta.toFixed(1)}° to ${result.rightTheta.toFixed(1)}°)`,
        },
        {
            type: "scatterpolar", theta: circleThetas, r: circleThetas.map(() => radius(result.halfPower)),
            mode: "lines", line: { ...line, dash: "dash" }, name: "Half power", showlegend: false,
        },
        {
            type: "scatterpolar", theta: [result.leftTheta, result.leftTheta], r: [0, radius(result.maximum)],
            mode: "lines", line, name: "Left HPBW", showlegend: false,
        },
        {
            type: "scatterpolar", theta: [result.rightTheta, result.rightTheta], r: [0, radius(result.maximum)],
            mode: "lines", line, name: "Right HPBW", showlegend: false,
        },
        {
            type: "scatterpolar", theta: [result.peakTheta, result.peakTheta], r: [0, radius(result.maximum)],
            mode: "lines", line: { ...line, dash: "dash" }, name: "Peak", showlegend: false,
        },
    ];
}

function renderPolar(definition, plot) {
    const cuts = (resultsPayload?.cuts || []).filter((cut) => cut.direction === definition.direction);
    if (!cuts.length) {
        emptyPlot(plot, `No ${definition.direction} cut data yet.`);
        return;
    }
    const allValues = cuts.flatMap((cut) =>
        cut[definition.power].normalized_db.filter(Number.isFinite),
    );
    const floor = Math.max(
        -60,
        Math.min(-5, Math.floor((allValues.length ? Math.min(...allValues) : -5) / 5) * 5),
    );
    const dataTraces = cuts.map((cut) => ({
        type: "scatterpolar",
        mode: "lines+markers",
        name: cut.id,
        theta: cut[definition.angle],
        r: cut[definition.power].normalized_db.map((value) =>
            Number.isFinite(value) ? Math.max(value, floor) - floor : null,
        ),
        customdata: cut[definition.power].absolute_dbm.map((value, index) => [
            cut[definition.power].normalized_db[index],
            value,
            cut.point_indexes[index],
        ]),
        marker: { size: 6 },
        hovertemplate: `${cut.id}<br>Angle %{theta:.2f}°<br>Relative %{customdata[0]:.2f} dB<br>Absolute %{customdata[1]:.2f} dBm<br>Point %{customdata[2]}<extra></extra>`,
    }));
    const overlayTraces = [];
    if (hpbwEnabled) {
        cuts.forEach((cut) => {
            const result = computeHpbw(
                cut[definition.angle],
                cut[definition.power].normalized_db,
            );
            if (result) overlayTraces.push(...hpbwTraces(result, floor, cut.id));
        });
    }
    const radialTickvals = [];
    const radialTicktext = [];
    for (let value = floor; value <= 0; value += 5) {
        radialTickvals.push(value - floor);
        radialTicktext.push(`${value}`);
    }
    const ticks = polarTicks();
    window.Plotly.react(plot, [...overlayTraces, ...dataTraces], baseLayout(plot, {
        margin: { t: 25, r: 30, b: 55, l: 30 },
        legend: { orientation: "h", x: 0.5, xanchor: "center", y: -0.08 },
        uirevision: `${definition.id}-${resultsPayload?.version || "empty"}-${hpbwEnabled}`,
        polar: {
            bgcolor: cssColor("--surface-muted", "#c2d5ff"),
            angularaxis: {
                tickmode: "array", tickvals: ticks.values, ticktext: ticks.text,
                rotation: definition.compass ? 90 : 0,
                direction: definition.compass ? "clockwise" : "counterclockwise",
                gridcolor: cssColor("--plot-grid", "#8fa6d2"),
            },
            radialaxis: {
                range: [0, -floor],
                tickvals: radialTickvals,
                ticktext: radialTicktext,
                ticksuffix: " dB",
                angle: 45,
                gridcolor: cssColor("--plot-grid", "#8fa6d2"),
            },
        },
    }), { responsive: true, displaylogo: false });
}

function renderTimeSeries(definition, plot) {
    const rows = resultsPayload?.rows || [];
    const series = definition.series === "power"
        ? [
            { column: "peak_amplitude", label: "Peak power", units: "dBm" },
            { column: "center_amplitude", label: "Center power", units: "dBm" },
        ]
        : [
            { column: "peak_frequency", label: "Peak frequency", units: "Hz" },
            { column: "center_frequency", label: "Center frequency", units: "Hz" },
        ];
    const traces = series.map((item) => {
        const data = rows.filter((row) => row.timestamp && Number.isFinite(row[item.column]));
        return {
            type: "scatter",
            mode: "lines+markers",
            name: item.label,
            x: data.map((row) => row.timestamp),
            y: data.map((row) => row[item.column]),
            customdata: data.map((row) => [row.cut_id, row.point_index]),
            hovertemplate: `${item.label}<br>%{x}<br>%{y:.4g} ${item.units}<br>Cut %{customdata[0]} · point %{customdata[1]}<extra></extra>`,
        };
    }).filter((trace) => trace.x.length);
    if (!traces.length) {
        emptyPlot(plot, `No ${definition.series} time-series data yet.`);
        return;
    }
    window.Plotly.react(plot, traces, baseLayout(plot, {
        legend: { orientation: "h", x: 0.5, xanchor: "center", y: -0.16 },
        xaxis: { title: "Time", gridcolor: cssColor("--plot-grid", "#8fa6d2") },
        yaxis: {
            title: definition.series === "power" ? "Power (dBm)" : "Frequency (Hz)",
            gridcolor: cssColor("--plot-grid", "#8fa6d2"),
        },
    }), { responsive: true, displaylogo: false });
}

function heatmapBins(definition) {
    const bins = resultsPayload?.heatmap_bin_sizes || {
        horizontal_degrees: 3,
        vertical_degrees: 3,
    };
    return {
        x: bins.horizontal_degrees,
        y: bins.vertical_degrees,
        xName: definition.frame === "pan-tilt" ? "Pan" : "Azimuth",
        yName: definition.frame === "pan-tilt" ? "Tilt" : "Elevation",
        xColumn: definition.frame === "pan-tilt" ? "commanded_pan" : "commanded_azimuth",
        yColumn: definition.frame === "pan-tilt" ? "commanded_tilt" : "commanded_elevation",
    };
}

function heatmapTitle(definition) {
    const bins = heatmapBins(definition);
    return `${definition.title} · ${bins.x}° ${bins.xName.toLowerCase()} × ${bins.y}° ${bins.yName.toLowerCase()} bins`;
}

function renderHeatmap(definition, plot) {
    const bins = heatmapBins(definition);
    const values = new Map();
    (resultsPayload?.rows || []).forEach((row) => {
        const x = row[bins.xColumn];
        const y = row[bins.yColumn];
        const power = row[definition.power];
        if (![x, y, power].every(Number.isFinite)) return;
        const binnedX = Math.round(x / bins.x) * bins.x;
        const binnedY = Math.round(y / bins.y) * bins.y;
        const key = `${binnedX}|${binnedY}`;
        const existing = values.get(key) || { x: binnedX, y: binnedY, powers: [] };
        existing.powers.push(power);
        values.set(key, existing);
    });
    if (!values.size) {
        emptyPlot(plot, "No heatmap data yet.");
        return;
    }
    const xs = [...new Set([...values.values()].map((value) => value.x))].sort((a, b) => a - b);
    const ys = [...new Set([...values.values()].map((value) => value.y))].sort((a, b) => a - b);
    const z = ys.map((y) => xs.map((x) => {
        const entry = values.get(`${x}|${y}`);
        return entry
            ? entry.powers.reduce((sum, power) => sum + power, 0) / entry.powers.length
            : null;
    }));
    window.Plotly.react(plot, [{
        type: "heatmap",
        x: xs,
        y: ys,
        z,
        connectgaps: false,
        colorbar: { title: "dBm" },
        hovertemplate: `${bins.xName} %{x:.1f}°<br>${bins.yName} %{y:.1f}°<br>Power %{z:.2f} dBm<extra></extra>`,
    }], baseLayout(plot, {
        xaxis: degreeAxis(bins.xName),
        yaxis: degreeAxis(bins.yName, "x"),
    }), { responsive: true, displaylogo: false });
}

function enabledGraphConfig() {
    return [...graphConfig]
        .sort((left, right) => left.order - right.order)
        .filter((item) => item.enabled);
}

function rebuildGraphGrid() {
    const grid = document.querySelector("[data-graph-grid]");
    grid.querySelectorAll(".dashboard-plot").forEach((plot) => window.Plotly?.purge(plot));
    grid.replaceChildren();
    enabledGraphConfig().forEach((item) => {
        const definition = graphDefinition(item.id);
        const card = document.createElement("article");
        card.className = "dashboard-graph-card";
        card.dataset.graphId = definition.id;
        const header = document.createElement("header");
        const heading = document.createElement("h3");
        heading.textContent = definition.kind === "heatmap"
            ? heatmapTitle(definition)
            : definition.title;
        header.append(heading);
        const plot = document.createElement("div");
        plot.className = "dashboard-plot";
        plot.dataset.graphPlot = definition.id;
        card.append(header, plot);
        grid.append(card);
    });
    graphConfigRevision += 1;
    renderedGraphKey = null;
}

function updateHeatmapHeadings() {
    GRAPH_DEFINITIONS.filter((definition) => definition.kind === "heatmap").forEach((definition) => {
        const heading = document.querySelector(
            `[data-graph-id="${definition.id}"] h3`,
        );
        if (heading) heading.textContent = heatmapTitle(definition);
    });
}

function renderGraph(definition, plot) {
    if (definition.kind === "path") renderPath(definition, plot);
    if (definition.kind === "polar") renderPolar(definition, plot);
    if (definition.kind === "time") renderTimeSeries(definition, plot);
    if (definition.kind === "heatmap") renderHeatmap(definition, plot);
}

function scheduleFullGraphRender(renderKey) {
    const generation = ++renderGeneration;
    window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
            if (generation !== renderGeneration) return;
            enabledGraphConfig().forEach((item) => {
                const definition = graphDefinition(item.id);
                const plot = document.querySelector(`[data-graph-plot="${item.id}"]`);
                if (plot?.isConnected) renderGraph(definition, plot);
            });
            renderedGraphKey = renderKey;
        });
    });
}

function renderLivePaths() {
    enabledGraphConfig().forEach((item) => {
        const definition = graphDefinition(item.id);
        if (definition.kind !== "path") return;
        const plot = document.querySelector(`[data-graph-plot="${item.id}"]`);
        if (plot?.isConnected) renderPath(definition, plot);
    });
}

function renderAll() {
    const loaded = Boolean(latestStatus?.loaded);
    document.querySelector("[data-graph-panel]").hidden = !loaded;
    const renderKey = [
        resultsKey || "no-results",
        planVersion || "no-plan",
        document.documentElement.dataset.colorMode,
        hpbwEnabled,
        graphConfigRevision,
    ].join(":");
    if (loaded && renderKey !== renderedGraphKey) {
        scheduleFullGraphRender(renderKey);
    } else if (loaded) {
        renderLivePaths();
    }
    const actual = latestTurntable?.state?.corrected_position;
    document.querySelector("[data-path-position]").textContent =
        actual ? `Actual pan ${angle(actual.pan)} · tilt ${angle(actual.tilt)}` : "Actual position unavailable";
}

function updateConfigFromItems() {
    const items = [...document.querySelectorAll("[data-graph-settings-items] .graph-settings-item")];
    graphConfig = items.map((element, index) => ({
        id: element.dataset.graphId,
        enabled: element.querySelector("input").checked,
        order: index,
    }));
    persistGraphConfig();
    rebuildGraphGrid();
    renderSettings();
    renderAll();
}

function renderSettingsGroups() {
    const container = document.querySelector("[data-graph-settings-groups]");
    container.replaceChildren();
    GRAPH_GROUPS.forEach((group) => {
        const enabled = new Set(graphConfig.filter((item) => item.enabled).map((item) => item.id));
        const enabledCount = group.members.filter((id) => enabled.has(id)).length;
        const row = document.createElement("div");
        row.className = "graph-settings-group";
        row.dataset.graphGroup = group.id;
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "graph-settings-check";
        checkbox.checked = enabledCount === group.members.length;
        checkbox.indeterminate = enabledCount > 0 && enabledCount < group.members.length;
        checkbox.tabIndex = -1;
        const label = document.createElement("span");
        label.textContent = group.label;
        row.append(checkbox, label);
        row.addEventListener("click", () => {
            const shouldEnable = enabledCount !== group.members.length;
            graphConfig.forEach((item) => {
                if (group.members.includes(item.id)) item.enabled = shouldEnable;
            });
            persistGraphConfig();
            rebuildGraphGrid();
            renderSettings();
            renderAll();
        });
        container.append(row);
    });
}

function renderSettings() {
    renderSettingsGroups();
    const container = document.querySelector("[data-graph-settings-items]");
    container.replaceChildren();
    [...graphConfig].sort((left, right) => left.order - right.order).forEach((item) => {
        const definition = graphDefinition(item.id);
        const row = document.createElement("div");
        row.className = "graph-settings-item";
        row.dataset.graphId = item.id;
        row.draggable = true;
        const handle = document.createElement("button");
        handle.type = "button";
        handle.className = "graph-drag-handle";
        handle.textContent = "⠿";
        handle.setAttribute("aria-label", `Reorder ${definition.title}`);
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "graph-settings-check";
        checkbox.checked = item.enabled;
        checkbox.setAttribute("aria-label", `Show ${definition.title}`);
        const label = document.createElement("span");
        label.className = "graph-settings-label";
        label.textContent = definition.title;
        checkbox.addEventListener("change", updateConfigFromItems);
        row.append(handle, checkbox, label);
        container.append(row);
    });
    const hpbw = document.querySelector("[data-hpbw-enabled]");
    hpbw.checked = hpbwEnabled;
}

function attachSettingsDragAndDrop() {
    const container = document.querySelector("[data-graph-settings-items]");
    let dragSource = null;
    container.addEventListener("dragstart", (event) => {
        dragSource = event.target.closest(".graph-settings-item");
        if (!dragSource) return;
        dragSource.classList.add("is-dragging");
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", dragSource.dataset.graphId);
    });
    container.addEventListener("dragover", (event) => {
        event.preventDefault();
        const target = event.target.closest(".graph-settings-item");
        container.querySelectorAll(".is-drag-over").forEach((item) => item.classList.remove("is-drag-over"));
        if (target && target !== dragSource) target.classList.add("is-drag-over");
    });
    container.addEventListener("drop", (event) => {
        event.preventDefault();
        const target = event.target.closest(".graph-settings-item");
        if (!dragSource || !target || dragSource === target) return;
        const items = [...container.children];
        if (items.indexOf(dragSource) < items.indexOf(target)) {
            container.insertBefore(dragSource, target.nextSibling);
        } else {
            container.insertBefore(dragSource, target);
        }
        updateConfigFromItems();
    });
    container.addEventListener("dragend", () => {
        dragSource?.classList.remove("is-dragging");
        container.querySelectorAll(".is-drag-over").forEach((item) => item.classList.remove("is-drag-over"));
        dragSource = null;
    });
}

function setSettingsOpen(open) {
    document.querySelector("[data-graph-settings-overlay]").hidden = !open;
    if (open) renderSettings();
}

async function refresh() {
    if (requestInFlight) return;
    requestInFlight = true;
    try {
        latestStatus = await requestJson("/experiment/status");
        const state = document.querySelector("[data-experiment-state]");
        state.textContent = humanize(latestStatus.state).toUpperCase();
        state.dataset.state = latestStatus.state;
        document.querySelector("[data-graph-description]").textContent = latestStatus.experiment
            ? `${latestStatus.experiment.short_description} · ${latestStatus.experiment.long_description}`
            : "Load an experiment on the Experiment page to view its route and measurements.";
        const nextPlanVersion = latestStatus.plan?.version;
        if (nextPlanVersion && nextPlanVersion !== planVersion) {
            pathPlan = await requestJson("/experiment/plan");
            planVersion = nextPlanVersion;
            renderedGraphKey = null;
        }
        const nextResultsKey = latestStatus.results?.available
            ? `${latestStatus.results.path}:${latestStatus.results.version}`
            : null;
        if (nextResultsKey !== resultsKey) {
            resultsPayload = nextResultsKey ? await requestJson("/experiment/results") : null;
            resultsKey = nextResultsKey;
            visitedPointKeys = new Set((resultsPayload?.visited_points || []).map((point) => pointKey(point.cut_id, point.point_index)));
            document.querySelector("[data-results-path]").textContent = resultsPayload?.source_path || "—";
            updateHeatmapHeadings();
            renderedGraphKey = null;
        }
        try {
            latestTurntable = await requestJson("/turntable/status?max_time=1&max_points=1");
        } catch {
            latestTurntable = null;
        }
        renderAll();
        setFeedback(latestStatus.loaded ? "Graphs update automatically while the experiment runs." : "No experiment is loaded.");
    } catch (error) {
        setFeedback(error.message, true);
    } finally {
        requestInFlight = false;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("menu-toggle")?.addEventListener("click", (event) => {
        event.stopPropagation();
        setMenuOpen(document.getElementById("application-menu")?.hidden ?? true);
    });
    document.addEventListener("click", (event) => {
        const menu = document.getElementById("application-menu");
        const toggle = document.getElementById("menu-toggle");
        if (menu && !menu.hidden && !menu.contains(event.target) && !toggle?.contains(event.target)) setMenuOpen(false);
    });
    document.querySelectorAll('input[name="color_mode"]').forEach((input) => {
        input.addEventListener("change", () => setColorMode(input.value));
    });
    document.querySelector("[data-open-graph-settings]").addEventListener("click", () => setSettingsOpen(true));
    document.querySelector("[data-close-graph-settings]").addEventListener("click", () => setSettingsOpen(false));
    document.querySelector("[data-graph-settings-overlay]").addEventListener("click", (event) => {
        if (event.target.matches("[data-graph-settings-overlay]")) setSettingsOpen(false);
    });
    document.querySelector("[data-hpbw-enabled]").addEventListener("change", (event) => {
        hpbwEnabled = event.target.checked;
        writeStorage(HPBW_KEY, String(hpbwEnabled));
        renderedGraphKey = null;
        renderAll();
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") setSettingsOpen(false);
    });
    attachSettingsDragAndDrop();
    rebuildGraphGrid();
    setColorMode(document.documentElement.dataset.colorMode, false);
    refresh();
    const timer = window.setInterval(refresh, 1000);
    window.addEventListener("pagehide", () => window.clearInterval(timer));
});
