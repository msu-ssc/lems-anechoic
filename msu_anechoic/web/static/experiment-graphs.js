"use strict";

let latestStatus = null;
let latestTurntable = null;
let pathPlan = null;
let resultsPayload = null;
let planVersion = null;
let resultsKey = null;
let polarRenderedKey = null;
let visitedPointKeys = new Set();
let requestInFlight = false;

const POLAR_DEFINITIONS = {
    horizontal: [
        { id: "pan-peak", title: "Pan · Peak Power", angle: "pan_angles", power: "peak", compass: true },
        { id: "pan-center", title: "Pan · Center Power", angle: "pan_angles", power: "center", compass: true },
        { id: "az-peak", title: "Azimuth · Peak Power", angle: "azimuth_angles", power: "peak", compass: true },
        { id: "az-center", title: "Azimuth · Center Power", angle: "azimuth_angles", power: "center", compass: true },
    ],
    vertical: [
        { id: "tilt-peak", title: "Tilt · Peak Power", angle: "tilt_angles", power: "peak", compass: false },
        { id: "tilt-center", title: "Tilt · Center Power", angle: "tilt_angles", power: "center", compass: false },
        { id: "el-peak", title: "Elevation · Peak Power", angle: "elevation_angles", power: "peak", compass: false },
        { id: "el-center", title: "Elevation · Center Power", angle: "elevation_angles", power: "center", compass: false },
    ],
};

function cssColor(name, fallback) {
    return window.getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
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
    if (persist) {
        try {
            window.localStorage.setItem("grid-designer-color-mode", mode);
        } catch {
            // Ignore unavailable storage.
        }
    }
    polarRenderedKey = null;
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

function renderPath(frame) {
    const plot = document.querySelector(`[data-path-plot="${frame}"]`);
    if (!plot || !pathPlan || !window.Plotly) return;
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
    window.Plotly.react(plot, traces, {
        margin: { t: 15, r: 25, b: 65, l: 65 },
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: cssColor("--plot-background", "#d1e0ff"),
        font: { color: cssColor("--text", "#000") },
        legend: { orientation: "h", x: 0.5, xanchor: "center", y: -0.18 },
        uirevision: `path-${frame}-${pathPlan.version}`,
        xaxis: degreeAxis(frame === "pan-tilt" ? "Pan" : "Azimuth"),
        yaxis: degreeAxis(frame === "pan-tilt" ? "Tilt" : "Elevation", "x"),
    }, { responsive: true, displaylogo: false });
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

function renderPolarGroup(direction) {
    const container = document.querySelector(`[data-polar-group="${direction}"]`);
    if (!container || !window.Plotly) return;
    container.querySelectorAll(".polar-plot").forEach((plot) => window.Plotly.purge(plot));
    container.replaceChildren();
    const cuts = (resultsPayload?.cuts || []).filter((cut) => cut.direction === direction);
    const pendingPlots = POLAR_DEFINITIONS[direction].map((definition) => {
        const card = document.createElement("article");
        card.className = "polar-plot-card";
        const header = document.createElement("header");
        const heading = document.createElement("h3");
        heading.textContent = definition.title;
        header.append(heading);
        const plot = document.createElement("div");
        plot.className = "polar-plot";
        card.append(header, plot);
        container.append(card);
        return { definition, plot };
    });

    // Plotly measures a plot's parent when it renders. Build the entire grid
    // first, then wait for the browser to resolve the final column widths.
    window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
            pendingPlots.forEach(({ definition, plot }) => {
                if (!plot.isConnected) return;
                const allValues = cuts.flatMap((cut) =>
                    cut[definition.power].normalized_db.filter(Number.isFinite),
                );
                const floor = Math.max(
                    -60,
                    Math.min(
                        -5,
                        Math.floor((allValues.length ? Math.min(...allValues) : -5) / 5) * 5,
                    ),
                );
                const traces = cuts.map((cut) => ({
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
                const radialTickvals = [];
                const radialTicktext = [];
                for (let value = floor; value <= 0; value += 5) {
                    radialTickvals.push(value - floor);
                    radialTicktext.push(`${value}`);
                }
                const ticks = polarTicks();
                window.Plotly.react(plot, traces, {
                    autosize: false,
                    width: plot.clientWidth,
                    height: Math.max(430, plot.clientHeight),
                    margin: { t: 25, r: 30, b: 55, l: 30 },
                    paper_bgcolor: "rgba(0,0,0,0)",
                    font: { color: cssColor("--text", "#000") },
                    legend: { orientation: "h", x: 0.5, xanchor: "center", y: -0.08 },
                    uirevision: `${definition.id}-${resultsPayload?.version || "empty"}`,
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
                }, { responsive: true, displaylogo: false });
            });
        });
    });
}

function renderAll() {
    const loaded = Boolean(latestStatus?.loaded);
    document.querySelectorAll("[data-path-panel]").forEach((panel) => { panel.hidden = !loaded; });
    document.querySelectorAll("[data-results-panel]").forEach((panel) => { panel.hidden = !resultsPayload; });
    if (loaded && pathPlan) {
        renderPath("pan-tilt");
        renderPath("az-el");
    }
    const nextPolarRenderedKey = resultsPayload
        ? `${resultsKey}:${document.documentElement.dataset.colorMode}`
        : null;
    if (resultsPayload && nextPolarRenderedKey !== polarRenderedKey) {
        renderPolarGroup("horizontal");
        renderPolarGroup("vertical");
        polarRenderedKey = nextPolarRenderedKey;
    }
    const actual = latestTurntable?.state?.corrected_position;
    document.querySelector("[data-path-position]").textContent =
        actual ? `Actual pan ${angle(actual.pan)} · tilt ${angle(actual.tilt)}` : "Actual position unavailable";
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
        }
        const nextResultsKey = latestStatus.results?.available
            ? `${latestStatus.results.path}:${latestStatus.results.version}`
            : null;
        if (nextResultsKey !== resultsKey) {
            resultsPayload = nextResultsKey ? await requestJson("/experiment/results") : null;
            resultsKey = nextResultsKey;
            polarRenderedKey = null;
            visitedPointKeys = new Set((resultsPayload?.visited_points || []).map((point) => pointKey(point.cut_id, point.point_index)));
            document.querySelector("[data-results-path]").textContent = resultsPayload?.source_path || "—";
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
    setColorMode(document.documentElement.dataset.colorMode, false);
    refresh();
    const timer = window.setInterval(refresh, 1000);
    window.addEventListener("pagehide", () => window.clearInterval(timer));
});
