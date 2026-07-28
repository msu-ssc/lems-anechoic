"use strict";

let statusTimer = null;
let statusRequestInFlight = false;

function setMenuOpen(isOpen) {
    const toggle = document.getElementById("menu-toggle");
    const menu = document.getElementById("application-menu");
    if (!toggle || !menu) return;
    toggle.setAttribute("aria-expanded", String(isOpen));
    toggle.setAttribute("aria-label", isOpen ? "Close navigation menu" : "Open navigation menu");
    menu.hidden = !isOpen;
}

function setColorMode(mode, { persist = true } = {}) {
    if (mode !== "light" && mode !== "dark") return;
    document.documentElement.dataset.colorMode = mode;
    const input = document.querySelector(`input[name="color_mode"][value="${mode}"]`);
    if (input) input.checked = true;
    if (persist) {
        try {
            window.localStorage.setItem("grid-designer-color-mode", mode);
        } catch {
            // The control remains useful without local storage.
        }
    }
}

function setFeedback(message, { error = false } = {}) {
    const feedback = document.querySelector("[data-feedback]");
    if (!feedback) return;
    feedback.textContent = message;
    feedback.classList.toggle("is-error", error);
}

function angle(value) {
    return Number.isFinite(value) ? `${value.toFixed(2).replace(/\.?0+$/, "")}°` : "—";
}

function duration(seconds) {
    if (!Number.isFinite(seconds)) return "—";
    const rounded = Math.max(0, Math.round(seconds));
    if (rounded < 60) return `${rounded}s`;
    const hours = Math.floor(rounded / 3600);
    const minutes = Math.floor((rounded % 3600) / 60);
    const remainder = rounded % 60;
    return [
        hours ? `${hours}h` : "",
        minutes ? `${minutes}m` : "",
        !hours && remainder ? `${remainder}s` : "",
    ].filter(Boolean).join(" ");
}

