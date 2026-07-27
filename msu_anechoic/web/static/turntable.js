"use strict";

let lastStatusPayload = null;
let refreshTimer = null;
let statusRequestInFlight = false;

function setMenuOpen(isOpen) {
    const toggle = document.getElementById("menu-toggle");
    const menu = document.getElementById("application-menu");
    if (!toggle || !menu) return;
    toggle.setAttribute("aria-expanded", String(isOpen));
    toggle.setAttribute("aria-label", isOpen ? "Close navigation menu" : "Open navigation menu");
    menu.hidden = !isOpen;
}

function storeColorMode(mode) {
    try {
        window.localStorage.setItem("grid-designer-color-mode", mode);
    } catch {
        // The control remains useful without local storage.
    }
}

function setColorMode(mode, { persist = true } = {}) {
    if (mode !== "light" && mode !== "dark") return;
    document.documentElement.dataset.colorMode = mode;
    const input = document.querySelector(`input[name="color_mode"][value="${mode}"]`);
    if (input) input.checked = true;
    if (persist) storeColorMode(mode);
    if (lastStatusPayload) renderPlots(lastStatusPayload);
}

function cssColor(name, fallback) {
    return window.getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function historyOptions() {
    const maxTime = Number.parseFloat(document.getElementById("history-max-time")?.value || "3600");
    const maxPoints = Number.parseInt(document.getElementById("history-max-points")?.value || "1000", 10);
    const refreshInterval = Number.parseFloat(document.getElementById("refresh-interval")?.value || "1");
    return {
        maxTime: Number.isFinite(maxTime) && maxTime > 0 ? Math.min(maxTime, 86400) : 3600,
        maxPoints: Number.isFinite(maxPoints) && maxPoints > 0 ? Math.min(maxPoints, 50000) : 1000,
        refreshInterval:
            Number.isFinite(refreshInterval) && refreshInterval >= 0.1
                ? Math.min(refreshInterval, 60)
                : 1,
    };
}

function scheduleRefresh() {
    window.clearTimeout(refreshTimer);
    refreshTimer = window.setTimeout(refreshStatus, historyOptions().refreshInterval * 1000);
}

async function refreshStatus() {
    if (statusRequestInFlight) {
        scheduleRefresh();
        return;
    }
    statusRequestInFlight = true;
    const options = historyOptions();
    const query = new URLSearchParams({
        max_time: String(options.maxTime),
        max_points: String(options.maxPoints),
    });
    try {
        const response = await window.fetch(`/turntable/status?${query}`, {
            headers: { Accept: "application/json" },
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || "Unable to load controller status.");
        lastStatusPayload = payload;
        renderStatus(payload);
    } catch (error) {
        renderConnectionFailure(error.message);
    } finally {
        statusRequestInFlight = false;
        scheduleRefresh();
    }
}

function humanize(value) {
    if (!value) return "—";
    return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function angle(value) {
    return Number.isFinite(value) ? `${value.toFixed(2)}°` : "—";
}

function seconds(value) {
    return Number.isFinite(value) ? `${value.toFixed(2)} sec` : "—";
}

function pair(position, first, second) {
    if (!position) return "—";
    return `${angle(position[first])} / ${angle(position[second])}`;
}

function localTimestamp(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? "—" : date.toLocaleString();
}

function setStatusValue(name, value) {
    const element = document.querySelector(`[data-status="${name}"]`);
    if (element) element.textContent = value;
}

function renderStatus(payload) {
    const state = payload.state;
    const connectionSummary = document.querySelector(".connection-summary");
    connectionSummary?.classList.toggle("is-connected", payload.connected);
    connectionSummary?.classList.toggle("is-error", !payload.connected);
    document.querySelector("[data-connection-label]").textContent = payload.connected ? "Controller connected" : "Disconnected";

    const badge = document.querySelector("[data-state-badge]");
    badge.textContent = humanize(state.state).toUpperCase();
    badge.dataset.state = state.state;

    const activity = state.activity_phase
        ? `${humanize(state.activity)} · ${humanize(state.activity_phase)}`
        : humanize(state.activity);
    setStatusValue("activity", activity);
    setStatusValue("pan-tilt", pair(state.corrected_position, "pan", "tilt"));
    setStatusValue("yaw-pitch", pair(state.uncorrected_position, "yaw", "pitch"));
    setStatusValue(
        "regime",
        state.current_regime
            ? `${angle(state.current_regime.center_tilt)} center (${angle(state.current_regime.minimum_tilt)} to ${angle(state.current_regime.maximum_tilt)})`
            : "Not established",
    );
    setStatusValue("offset", pair(state.regime_offset, "pan", "tilt"));
    setStatusValue("target", pair(state.target_position, "pan", "tilt"));
    setStatusValue("internal-target", pair(state.internal_target, "yaw", "pitch"));
    setStatusValue("last-position", localTimestamp(state.most_recent_position_event?.timestamp));
    setStatusValue("last-communication", localTimestamp(state.last_communication_at));
    setStatusValue("communication-age", seconds(state.seconds_since_last_communication));
    setStatusValue("communication-timeout", seconds(state.communication_timeout));
    setStatusValue("timeout", localTimestamp(state.activity_timeout_at));
    setStatusValue("queued", String(state.queued_command_count));
    setStatusValue(
        "set-status",
        state.has_been_set ? "Acknowledged" : state.set_requested ? "Requested" : "Not set",
    );
    setStatusValue(
        "event-count",
        `${Number(state.event_count || 0).toLocaleString()} total · ${Number(state.position_history_count || 0).toLocaleString()} positions`,
    );
    setStatusValue("error", state.last_error || payload.connection_error || "None");
    document.querySelector('[data-status="error"]')?.classList.toggle(
        "is-error",
        Boolean(state.last_error || payload.connection_error),
    );

    document.querySelectorAll("[data-history-count]").forEach((element) => {
        element.textContent = `${payload.history.length.toLocaleString()} ${payload.history.length === 1 ? "point" : "points"}`;
    });
    applyControlState(payload.controls);
    renderPlots(payload);
}

function renderConnectionFailure(message) {
    const payload = {
        connected: false,
        connection_error: message,
        state: {
            state: "disconnected",
            activity: "idle",
            activity_phase: null,
            corrected_position: null,
            uncorrected_position: null,
            current_regime: null,
            regime_offset: null,
            target_position: null,
            internal_target: null,
            most_recent_position_event: null,
            last_communication_at: null,
            seconds_since_last_communication: null,
            communication_timeout: null,
            activity_timeout_at: null,
            queued_command_count: 0,
            has_been_set: false,
            set_requested: false,
            event_count: 0,
            position_history_count: 0,
            last_error: null,
        },
        controls: { set_enabled: false, move_enabled: false, abort_enabled: false },
        history: [],
    };
    lastStatusPayload = payload;
    renderStatus(payload);
}

function applyControlState(controls) {
    document.querySelector('[data-control="set"]').disabled = !controls.set_enabled;
    document.querySelector('[data-control="move"]').disabled = !controls.move_enabled;
    document.querySelector('[data-control="abort"]').disabled = !controls.abort_enabled;
}

function basePlotLayout(titleX, titleY) {
    const paper = cssColor("--plot-paper", "#e6eeff");
    const background = cssColor("--plot-background", "#d1e0ff");
    const text = cssColor("--plot-text", "#000000");
    const grid = cssColor("--plot-grid", "#8fa6d2");
    const zero = cssColor("--plot-zero", "#5f79ad");
    const axis = (title) => ({
        title: { text: title, font: { size: 14 } },
        gridcolor: grid,
        zerolinecolor: zero,
        zerolinewidth: 2,
        tickfont: { size: 12 },
        automargin: true,
    });
    return {
        margin: { l: 58, r: 20, t: 22, b: 54 },
        paper_bgcolor: paper,
        plot_bgcolor: background,
        font: { color: text, family: '"Segoe UI", Arial, sans-serif', size: 13 },
        xaxis: axis(titleX),
        yaxis: { ...axis(titleY), scaleanchor: "x", scaleratio: 1 },
        hovermode: "closest",
        showlegend: true,
        legend: { orientation: "h", x: 0, y: 1.08, font: { size: 12 } },
        uirevision: "turntable-position-history",
    };
}

function positionTraces(payload, coordinateSystem) {
    const history = payload.history;
    const isCorrected = coordinateSystem === "pan_tilt";
    const xKey = isCorrected ? "pan" : "yaw";
    const yKey = isCorrected ? "tilt" : "pitch";
    const current = history.at(-1);
    const state = payload.state;
    const target = isCorrected ? state.target_position : state.internal_target;
    const moving = state.state === "moving";
    const lineColor = cssColor("--plot-line", "#4368aa");
    const currentColor = cssColor("--status-green", "#17823b");
    const targetColor = cssColor("--target-red", "#c62828");
    const paper = cssColor("--plot-paper", "#e6eeff");
    const traces = [
        {
            name: "History",
            type: "scatter",
            mode: "lines+markers",
            x: history.map((point) => point[xKey]),
            y: history.map((point) => point[yKey]),
            text: history.map((point) => localTimestamp(point.timestamp)),
            line: { color: lineColor, width: 2 },
            marker: { color: lineColor, size: 5, opacity: 0.7 },
            hovertemplate: `%{text}<br>${humanize(xKey)}: %{x:.3f}°<br>${humanize(yKey)}: %{y:.3f}°<extra></extra>`,
        },
    ];
    if (current) {
        traces.push({
            name: "Current",
            type: "scatter",
            mode: "markers",
            x: [current[xKey]],
            y: [current[yKey]],
            text: [localTimestamp(current.timestamp)],
            marker: {
                color: currentColor,
                size: 13,
                symbol: "circle",
                line: { color: paper, width: 2 },
            },
            hovertemplate: `%{text}<br>${humanize(xKey)}: %{x:.3f}°<br>${humanize(yKey)}: %{y:.3f}°<extra></extra>`,
        });
    }
    if (moving && target) {
        traces.push({
            name: "Target",
            type: "scatter",
            mode: "markers",
            x: [target[xKey]],
            y: [target[yKey]],
            marker: {
                color: targetColor,
                size: 15,
                symbol: "x",
                line: { color: targetColor, width: 3 },
            },
            hovertemplate: `${humanize(xKey)}: %{x:.3f}°<br>${humanize(yKey)}: %{y:.3f}°<extra>Target</extra>`,
        });
    }
    return traces;
}

function renderPlots(payload) {
    if (!window.Plotly) {
        window.setTimeout(() => renderPlots(payload), 40);
        return;
    }
    const config = {
        responsive: true,
        displaylogo: false,
        modeBarButtonsToRemove: ["lasso2d", "select2d"],
    };
    window.Plotly.react(
        "pan-tilt-plot",
        positionTraces(payload, "pan_tilt"),
        basePlotLayout("Pan (°)", "Tilt (°)"),
        config,
    );
    window.Plotly.react(
        "yaw-pitch-plot",
        positionTraces(payload, "yaw_pitch"),
        basePlotLayout("Yaw (°)", "Pitch (°)"),
        config,
    );
}

function commandValues(form) {
    const pan = Number.parseFloat(form.elements.pan.value.trim());
    const tilt = Number.parseFloat(form.elements.tilt.value.trim());
    if (!Number.isFinite(pan) || !Number.isFinite(tilt)) {
        throw new Error("Enter finite numeric values for both pan and tilt.");
    }
    return { pan, tilt };
}

function setFeedback(message, kind = "") {
    const feedback = document.querySelector("[data-command-feedback]");
    feedback.textContent = message;
    feedback.classList.toggle("is-error", kind === "error");
    feedback.classList.toggle("is-success", kind === "success");
}

async function sendCommand(path, body = null) {
    const options = {
        method: "POST",
        headers: { Accept: "application/json" },
    };
    if (body) {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
    }
    const response = await window.fetch(path, options);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "The controller rejected the command.");
    setFeedback(payload.message, "success");
    await refreshStatus();
}

async function submitCommandForm(form) {
    const command = form.dataset.commandForm;
    const button = form.querySelector("button[type=submit]");
    try {
        button.disabled = true;
        setFeedback(`Sending ${command.toUpperCase()} command…`);
        await sendCommand(`/turntable/${command}`, commandValues(form));
    } catch (error) {
        setFeedback(error.message, "error");
        if (lastStatusPayload) applyControlState(lastStatusPayload.controls);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    setColorMode(document.documentElement.dataset.colorMode || "light", { persist: false });

    document.getElementById("menu-toggle")?.addEventListener("click", (event) => {
        event.stopPropagation();
        const isOpen = event.currentTarget.getAttribute("aria-expanded") === "true";
        setMenuOpen(!isOpen);
    });
    document.getElementById("application-menu")?.addEventListener("click", (event) => event.stopPropagation());
    document.querySelectorAll('input[name="color_mode"]').forEach((control) => {
        control.addEventListener("change", (event) => {
            if (event.currentTarget.checked) setColorMode(event.currentTarget.value);
        });
    });
    document.querySelectorAll("[data-command-form]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            submitCommandForm(form);
        });
    });
    document.querySelector('[data-control="abort"]')?.addEventListener("click", async () => {
        try {
            setFeedback("Sending emergency stop…");
            await sendCommand("/turntable/abort");
        } catch (error) {
            setFeedback(error.message, "error");
        }
    });
    document.querySelectorAll("#history-max-time, #history-max-points, #refresh-interval").forEach((input) => {
        input.addEventListener("change", refreshStatus);
    });
    refreshStatus();
});

document.addEventListener("click", () => setMenuOpen(false));
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
        setMenuOpen(false);
        document.getElementById("menu-toggle")?.focus();
    }
});
