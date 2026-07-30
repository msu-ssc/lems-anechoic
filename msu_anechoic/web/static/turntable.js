"use strict";

const MAX_SERVER_HISTORY_POINTS = 50000;
const DEFAULT_HISTORY_OPTIONS = {
    recentTime: 60,
    recentRate: 10,
    historyTime: 7200,
    historyRate: 0.5,
    refreshInterval: 1,
};
const MOVE_TIMEOUT_SAFETY_FACTOR = 1.5;
const MOVE_TIMEOUT_MINIMUM = 5;
const CAMERA_ROTATION_PERIOD_MS = 60000;
const CAMERA_UPDATE_INTERVAL_MS = 50;
const rotatingPlots = new WeakMap();
const cameraRotationSettings = {
    paused: true,
    speed: 1,
};

let lastStatusPayload = null;
let refreshTimer = null;
let statusRequestInFlight = false;
let historyCursor = null;
let largestReceivedTimestamp = null;
let historyGeneration = 0;
let serverHistoryGeneration = null;
let plotRevision = 0;
let lastCommandLogSignature = null;
const sampledHistory = {
    recent: [],
    history: [],
};

const COORDINATE_SYSTEMS = {
    pan_tilt: {
        xKey: "pan",
        yKey: "tilt",
        xLabel: "Pan",
        yLabel: "Tilt",
        currentKey: "corrected_position",
        targetKey: "target_position",
    },
    yaw_pitch: {
        xKey: "yaw",
        yKey: "pitch",
        xLabel: "Yaw",
        yLabel: "Pitch",
        currentKey: "uncorrected_position",
        targetKey: "internal_target",
    },
    az_el: {
        xKey: "azimuth",
        yKey: "elevation",
        xLabel: "Azimuth",
        yLabel: "Elevation",
        currentKey: "az_el_position",
        targetKey: "az_el_target",
    },
};

function formatRotationSpeed(speed) {
    return `${speed.toFixed(2).replace(/\.?0+$/, "")}×`;
}

function syncRotationControls() {
    document.querySelectorAll("[data-rotation-toggle]").forEach((button) => {
        button.textContent = cameraRotationSettings.paused ? "Play" : "Pause";
        button.setAttribute(
            "aria-label",
            cameraRotationSettings.paused
                ? "Play 3D view rotation"
                : "Pause 3D view rotation",
        );
    });
    document.querySelectorAll("[data-rotation-speed]").forEach((slider) => {
        slider.value = String(cameraRotationSettings.speed);
    });
    document.querySelectorAll("[data-rotation-speed-output]").forEach((output) => {
        output.value = formatRotationSpeed(cameraRotationSettings.speed);
        output.textContent = output.value;
    });
}

function cameraEyeFromRelayout(eventData) {
    if (eventData["scene.camera"]?.eye) return eventData["scene.camera"].eye;
    if (eventData["scene.camera.eye"]) return eventData["scene.camera.eye"];
    const x = eventData["scene.camera.eye.x"];
    const y = eventData["scene.camera.eye.y"];
    const z = eventData["scene.camera.eye.z"];
    return [x, y, z].every(Number.isFinite) ? { x, y, z } : null;
}

function updateRotationFromEye(state, eye) {
    if (![eye?.x, eye?.y, eye?.z].every(Number.isFinite)) return;
    state.radius = Math.hypot(eye.x, eye.y);
    state.angle = Math.atan2(eye.y, eye.x);
    state.z = eye.z;
}

function startCameraRotation(plotElement, initialEye) {
    if (!plotElement || rotatingPlots.has(plotElement)) return;
    const state = {
        angle: 0,
        radius: 1,
        z: 1,
        visible: true,
        updating: false,
        lastFrame: performance.now(),
        lastUpdate: 0,
        observer: null,
    };
    updateRotationFromEye(state, initialEye);
    rotatingPlots.set(plotElement, state);

    if (window.IntersectionObserver) {
        state.observer = new IntersectionObserver((entries) => {
            state.visible = entries.some((entry) => entry.isIntersecting);
            state.lastFrame = performance.now();
        });
        state.observer.observe(plotElement);
    }
    if (typeof plotElement.on === "function") {
        plotElement.on("plotly_relayout", (eventData) => {
            if (state.updating) return;
            const eye = cameraEyeFromRelayout(eventData);
            if (eye) {
                updateRotationFromEye(state, eye);
                state.lastFrame = performance.now();
            }
        });
    }

    function animate(now) {
        if (!plotElement.isConnected) {
            state.observer?.disconnect();
            return;
        }
        window.requestAnimationFrame(animate);
        const elapsed = now - state.lastFrame;
        state.lastFrame = now;
        if (
            cameraRotationSettings.paused
            || !state.visible
            || document.hidden
            || state.updating
        ) return;

        state.angle = (
            state.angle
            + elapsed * cameraRotationSettings.speed * Math.PI * 2 / CAMERA_ROTATION_PERIOD_MS
        ) % (Math.PI * 2);
        if (now - state.lastUpdate < CAMERA_UPDATE_INTERVAL_MS) return;

        state.lastUpdate = now;
        state.updating = true;
        Promise.resolve(
            window.Plotly.relayout(plotElement, {
                "scene.camera.eye": {
                    x: state.radius * Math.cos(state.angle),
                    y: state.radius * Math.sin(state.angle),
                    z: state.z,
                },
            }),
        ).finally(() => {
            state.updating = false;
        });
    }
    window.requestAnimationFrame(animate);
}

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

function positiveNumber(id, fallback, maximum) {
    const value = Number.parseFloat(document.getElementById(id)?.value || "");
    return Number.isFinite(value) && value > 0 ? Math.min(value, maximum) : fallback;
}