function humanize(value) {
    return String(value || "empty").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

async function requestJson(url, options = {}) {
    const response = await window.fetch(url, {
        ...options,
        headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            ...(options.headers || {}),
        },
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "The request failed.");
    return payload;
}

function renderCuts(cuts) {
    const body = document.querySelector("[data-cut-list]");
    body.replaceChildren();
    if (!cuts.length) {
        const row = body.insertRow();
        const cell = row.insertCell();
        cell.colSpan = 7;
        cell.textContent = "No cuts loaded.";
        return;
    }
    cuts.forEach((cut) => {
        const row = body.insertRow();
        [
            cut.id,
            humanize(cut.direction),
            angle(cut.fixed_angle),
            `${angle(cut.start_angle)} to ${angle(cut.end_angle)}`,
            cut.variable_spacing ? "Variable" : angle(cut.step_size),
            cut.point_count.toLocaleString(),
            duration(cut.travel_seconds),
        ].forEach((value) => {
            row.insertCell().textContent = value;
        });
    });
}

function setProgress(selector, completed, total) {
    const bar = document.querySelector(selector);
    const safeTotal = Math.max(1, Number(total) || 0);
    bar.max = safeTotal;
    bar.value = Math.min(safeTotal, Math.max(0, Number(completed) || 0));
}

function renderProgress(payload) {
    const progress = payload.progress || {};
    const totalPoints = progress.total_points ?? payload.experiment?.total_points ?? 0;
    const completedPoints = progress.completed_points ?? 0;
    const cutCount = progress.cut_count ?? payload.experiment?.cuts?.length ?? 0;
    const completedCuts = progress.completed_cuts ?? 0;
    const pointsInCut = progress.points_in_cut ?? 0;
    const completedInCut = progress.completed_points_in_cut ?? 0;
    const totalEstimate = progress.estimated_total_travel_seconds ?? payload.experiment?.travel_seconds;
    const remaining = Number.isFinite(totalEstimate) && totalPoints
        ? totalEstimate * Math.max(0, 1 - completedPoints / totalPoints)
        : null;
    const cutEstimate = progress.estimated_cut_travel_seconds;
    const cutRemaining = Number.isFinite(cutEstimate) && pointsInCut
        ? cutEstimate * Math.max(0, 1 - completedInCut / pointsInCut)
        : null;

    setProgress("[data-points-progress-bar]", completedPoints, totalPoints);
    setProgress("[data-cuts-progress-bar]", completedCuts, cutCount);
    setProgress("[data-cut-points-progress-bar]", completedInCut, pointsInCut);
    document.querySelector("[data-points-progress-count]").textContent =
        totalPoints ? `${completedPoints.toLocaleString()} / ${totalPoints.toLocaleString()}` : "—";
    document.querySelector("[data-cuts-progress-count]").textContent =
        cutCount ? `${completedCuts.toLocaleString()} / ${cutCount.toLocaleString()}` : "—";
    document.querySelector("[data-cut-points-progress-count]").textContent =
        pointsInCut ? `${completedInCut.toLocaleString()} / ${pointsInCut.toLocaleString()}` : "—";
    document.querySelector("[data-points-time]").textContent = Number.isFinite(totalEstimate)
        ? `${duration(totalEstimate)} travel planned · about ${duration(remaining)} remaining`
        : "Waiting for an experiment.";
    document.querySelector("[data-cuts-time]").textContent = progress.cut_id
        ? `${progress.cut_id} · cut ${progress.cut_index || completedCuts} of ${cutCount} · ${duration(cutEstimate)} planned`
        : Number.isFinite(totalEstimate) ? `${duration(totalEstimate)} total travel planned` : "—";
    document.querySelector("[data-cut-points-time]").textContent = Number.isFinite(cutRemaining)
        ? `about ${duration(cutRemaining)} remaining in this cut`
        : "—";
}

function renderStatus(payload) {
    const state = document.querySelector("[data-experiment-state]");
    state.textContent = humanize(payload.state).toUpperCase();
    state.dataset.state = payload.state;

    const definition = payload.experiment;
    document.querySelector("[data-experiment-name]").textContent =
        definition?.short_description || "No experiment loaded";
    document.querySelector("[data-experiment-description]").textContent =
        definition?.long_description || "Choose a saved definition or load a JSON file to inspect it here.";
    document.querySelector("[data-source-name]").textContent = payload.source_name || "—";
    document.querySelector("[data-total-points]").textContent =
        definition ? definition.total_points.toLocaleString() : "—";
    document.querySelector("[data-total-travel]").textContent =
        definition ? duration(definition.travel_seconds) : "—";
    document.querySelector("[data-output-folder]").textContent = definition?.output_folder || "—";

    const products = [];
    if (definition?.collect_center_frequency_data) products.push("center");
    if (definition?.collect_peak_data) products.push("peak");
    if (definition?.collect_trace_data) products.push("trace");
    document.querySelector("[data-data-products]").textContent = products.length ? products.join(", ") : "none";
    renderCuts(definition?.cuts || []);
    renderProgress(payload);

    document.querySelector("[data-start]").disabled = !payload.can_start;
    document.querySelector("[data-abort]").disabled = !payload.can_abort;
    document.querySelectorAll("[data-server-load-form] button, [data-file-load-form] button").forEach((button) => {
        button.disabled = payload.state === "running" || payload.state === "cancelling";
    });

    if (payload.error) {
        setFeedback(payload.error, { error: true });
    } else if (payload.state === "running") {
        setFeedback(`Measuring ${payload.progress.cut_id || "the experiment"}…`);
    } else if (payload.state === "completed") {
        setFeedback("Experiment completed. Open graphs to inspect the measurements.");
    } else if (payload.loaded) {
        setFeedback("Experiment ready. Review the plan and confirm readiness before starting.");
    } else {
        setFeedback("Load an experiment definition to begin.");
    }
}

async function refreshStatus() {
    if (statusRequestInFlight) return;
    statusRequestInFlight = true;
    try {
        renderStatus(await requestJson("/experiment/status"));
    } catch (error) {
        setFeedback(error.message, { error: true });
    } finally {
        statusRequestInFlight = false;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("menu-toggle")?.addEventListener("click", (event) => {
        event.stopPropagation();
        const menu = document.getElementById("application-menu");
        setMenuOpen(menu?.hidden ?? true);
    });
    document.addEventListener("click", (event) => {
        const menu = document.getElementById("application-menu");
        const toggle = document.getElementById("menu-toggle");
        if (menu && !menu.hidden && !menu.contains(event.target) && !toggle?.contains(event.target)) {
            setMenuOpen(false);
        }
    });
    document.querySelectorAll('input[name="color_mode"]').forEach((input) => {
        input.addEventListener("change", () => setColorMode(input.value));
    });
    setColorMode(document.documentElement.dataset.colorMode, { persist: false });

    document.querySelector("[data-server-load-form]")?.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            const path = new FormData(event.currentTarget).get("path");
            renderStatus(await requestJson("/experiment/load-server", {
                method: "POST",
                body: JSON.stringify({ path }),
            }));
        } catch (error) {
            setFeedback(error.message, { error: true });
        }
    });

    document.querySelector("[data-file-load-form]")?.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            const file = new FormData(event.currentTarget).get("experiment_file");
            const definition = JSON.parse(await file.text());
            renderStatus(await requestJson("/experiment/load", {
                method: "POST",
                body: JSON.stringify({ definition, filename: file.name }),
            }));
        } catch (error) {
            setFeedback(error.message, { error: true });
        }
    });

    document.querySelector("[data-start-form]")?.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            const outputMode = new FormData(event.currentTarget).get("output_mode");
            renderStatus(await requestJson("/experiment/start", {
                method: "POST",
                body: JSON.stringify({ output_mode: outputMode }),
            }));
        } catch (error) {
            setFeedback(error.message, { error: true });
        }
    });

    document.querySelector("[data-abort]")?.addEventListener("click", async () => {
        try {
            renderStatus(await requestJson("/experiment/abort", { method: "POST", body: "{}" }));
        } catch (error) {
            setFeedback(error.message, { error: true });
        }
    });

    refreshStatus();
    statusTimer = window.setInterval(refreshStatus, 1000);
    window.addEventListener("pagehide", () => window.clearInterval(statusTimer));
});