function samplingInterval(rate, fallback, input) {
    const validInteger = rate >= 1 && Math.abs(rate - Math.round(rate)) < 1e-7;
    const reciprocal = 1 / rate;
    const validReciprocal = rate < 1 && Math.abs(reciprocal - Math.round(reciprocal)) < 1e-7;
    const isValid = Number.isFinite(rate) && rate > 0 && (validInteger || validReciprocal);
    input?.setCustomValidity(isValid ? "" : "Use a whole-number rate or the reciprocal of a whole number.");
    return 1 / (isValid ? rate : fallback);
}

function historyOptions() {
    const recentRateInput = document.getElementById("recent-history-rate");
    const historyRateInput = document.getElementById("history-rate");
    const recentRate = Number.parseFloat(recentRateInput?.value || "");
    const historyRate = Number.parseFloat(historyRateInput?.value || "");
    return {
        recentTime: positiveNumber("recent-history-time", DEFAULT_HISTORY_OPTIONS.recentTime, 3600),
        recentRate: Number.isFinite(recentRate) ? recentRate : DEFAULT_HISTORY_OPTIONS.recentRate,
        recentInterval: samplingInterval(
            recentRate,
            DEFAULT_HISTORY_OPTIONS.recentRate,
            recentRateInput,
        ),
        historyTime: positiveNumber("history-max-time", DEFAULT_HISTORY_OPTIONS.historyTime, 86400),
        historyRate: Number.isFinite(historyRate) ? historyRate : DEFAULT_HISTORY_OPTIONS.historyRate,
        historyInterval: samplingInterval(
            historyRate,
            DEFAULT_HISTORY_OPTIONS.historyRate,
            historyRateInput,
        ),
        refreshInterval: positiveNumber("refresh-interval", DEFAULT_HISTORY_OPTIONS.refreshInterval, 60),
    };
}

function scheduleRefresh() {
    window.clearTimeout(refreshTimer);
    refreshTimer = window.setTimeout(refreshStatus, historyOptions().refreshInterval * 1000);
}

function sampleTimestamp(sample) {
    return new Date(sample.timestamp).valueOf();
}

function appendRateLimited(bucket, sample, intervalSeconds) {
    const timestamp = sampleTimestamp(sample);
    if (!Number.isFinite(timestamp)) return;
    const previousTimestamp = bucket.length ? sampleTimestamp(bucket.at(-1)) : Number.NEGATIVE_INFINITY;
    if (timestamp <= previousTimestamp) return;
    if (timestamp - previousTimestamp + 0.001 >= intervalSeconds * 1000) {
        bucket.push(sample);
    }
}

function pruneHistory() {
    if (!Number.isFinite(largestReceivedTimestamp)) return;
    const options = historyOptions();
    const recentCutoff = largestReceivedTimestamp - options.recentTime * 1000;
    const historyCutoff = largestReceivedTimestamp - options.historyTime * 1000;
    sampledHistory.recent = sampledHistory.recent.filter((sample) => sampleTimestamp(sample) >= recentCutoff);
    sampledHistory.history = sampledHistory.history.filter((sample) => sampleTimestamp(sample) >= historyCutoff);
}

function ingestHistory(samples) {
    const options = historyOptions();
    const ordered = [...samples].sort((first, second) => sampleTimestamp(first) - sampleTimestamp(second));
    ordered.forEach((sample) => {
        const timestamp = sampleTimestamp(sample);
        if (!Number.isFinite(timestamp)) return;
        largestReceivedTimestamp = Math.max(largestReceivedTimestamp ?? timestamp, timestamp);
        appendRateLimited(sampledHistory.recent, sample, options.recentInterval);
        appendRateLimited(sampledHistory.history, sample, options.historyInterval);
        if (!historyCursor || timestamp > new Date(historyCursor).valueOf()) {
            historyCursor = sample.timestamp;
        }
    });
    pruneHistory();
}

function combinedHistory() {
    const byTimestamp = new Map();
    sampledHistory.history.forEach((sample) => byTimestamp.set(sample.timestamp, sample));
    sampledHistory.recent.forEach((sample) => byTimestamp.set(sample.timestamp, sample));
    return [...byTimestamp.values()].sort((first, second) => sampleTimestamp(first) - sampleTimestamp(second));
}

function resetPositionHistory({ preserveCursor = true } = {}) {
    sampledHistory.recent = [];
    sampledHistory.history = [];
    largestReceivedTimestamp = preserveCursor && historyCursor ? new Date(historyCursor).valueOf() : null;
    if (!preserveCursor) historyCursor = null;
    historyGeneration += 1;
    plotRevision += 1;
    if (lastStatusPayload) {
        lastStatusPayload = { ...lastStatusPayload, history: [] };
        renderStatus(lastStatusPayload);
    }
}

async function refreshStatus() {
    if (statusRequestInFlight) {
        scheduleRefresh();
        return;
    }
    statusRequestInFlight = true;
    const options = historyOptions();
    const requestGeneration = historyGeneration;
    const query = new URLSearchParams({
        max_time: String(options.historyTime),
        max_points: String(MAX_SERVER_HISTORY_POINTS),
    });
    if (historyCursor) query.set("after", historyCursor);
    try {
        const response = await window.fetch(`/turntable/status?${query}`, {
            headers: { Accept: "application/json" },
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || "Unable to load controller status.");
        const receivedGeneration = payload.state.position_history_generation;
        let serverResetDetected = false;
        if (payload.connected && Number.isInteger(receivedGeneration)) {
            if (serverHistoryGeneration !== null && receivedGeneration !== serverHistoryGeneration) {
                resetPositionHistory({ preserveCursor: true });
                serverResetDetected = true;
            }
            serverHistoryGeneration = receivedGeneration;
        }
        if (requestGeneration === historyGeneration || serverResetDetected) ingestHistory(payload.history || []);
        lastStatusPayload = { ...payload, history: combinedHistory() };
        renderStatus(lastStatusPayload);
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

function renderCommandLog(commands) {
    const commandLog = document.querySelector("[data-command-log]");
    if (!commandLog) return;
    const commandCount = document.querySelector("[data-command-count]");
    if (commandCount) {
        commandCount.textContent = `${commands.length.toLocaleString()} ${commands.length === 1 ? "write" : "writes"}`;
    }

    const signature = commands.map((command) => `${command.timestamp}:${command.hex}`).join("|");
    if (signature === lastCommandLogSignature) return;
    lastCommandLogSignature = signature;
    const wasAtBottom = (
        commandLog.scrollHeight - commandLog.scrollTop - commandLog.clientHeight < 12
    );
    commandLog.replaceChildren();
    if (!commands.length) {
        const empty = document.createElement("li");
        empty.className = "command-log-empty";
        empty.textContent = "No commands have been sent during this connection.";
        commandLog.append(empty);
        return;
    }

    commands.forEach((command) => {
        const item = document.createElement("li");
        const timestamp = document.createElement("time");
        timestamp.dateTime = command.timestamp;
        timestamp.textContent = command.timestamp;
        const bytes = document.createElement("code");
        bytes.textContent = command.bytes;
        const hex = document.createElement("small");
        hex.textContent = `${command.byte_count} bytes · ${command.hex}`;
        item.append(timestamp, bytes, hex);
        commandLog.append(item);
    });
    if (wasAtBottom) commandLog.scrollTop = commandLog.scrollHeight;
}

function setStatusValue(name, value) {
    document.querySelectorAll(`[data-status="${name}"]`).forEach((element) => {
        element.textContent = value;
    });
}

function renderStatus(payload) {
    const state = payload.state;
    const connectionSummary = document.querySelector(".connection-summary");
    connectionSummary?.classList.toggle("is-connected", payload.connected);
    connectionSummary?.classList.toggle("is-error", !payload.connected);
    const connectionLabel = document.querySelector("[data-connection-label]");
    if (connectionLabel) connectionLabel.textContent = payload.connected ? "Controller connected" : "Disconnected";

    const badge = document.querySelector("[data-state-badge]");
    if (badge) {
        badge.textContent = humanize(state.state).toUpperCase();
        badge.dataset.state = state.state;
    }
    const floatingState = document.querySelector("[data-floating-state]");
    if (floatingState) {
        floatingState.textContent = humanize(state.state).toUpperCase();
        floatingState.dataset.state = state.state;
    }

    const activity = state.activity_phase
        ? `${humanize(state.activity)} · ${humanize(state.activity_phase)}`
        : humanize(state.activity);
    setStatusValue("activity", activity);
    setStatusValue("pan-tilt", pair(state.corrected_position, "pan", "tilt"));
    setStatusValue("yaw-pitch", pair(state.uncorrected_position, "yaw", "pitch"));
    setStatusValue("confirm-position", pair(state.uncorrected_position, "yaw", "pitch"));
    setStatusValue("az-el", pair(state.az_el_position, "azimuth", "elevation"));
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

    const floatingPosition = document.querySelector("[data-floating-position]");
    if (floatingPosition) floatingPosition.textContent = pair(state.corrected_position, "pan", "tilt");
    const floatingAzEl = document.querySelector("[data-floating-az-el]");
    if (floatingAzEl) floatingAzEl.textContent = `Az / el: ${pair(state.az_el_position, "azimuth", "elevation")}`;

    document.querySelectorAll("[data-history-count]").forEach((element) => {
        element.textContent = `${payload.history.length.toLocaleString()} ${payload.history.length === 1 ? "point" : "points"}`;
    });
    renderCommandLog(payload.commands || []);
    applyControlState(payload.controls);
    updateMoveEstimate();
    renderPlots(payload);
}

function disconnectedState() {
    return {
        state: "disconnected",
        activity: "idle",
        activity_phase: null,
        corrected_position: null,
        uncorrected_position: null,
        az_el_position: null,
        current_regime: null,
        regime_offset: null,
        target_position: null,
        internal_target: null,
        az_el_target: null,
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
        position_history_generation: 0,
        last_error: null,
    };
}

function renderConnectionFailure(message) {
    const payload = {
        connected: false,
        connection_error: message,
        state: disconnectedState(),
        controls: {
            set_enabled: false,
            move_enabled: false,
            confirm_enabled: false,
            abort_enabled: false,
        },
        history: combinedHistory(),
        commands: lastStatusPayload?.commands || [],
    };
    lastStatusPayload = payload;
    renderStatus(payload);
}

function applyControlState(controls) {
    document.querySelectorAll('[data-control="set"]').forEach((button) => {
        button.disabled = !controls.set_enabled;
    });
    document.querySelectorAll('[data-control="move"]').forEach((button) => {
        button.disabled = !controls.move_enabled;
    });
    document.querySelectorAll('[data-control="confirm"]').forEach((button) => {
        button.disabled = !controls.confirm_enabled;
    });
    document.querySelectorAll('[data-control="abort"]').forEach((button) => {
        button.disabled = !controls.abort_enabled;
    });
    document.querySelectorAll("[data-jog-pan]").forEach((button) => {
        button.disabled = !controls.move_enabled;
    });
}

function plotAxis(title) {
    return {
        title: { text: title, font: { size: 14 } },
        gridcolor: cssColor("--plot-grid", "#8fa6d2"),
        zerolinecolor: cssColor("--plot-zero", "#5f79ad"),
        zerolinewidth: 2,
        tickfont: { size: 12 },
        automargin: true,
    };
}

function basePlotLayout(titleX, titleY) {
    return {
        margin: { l: 58, r: 20, t: 22, b: 54 },
        paper_bgcolor: cssColor("--plot-paper", "#e6eeff"),
        plot_bgcolor: cssColor("--plot-background", "#d1e0ff"),
        font: {
            color: cssColor("--plot-text", "#000000"),
            family: '"Segoe UI", Arial, sans-serif',
            size: 13,
        },
        xaxis: plotAxis(titleX),
        yaxis: { ...plotAxis(titleY), scaleanchor: "x", scaleratio: 1 },
        hovermode: "closest",
        showlegend: true,
        legend: { orientation: "h", x: 0, y: 1.08, font: { size: 12 } },
        uirevision: `turntable-position-${plotRevision}`,
    };
}

function positionTraces(payload, coordinateSystem) {
    const history = payload.history;
    const definition = COORDINATE_SYSTEMS[coordinateSystem];
    const { xKey, yKey, xLabel, yLabel } = definition;
    const state = payload.state;
    const current = state[definition.currentKey];
    const target = state[definition.targetKey];
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
            hovertemplate: `%{text}<br>${xLabel}: %{x:.3f}°<br>${yLabel}: %{y:.3f}°<extra></extra>`,
        },
    ];
    if (current) {
        traces.push({
            name: "Current",
            type: "scatter",
            mode: "markers",
            x: [current[xKey]],
            y: [current[yKey]],
            text: [localTimestamp(state.most_recent_position_event?.timestamp)],
            marker: {
                color: currentColor,
                size: 13,
                symbol: "circle",
                line: { color: paper, width: 2 },
            },
            hovertemplate: `%{text}<br>${xLabel}: %{x:.3f}°<br>${yLabel}: %{y:.3f}°<extra></extra>`,
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
            hovertemplate: `${xLabel}: %{x:.3f}°<br>${yLabel}: %{y:.3f}°<extra>Target</extra>`,
        });
    }
    return traces;
}

function azElUnitVector(azimuth, elevation, radius = 1) {
    const azimuthRadians = azimuth * Math.PI / 180;
    const elevationRadians = elevation * Math.PI / 180;
    const horizontalRadius = Math.cos(elevationRadians);
    return {
        x: radius * horizontalRadius * Math.cos(azimuthRadians),
        y: -radius * horizontalRadius * Math.sin(azimuthRadians),
        z: radius * Math.sin(elevationRadians),
    };
}

function indexedMesh(vertices, faces) {
    return {
        x: vertices.map((vertex) => vertex.x),
        y: vertices.map((vertex) => vertex.y),
        z: vertices.map((vertex) => vertex.z),
        i: faces.map((face) => face[0]),
        j: faces.map((face) => face[1]),
        k: faces.map((face) => face[2]),
    };
}

function sphereMesh(center, radius, latitudeSegments = 12, longitudeSegments = 24) {
    const vertices = [{ x: center.x, y: center.y, z: center.z - radius }];
    for (let latitudeIndex = 1; latitudeIndex < latitudeSegments; latitudeIndex += 1) {
        const latitude = -Math.PI / 2 + Math.PI * latitudeIndex / latitudeSegments;
        const ringRadius = radius * Math.cos(latitude);
        const z = center.z + radius * Math.sin(latitude);
        for (let longitudeIndex = 0; longitudeIndex < longitudeSegments; longitudeIndex += 1) {
            const longitude = 2 * Math.PI * longitudeIndex / longitudeSegments;
            vertices.push({
                x: center.x + ringRadius * Math.cos(longitude),
                y: center.y + ringRadius * Math.sin(longitude),
                z,
            });
        }
    }
    const northPoleIndex = vertices.length;
    vertices.push({ x: center.x, y: center.y, z: center.z + radius });

    const faces = [];
    for (let longitudeIndex = 0; longitudeIndex < longitudeSegments; longitudeIndex += 1) {
        const current = 1 + longitudeIndex;
        const following = 1 + (longitudeIndex + 1) % longitudeSegments;
        faces.push([0, following, current]);
    }
    const ringCount = latitudeSegments - 1;
    for (let ringIndex = 0; ringIndex < ringCount - 1; ringIndex += 1) {
        const lowerStart = 1 + ringIndex * longitudeSegments;
        const upperStart = lowerStart + longitudeSegments;
        for (let longitudeIndex = 0; longitudeIndex < longitudeSegments; longitudeIndex += 1) {
            const following = (longitudeIndex + 1) % longitudeSegments;
            const lowerCurrent = lowerStart + longitudeIndex;
            const lowerFollowing = lowerStart + following;
            const upperCurrent = upperStart + longitudeIndex;
            const upperFollowing = upperStart + following;
            faces.push([lowerCurrent, lowerFollowing, upperCurrent]);
            faces.push([lowerFollowing, upperFollowing, upperCurrent]);
        }
    }
    const lastRingStart = 1 + (ringCount - 1) * longitudeSegments;
    for (let longitudeIndex = 0; longitudeIndex < longitudeSegments; longitudeIndex += 1) {
        const current = lastRingStart + longitudeIndex;
        const following = lastRingStart + (longitudeIndex + 1) % longitudeSegments;
        faces.push([current, following, northPoleIndex]);
    }
    return indexedMesh(vertices, faces);
}

function turntableMesh(radius = 0.5, latitudeSegments = 8, longitudeSegments = 32) {
    const vertices = [{ x: 0, y: 0, z: -radius }];
    for (let latitudeIndex = 1; latitudeIndex <= latitudeSegments; latitudeIndex += 1) {
        const latitude = -Math.PI / 2 + (Math.PI / 2) * latitudeIndex / latitudeSegments;
        const ringRadius = radius * Math.cos(latitude);
        const z = radius * Math.sin(latitude);
        for (let longitudeIndex = 0; longitudeIndex < longitudeSegments; longitudeIndex += 1) {
            const longitude = 2 * Math.PI * longitudeIndex / longitudeSegments;
            vertices.push({
                x: ringRadius * Math.cos(longitude),
                y: ringRadius * Math.sin(longitude),
                z,
            });
        }
    }

    const faces = [];
    for (let longitudeIndex = 0; longitudeIndex < longitudeSegments; longitudeIndex += 1) {
        const current = 1 + longitudeIndex;
        const following = 1 + (longitudeIndex + 1) % longitudeSegments;
        faces.push([0, following, current]);
    }
    for (let ringIndex = 0; ringIndex < latitudeSegments - 1; ringIndex += 1) {
        const lowerStart = 1 + ringIndex * longitudeSegments;
        const upperStart = lowerStart + longitudeSegments;
        for (let longitudeIndex = 0; longitudeIndex < longitudeSegments; longitudeIndex += 1) {
            const following = (longitudeIndex + 1) % longitudeSegments;
            const lowerCurrent = lowerStart + longitudeIndex;
            const lowerFollowing = lowerStart + following;
            const upperCurrent = upperStart + longitudeIndex;
            const upperFollowing = upperStart + following;
            faces.push([lowerCurrent, lowerFollowing, upperCurrent]);
            faces.push([lowerFollowing, upperFollowing, upperCurrent]);
        }
    }
    const rimStart = 1 + (latitudeSegments - 1) * longitudeSegments;
    const capCenterIndex = vertices.length;
    vertices.push({ x: 0, y: 0, z: 0 });
    for (let longitudeIndex = 0; longitudeIndex < longitudeSegments; longitudeIndex += 1) {
        const current = rimStart + longitudeIndex;
        const following = rimStart + (longitudeIndex + 1) % longitudeSegments;
        faces.push([capCenterIndex, current, following]);
    }
    return indexedMesh(vertices, faces);
}

function minimumAngularExtent(values, defaultCenter, minimumWidth, minimumValue, maximumValue) {
    if (!values.length) {
        return [defaultCenter - minimumWidth / 2, defaultCenter + minimumWidth / 2];
    }
    let minimum = Math.min(...values);
    let maximum = Math.max(...values);
    const center = (minimum + maximum) / 2;
    const width = Math.max(maximum - minimum, minimumWidth);
    minimum = center - width / 2;
    maximum = center + width / 2;
    if (minimum < minimumValue) {
        maximum += minimumValue - minimum;
        minimum = minimumValue;
    }
    if (maximum > maximumValue) {
        minimum -= maximum - maximumValue;
        maximum = maximumValue;
    }
    return [Math.max(minimum, minimumValue), Math.min(maximum, maximumValue)];
}

function sphericalScreenMesh(history, current, radius = 0.985) {
    const azimuths = history.map((sample) => sample.azimuth);
    const elevations = history.map((sample) => sample.elevation);
    if (current) {
        azimuths.push(current.azimuth);
        elevations.push(current.elevation);
    }
    let [azimuthMinimum, azimuthMaximum] = minimumAngularExtent(azimuths, 0, 30, -180, 180);
    let [elevationMinimum, elevationMaximum] = minimumAngularExtent(elevations, 0, 30, -90, 90);

    const azimuthCenter = (azimuthMinimum + azimuthMaximum) / 2;
    const azimuthWidth = Math.min((azimuthMaximum - azimuthMinimum) * 1.1, 360);
    azimuthMinimum = azimuthCenter - azimuthWidth / 2;
    azimuthMaximum = azimuthCenter + azimuthWidth / 2;
    const elevationCenter = (elevationMinimum + elevationMaximum) / 2;
    const elevationWidth = (elevationMaximum - elevationMinimum) * 1.1;
    elevationMinimum = Math.max(-90, elevationCenter - elevationWidth / 2);
    elevationMaximum = Math.min(90, elevationCenter + elevationWidth / 2);

    const azimuthSegments = 32;
    const elevationSegments = 20;
    const vertices = [];
    for (let elevationIndex = 0; elevationIndex <= elevationSegments; elevationIndex += 1) {
        const elevationFraction = elevationIndex / elevationSegments;
        const elevation = elevationMinimum + (elevationMaximum - elevationMinimum) * elevationFraction;
        for (let azimuthIndex = 0; azimuthIndex <= azimuthSegments; azimuthIndex += 1) {
            const azimuthFraction = azimuthIndex / azimuthSegments;
            const azimuth = azimuthMinimum + (azimuthMaximum - azimuthMinimum) * azimuthFraction;
            vertices.push(azElUnitVector(azimuth, elevation, radius));
        }
    }
    const faces = [];
    const rowWidth = azimuthSegments + 1;
    for (let elevationIndex = 0; elevationIndex < elevationSegments; elevationIndex += 1) {
        const lowerStart = elevationIndex * rowWidth;
        const upperStart = lowerStart + rowWidth;
        for (let azimuthIndex = 0; azimuthIndex < azimuthSegments; azimuthIndex += 1) {
            const lowerLeft = lowerStart + azimuthIndex;
            const lowerRight = lowerLeft + 1;
            const upperLeft = upperStart + azimuthIndex;
            const upperRight = upperLeft + 1;
            faces.push([lowerLeft, lowerRight, upperLeft]);
            faces.push([lowerRight, upperRight, upperLeft]);
        }
    }
    return indexedMesh(vertices, faces);
}

function meshTrace(mesh, name, color, opacity = 1) {
    return {
        type: "mesh3d",
        ...mesh,
        name,
        color,
        opacity,
        flatshading: false,
        hoverinfo: opacity < 1 ? "skip" : "name",
        lighting: {
            ambient: 0.55,
            diffuse: 0.75,
            fresnel: 0.08,
            roughness: 0.8,
            specular: 0.15,
        },
        lightposition: { x: 3, y: 4, z: 5 },
        showlegend: false,
    };
}

function threeDimensionalPositionTraces(payload) {
    const history = payload.history;
    const current = payload.state.az_el_position;
    const historyCoordinates = history.map((sample) => azElUnitVector(sample.azimuth, sample.elevation));
    const currentCoordinate = current
        ? azElUnitVector(current.azimuth, current.elevation)
        : null;
    const paper = cssColor("--plot-paper", "#e6eeff");
    const currentColor = cssColor("--status-green", "#17823b");
    const rayColor = cssColor("--plot-boresight", "#005eb8");

    const traces = [
        meshTrace(
            turntableMesh(),
            "Turntable",
            cssColor("--plot-turntable", "#808080"),
        ),
        meshTrace(
            sphericalScreenMesh(history, current),
            "History screen",
            cssColor("--plot-screen", "#7a7a7a"),
            0.22,
        ),
        {
            type: "scatter3d",
            mode: "markers",
            x: historyCoordinates.map((coordinate) => coordinate.x),
            y: historyCoordinates.map((coordinate) => coordinate.y),
            z: historyCoordinates.map((coordinate) => coordinate.z),
            text: history.map((sample) => (
                `${localTimestamp(sample.timestamp)}<br>`
                + `Azimuth: ${sample.azimuth.toFixed(3)}°<br>`
                + `Elevation: ${sample.elevation.toFixed(3)}°<br>`
                + `Pan: ${sample.pan.toFixed(3)}°<br>`
                + `Tilt: ${sample.tilt.toFixed(3)}°`
            )),
            hovertemplate: "%{text}<extra></extra>",
            marker: {
                color: history.map((_, index) => index),
                colorscale: [
                    [0, cssColor("--plot-start", "#0033a0")],
                    [1, cssColor("--plot-end", "#c49300")],
                ],
                size: 4,
                line: { color: paper, width: 1 },
            },
            name: "Position history",
            showlegend: false,
        },
    ];
    if (currentCoordinate) {
        traces.push(
            {
                type: "scatter3d",
                mode: "lines",
                x: [0, currentCoordinate.x * 1.15],
                y: [0, currentCoordinate.y * 1.15],
                z: [0, currentCoordinate.z * 1.15],
                line: { color: rayColor, width: 7 },
                hoverinfo: "skip",
                name: "Current pointing ray",
                showlegend: false,
            },
            {
                type: "scatter3d",
                mode: "markers",
                x: [currentCoordinate.x],
                y: [currentCoordinate.y],
                z: [currentCoordinate.z],
                hovertemplate: (
                    `Azimuth: ${current.azimuth.toFixed(3)}°<br>`
                    + `Elevation: ${current.elevation.toFixed(3)}°<extra>Current</extra>`
                ),
                marker: {
                    color: currentColor,
                    size: 8,
                    line: { color: paper, width: 2 },
                },
                name: "Current",
                showlegend: false,
            },
        );
    }
    traces.push(
        meshTrace(
            sphereMesh({ x: 0, y: 0, z: 0 }, 0.075),
            "Origin",
            cssColor("--plot-origin", "#d62728"),
        ),
    );
    return traces;
}

function copyCameraVector(vector) {
    if (![vector?.x, vector?.y, vector?.z].every(Number.isFinite)) return null;
    return { x: vector.x, y: vector.y, z: vector.z };
}

function currentThreeDimensionalCamera(plotElement) {
    const camera = plotElement?.layout?.scene?.camera;
    const eye = copyCameraVector(camera?.eye);
    if (!eye) return null;
    const preserved = {
        eye,
        projection: {
            type: camera.projection?.type || "orthographic",
        },
    };
    const center = copyCameraVector(camera.center);
    const up = copyCameraVector(camera.up);
    if (center) preserved.center = center;
    if (up) preserved.up = up;
    return preserved;
}

function threeDimensionalPositionLayout(camera = null) {
    const grid = cssColor("--plot-grid", "#8fa6d2");
    const zero = cssColor("--plot-zero", "#5f79ad");
    const sceneAxis = (title, range) => ({
        title: { text: title, font: { size: 14 } },
        range,
        showticklabels: false,
        ticks: "",
        gridcolor: grid,
        zerolinecolor: zero,
    });
    return {
        paper_bgcolor: cssColor("--plot-paper", "#e6eeff"),
        font: {
            color: cssColor("--plot-text", "#000000"),
            family: '"Segoe UI", Arial, sans-serif',
            size: 13,
        },
        margin: { l: 12, r: 12, t: 12, b: 12 },
        showlegend: false,
        scene: {
            bgcolor: cssColor("--plot-background", "#d1e0ff"),
            aspectmode: "manual",
            aspectratio: { x: 4.45, y: 2.4, z: 2.4 },
            camera: camera || {
                eye: { x: -1.35, y: -1.65, z: 1.05 },
                projection: { type: "orthographic" },
            },
            uirevision: "turntable-three-dimensional-camera",
            xaxis: sceneAxis("X", [-1.2, 3.25]),
            yaxis: sceneAxis("Y", [-1.2, 1.2]),
            zaxis: sceneAxis("Z", [-1.2, 1.2]),
        },
        uirevision: "turntable-three-dimensional-camera",
    };
}

function kinematics(history, definition) {
    const velocity = [];
    for (let index = 1; index < history.length; index += 1) {
        const previous = history[index - 1];
        const current = history[index];
        const elapsed = (sampleTimestamp(current) - sampleTimestamp(previous)) / 1000;
        if (!Number.isFinite(elapsed) || elapsed <= 0) continue;
        velocity.push({
            timestamp: current.timestamp,
            x: (current[definition.xKey] - previous[definition.xKey]) / elapsed,
            y: (current[definition.yKey] - previous[definition.yKey]) / elapsed,
        });
    }

    const acceleration = [];
    for (let index = 1; index < velocity.length; index += 1) {
        const previous = velocity[index - 1];
        const current = velocity[index];
        const elapsed = (new Date(current.timestamp).valueOf() - new Date(previous.timestamp).valueOf()) / 1000;
        if (!Number.isFinite(elapsed) || elapsed <= 0) continue;
        acceleration.push({
            timestamp: current.timestamp,
            x: (current.x - previous.x) / elapsed,
            y: (current.y - previous.y) / elapsed,
        });
    }
    return { velocity, acceleration };
}

function kinematicsTraces(history, coordinateSystem) {
    const definition = COORDINATE_SYSTEMS[coordinateSystem];
    const { velocity, acceleration } = kinematics(history, definition);
    const xColor = cssColor("--plot-line", "#4368aa");
    const yColor = cssColor("--status-green", "#17823b");
    const accelerationXColor = cssColor("--target-red", "#c62828");
    const accelerationYColor = cssColor("--accent-dark", "#805c00");
    const trace = (name, values, key, color, yaxis = "y") => ({
        name,
        type: "scatter",
        mode: "lines",
        x: values.map((point) => point.timestamp),
        y: values.map((point) => point[key]),
        yaxis,
        line: { color, width: 2, dash: yaxis === "y2" ? "dot" : "solid" },
        hovertemplate: `%{x}<br>%{y:.3f}<extra>${name}</extra>`,
    });
    return [
        trace(`${definition.xLabel} velocity`, velocity, "x", xColor),
        trace(`${definition.yLabel} velocity`, velocity, "y", yColor),
        trace(`${definition.xLabel} acceleration`, acceleration, "x", accelerationXColor, "y2"),
        trace(`${definition.yLabel} acceleration`, acceleration, "y", accelerationYColor, "y2"),
    ];
}

function kinematicsLayout() {
    const layout = basePlotLayout("Time", "Velocity (°/sec)");
    layout.yaxis = plotAxis("Velocity (°/sec)");
    layout.yaxis2 = {
        ...plotAxis("Acceleration (°/sec²)"),
        overlaying: "y",
        side: "right",
    };
    layout.margin = { l: 62, r: 68, t: 22, b: 54 };
    layout.hovermode = "x unified";
    layout.uirevision = `turntable-kinematics-${plotRevision}`;
    return layout;
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
    Object.entries(COORDINATE_SYSTEMS).forEach(([name, definition]) => {
        const positionId = name === "az_el" ? "az-el-plot" : `${name.replace("_", "-")}-plot`;
        const kinematicsId = `${name.replace("_", "-")}-kinematics-plot`;
        window.Plotly.react(
            positionId,
            positionTraces(payload, name),
            basePlotLayout(`${definition.xLabel} (°)`, `${definition.yLabel} (°)`),
            config,
        );
        window.Plotly.react(
            kinematicsId,
            kinematicsTraces(payload.history, name),
            kinematicsLayout(),
            config,
        );
    });
    const threeDimensionalPlot = document.getElementById("three-dimensional-position-plot");
    const preservedCamera = currentThreeDimensionalCamera(threeDimensionalPlot);
    const threeDimensionalLayout = threeDimensionalPositionLayout(preservedCamera);
    Promise.resolve(window.Plotly.react(
        threeDimensionalPlot,
        threeDimensionalPositionTraces(payload),
        threeDimensionalLayout,
        { ...config, scrollZoom: true },
    )).then(() => {
        startCameraRotation(
            threeDimensionalPlot,
            threeDimensionalLayout.scene.camera.eye,
        );
    });
}

function commandValues(form) {
    const pan = Number.parseFloat(form.elements.pan.value.trim());
    const tilt = Number.parseFloat(form.elements.tilt.value.trim());
    if (!Number.isFinite(pan) || !Number.isFinite(tilt)) {
        throw new Error("Enter finite numeric values for both pan and tilt.");
    }
    if (form.dataset.commandForm === "set") {
        if (pan < -180 || pan > 180) {
            throw new Error("SET pan must be between -180° and 180°.");
        }
        if (tilt < -90 || tilt > 90) {
            throw new Error("SET tilt must be between -90° and 90°.");
        }
    }
    const values = { pan, tilt };
    const timeoutText = form.elements.timeout?.value.trim();
    if (timeoutText) {
        const timeout = Number.parseFloat(timeoutText);
        if (!Number.isFinite(timeout) || timeout <= 0) {
            throw new Error("Timeout must be a finite number greater than zero, or left blank for automatic.");
        }
        values.timeout = timeout;
    }
    return values;
}

function estimateAxisTime(delta, kind) {
    const angleDelta = Math.abs(delta);
    if (angleDelta <= 1e-12) return 0;
    if (kind === "horizontal") {
        return angleDelta < 2
            ? 0.5713 + 1.0117 * Math.sqrt(angleDelta)
            : 0.3940 * angleDelta + 1.2141;
    }
    return angleDelta < 2
        ? -0.1949 + 2.8896 * Math.sqrt(angleDelta)
        : 0.9038 * angleDelta + 2.0841;
}

function estimatedMoveTiming(pan, tilt) {
    const current = lastStatusPayload?.state?.corrected_position;
    if (!current) return null;
    const travel = Math.max(
        estimateAxisTime(pan - current.pan, "horizontal"),
        estimateAxisTime(tilt - current.tilt, "vertical"),
    );
    return {
        travel,
        timeout: travel * MOVE_TIMEOUT_SAFETY_FACTOR + MOVE_TIMEOUT_MINIMUM,
    };
}

function updateMoveEstimate() {
    const form = document.querySelector('[data-command-form="move"]');
    const output = document.querySelector("[data-move-estimate]");
    if (!form || !output) return;
    const pan = Number.parseFloat(form.elements.pan.value);
    const tilt = Number.parseFloat(form.elements.tilt.value);
    const timing = estimatedMoveTiming(pan, tilt);
    if (!timing || !Number.isFinite(pan) || !Number.isFinite(tilt)) {
        output.textContent = "Automatic timeout will be calculated when a current position is available.";
        return;
    }
    output.textContent = `Estimated travel: ${timing.travel.toFixed(2)} sec. Automatic timeout: ${timing.timeout.toFixed(2)} sec.`;
}

function setFeedback(message, kind = "") {
    const feedback = document.querySelector("[data-command-feedback]");
    if (!feedback) return;
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
    return payload;
}

function confirmNonzeroSet(values) {
    const dialog = document.getElementById("nonzero-set-confirmation");
    if (!dialog || typeof dialog.showModal !== "function") {
        return Promise.resolve(window.confirm("Are you sure? Make sure you're using new firmware."));
    }
    const position = dialog.querySelector("[data-set-confirmation-position]");
    if (position) {
        position.textContent = `Pan ${values.pan}° · Tilt ${values.tilt}°`;
    }
    dialog.returnValue = "cancel";
    dialog.showModal();
    return new Promise((resolve) => {
        dialog.addEventListener(
            "close",
            () => resolve(dialog.returnValue === "confirm"),
            { once: true },
        );
    });
}

async function submitCommandForm(form) {
    const command = form.dataset.commandForm;
    const button = form.querySelector("button[type=submit]");
    try {
        button.disabled = true;
        const values = commandValues(form);
        if (
            command === "set"
            && (values.pan !== 0 || values.tilt !== 0)
            && !(await confirmNonzeroSet(values))
        ) {
            setFeedback("SET command cancelled.");
            if (lastStatusPayload) applyControlState(lastStatusPayload.controls);
            return;
        }
        setFeedback(`Sending ${command.toUpperCase()} command…`);
        await sendCommand(`/turntable/${command}`, values);
        if (command === "set") resetPositionHistory({ preserveCursor: true });
        await refreshStatus();
    } catch (error) {
        setFeedback(error.message, "error");
        if (lastStatusPayload) applyControlState(lastStatusPayload.controls);
    }
}

async function jogTurntable(button) {
    const current = lastStatusPayload?.state?.corrected_position;
    const step = Number.parseFloat(document.getElementById("centering-step")?.value || "");
    if (!current) {
        setFeedback("A current physical position is required before jogging.", "error");
        return;
    }
    if (!Number.isFinite(step) || step <= 0) {
        setFeedback("Enter a finite jog step greater than zero.", "error");
        return;
    }
    const pan = current.pan + Number(button.dataset.jogPan) * step;
    const tilt = current.tilt + Number(button.dataset.jogTilt) * step;
    try {
        setFeedback(`Jogging to pan=${pan.toFixed(2)}°, tilt=${tilt.toFixed(2)}°…`);
        await sendCommand("/turntable/move", { pan, tilt });
        await refreshStatus();
    } catch (error) {
        setFeedback(error.message, "error");
    }
}

document.addEventListener("DOMContentLoaded", () => {
    setColorMode(document.documentElement.dataset.colorMode || "light", { persist: false });
    syncRotationControls();

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
    document.querySelectorAll("[data-rotation-toggle]").forEach((button) => {
        button.addEventListener("click", () => {
            cameraRotationSettings.paused = !cameraRotationSettings.paused;
            syncRotationControls();
        });
    });
    document.querySelectorAll("[data-rotation-speed]").forEach((slider) => {
        slider.addEventListener("input", () => {
            const speed = Number.parseFloat(slider.value);
            if (!Number.isFinite(speed) || speed <= 0) return;
            cameraRotationSettings.speed = speed;
            syncRotationControls();
        });
    });
    document.querySelectorAll("[data-command-form]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            submitCommandForm(form);
        });
    });
    document.querySelector('[data-command-form="move"]')?.addEventListener("input", updateMoveEstimate);
    document.querySelectorAll('[data-control="confirm"]').forEach((button) => {
        button.addEventListener("click", async () => {
            try {
                setFeedback("Confirming the reported position…");
                await sendCommand("/turntable/confirm");
                await refreshStatus();
            } catch (error) {
                setFeedback(error.message, "error");
            }
        });
    });
    document.querySelectorAll('[data-control="abort"]').forEach((button) => {
        button.addEventListener("click", async () => {
            try {
                setFeedback("Sending emergency stop…");
                await sendCommand("/turntable/abort");
                await refreshStatus();
            } catch (error) {
                setFeedback(error.message, "error");
            }
        });
    });
    document.querySelectorAll("[data-jog-pan]").forEach((button) => {
        button.addEventListener("click", () => jogTurntable(button));
    });
    document.getElementById("reset-position-history")?.addEventListener("click", () => {
        resetPositionHistory({ preserveCursor: true });
        setFeedback("Position graphs reset.", "success");
    });
    document.querySelectorAll(
        "#recent-history-time, #recent-history-rate, #history-max-time, #history-rate",
    ).forEach((input) => {
        input.addEventListener("change", () => {
            resetPositionHistory({ preserveCursor: false });
            refreshStatus();
        });
    });
    document.getElementById("refresh-interval")?.addEventListener("change", refreshStatus);
    refreshStatus();
});

document.addEventListener("click", () => setMenuOpen(false));
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
        setMenuOpen(false);
        document.getElementById("menu-toggle")?.focus();
    }
});
