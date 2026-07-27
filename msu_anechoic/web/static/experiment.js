"use strict";

let statusTimer = null;
let statusRequestInFlight = false;
let resultsRequestInFlight = false;
let desiredResultsKey = null;
let displayedResultsKey = null;
let polarRenderGeneration = 0;

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
    feedback.textContent = message;
    feedback.classList.toggle("is-error", error);
}

function angle(value) {
    return Number.isFinite(value) ? `${value.toFixed(2).replace(/\.?0+$/, "")}°` : "—";
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
        cell.colSpan = 6;
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
            angle(cut.step_size),
            cut.point_count.toLocaleString(),
        ].forEach((value) => {
            row.insertCell().textContent = value;
        });
    });
}

function cssColor(name, fallback) {
    return window.getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function finiteValues(series) {
    return series.filter((value) => Number.isFinite(value));
}

function polarFloor(cut) {
    const values = finiteValues([
        ...(cut.center.normalized_db || []),
        ...(cut.peak.normalized_db || []),
    ]);
    const minimum = values.length ? Math.min(...values) : -5;
    return Math.max(-60, Math.min(-5, Math.floor(minimum / 5) * 5));
}

function polarTrace(cut, seriesName, label, color, floor) {
    const series = cut[seriesName];
    const radii = series.normalized_db.map((value) =>
        Number.isFinite(value) ? Math.max(value, floor) - floor : null,
    );
    const customdata = series.normalized_db.map((value, index) => [
        value,
        series.absolute_dbm[index],
        cut.point_indexes[index],
    ]);
    return {
        type: "scatterpolar",
        mode: "lines+markers",
        name: label,
        theta: cut.angles,
        r: radii,
        customdata,
        line: { color, width: 2 },
        marker: { color, size: 6 },
        hovertemplate:
            `${label}<br>Angle %{theta:.2f}°` +
            "<br>Relative %{customdata[0]:.2f} dB" +
            "<br>Absolute %{customdata[1]:.2f} dBm" +
            "<br>Point %{customdata[2]:.0f}<extra></extra>",
    };
}

function renderPolarResults(payload, resultsKey) {
    const container = document.querySelector("[data-polar-plots]");
    container.querySelectorAll(".polar-plot").forEach((plot) => window.Plotly?.purge(plot));
    container.replaceChildren();
    document.querySelector("[data-results-path]").textContent = payload.source_path;
    displayedResultsKey = resultsKey;
    const renderGeneration = ++polarRenderGeneration;

    if (!payload.cuts.length) {
        const message = document.createElement("p");
        message.className = "results-description";
        message.textContent = "No plottable cut measurements were found in the results file.";
        container.append(message);
        return;
    }
    if (!window.Plotly) {
        const message = document.createElement("p");
        message.className = "experiment-feedback is-error";
        message.textContent = "Plotly did not load, so the polar plots cannot be displayed.";
        container.append(message);
        return;
    }

    const pendingPlots = payload.cuts.map((cut) => {
        const card = document.createElement("article");
        card.className = "polar-plot-card";
        const header = document.createElement("header");
        const heading = document.createElement("h3");
        const detail = document.createElement("span");
        heading.textContent = `${humanize(cut.direction)} · ${cut.id}`;
        detail.textContent = Number.isFinite(cut.fixed_angle)
            ? `Fixed at ${angle(cut.fixed_angle)} · ${cut.angles.length} points`
            : `${cut.angles.length} points`;
        header.append(heading, detail);

        const plot = document.createElement("div");
        plot.className = "polar-plot";
        plot.setAttribute("aria-label", `${cut.id} ${cut.direction} polar cut`);
        card.append(header, plot);
        container.append(card);
        return { cut, plot };
    });

    // Plotly measures its parent when rendering. Wait until every grid card is
    // present and the browser has calculated the final two-column layout.
    window.requestAnimationFrame(() => {
        if (renderGeneration !== polarRenderGeneration) return;
        pendingPlots.forEach(({ cut, plot }) => {
            if (!plot.isConnected) return;
            const floor = polarFloor(cut);
            const radialTicks = [];
            const radialTickText = [];
            for (let value = floor; value <= 0; value += 5) {
                radialTicks.push(value - floor);
                radialTickText.push(String(value));
            }
            const traces = [
                polarTrace(cut, "peak", "Detected peak", cssColor("--accent", "#0033a0"), floor),
                polarTrace(cut, "center", "Center frequency", cssColor("--plot-end", "#c49300"), floor),
            ];
            window.Plotly.react(
                plot,
                traces,
                {
                    margin: { t: 30, r: 35, b: 65, l: 35 },
                    paper_bgcolor: "rgba(0,0,0,0)",
                    font: { color: cssColor("--text", "#000000") },
                    showlegend: true,
                    legend: { orientation: "h", x: 0.5, xanchor: "center", y: -0.1 },
                    polar: {
                        bgcolor: cssColor("--surface-muted", "#c2d5ff"),
                        angularaxis: {
                            direction: "clockwise",
                            rotation: 90,
                            gridcolor: cssColor("--plot-grid", "#8fa6d2"),
                            linecolor: cssColor("--border-dark", "#6684c6"),
                            ticksuffix: "°",
                        },
                        radialaxis: {
                            range: [0, -floor],
                            tickvals: radialTicks,
                            ticktext: radialTickText,
                            ticksuffix: " dB",
                            angle: 45,
                            gridcolor: cssColor("--plot-grid", "#8fa6d2"),
                            linecolor: cssColor("--border-dark", "#6684c6"),
                        },
                    },
                },
                {
                    responsive: true,
                    displaylogo: false,
                    modeBarButtonsToRemove: ["select2d", "lasso2d"],
                },
            );
        });
    });
}

async function refreshResults(expectedResultsKey = desiredResultsKey) {
    if (resultsRequestInFlight) return;
    resultsRequestInFlight = true;
    try {
        const payload = await requestJson("/experiment/results");
        if (expectedResultsKey === desiredResultsKey) {
            renderPolarResults(payload, expectedResultsKey);
        }
    } catch (error) {
        if (expectedResultsKey !== desiredResultsKey) return;
        const container = document.querySelector("[data-polar-plots]");
        container.replaceChildren();
        const message = document.createElement("p");
        message.className = "experiment-feedback is-error";
        message.textContent = error.message;
        container.append(message);
    } finally {
        resultsRequestInFlight = false;
        if (desiredResultsKey && desiredResultsKey !== displayedResultsKey) {
            window.queueMicrotask(() => refreshResults(desiredResultsKey));
        }
    }
}

function renderStatus(payload) {
    const state = document.querySelector("[data-experiment-state]");
    state.textContent = humanize(payload.state).toUpperCase();
    state.dataset.state = payload.state;

    const definition = payload.experiment;
    document.querySelector("[data-experiment-name]").textContent = definition?.short_description || "No experiment loaded";
    document.querySelector("[data-experiment-description]").textContent =
        definition?.long_description || "Choose a saved definition or load a JSON file to inspect it here.";
    document.querySelector("[data-source-name]").textContent = payload.source_name || "—";
    document.querySelector("[data-total-points]").textContent = definition
        ? definition.total_points.toLocaleString()
        : "—";
    document.querySelector("[data-neutral-elevation]").textContent = definition
        ? angle(definition.neutral_elevation)
        : "—";
    document.querySelector("[data-output-folder]").textContent = definition?.output_folder || "—";

    const products = [];
    if (definition?.collect_center_frequency_data) products.push("center");
    if (definition?.collect_peak_data) products.push("peak");
    if (definition?.collect_trace_data) products.push("trace");
    document.querySelector("[data-data-products]").textContent = products.length ? products.join(", ") : "none";
    renderCuts(definition?.cuts || []);

    const resultsPanel = document.querySelector("[data-results-panel]");
    resultsPanel.hidden = !payload.results.available;
    document.querySelector("[data-results-path]").textContent = payload.results.path || "—";
    desiredResultsKey = payload.results.available
        ? `${payload.results.path}:${payload.results.version}`
        : null;
    if (desiredResultsKey && desiredResultsKey !== displayedResultsKey) {
        refreshResults(desiredResultsKey);
    } else if (!payload.results.available) {
        displayedResultsKey = null;
        document.querySelector("[data-polar-plots]").replaceChildren();
    }

    const completed = payload.progress.completed_points || 0;
    const total = payload.progress.total_points || definition?.total_points || 0;
    const progress = document.querySelector("[data-progress-bar]");
    progress.max = Math.max(total, 1);
    progress.value = Math.min(completed, Math.max(total, 1));
    document.querySelector("[data-progress-count]").textContent = total
        ? `${completed.toLocaleString()} / ${total.toLocaleString()}`
        : "—";
    document.querySelector("[data-progress-label]").textContent =
        payload.state === "running"
            ? payload.progress.cut_id
                ? `Running ${payload.progress.cut_id}`
                : "Starting hardware…"
            : humanize(payload.state);

    const ready = document.querySelector('input[name="ready"]');
    document.querySelector("[data-start]").disabled = !payload.can_start || !ready.checked;
    document.querySelector("[data-abort]").disabled = !payload.can_abort;

    if (payload.error) {
        setFeedback(payload.error, { error: true });
    } else if (payload.state === "completed") {
        setFeedback("Experiment completed successfully.");
    } else if (payload.state === "cancelled") {
        setFeedback("Experiment cancelled.");
    } else if (payload.state === "running") {
        setFeedback("Experiment is running. Keep this page open to monitor progress.");
    } else if (payload.state === "cancelling") {
        setFeedback("Stopping the experiment…");
    } else if (payload.loaded) {
        setFeedback("Definition loaded. Confirm readiness to start.");
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
    const selectedMode = document.documentElement.dataset.colorMode;
    setColorMode(selectedMode, { persist: false });

    document.getElementById("menu-toggle")?.addEventListener("click", (event) => {
        event.stopPropagation();
        const menu = document.getElementById("application-menu");
        setMenuOpen(menu.hidden);
    });
    document.addEventListener("click", (event) => {
        const menu = document.getElementById("application-menu");
        if (!menu?.hidden && !menu.contains(event.target) && event.target.id !== "menu-toggle") {
            setMenuOpen(false);
        }
    });
    document.querySelectorAll('input[name="color_mode"]').forEach((input) => {
        input.addEventListener("change", () => {
            setColorMode(input.value);
            if (desiredResultsKey) {
                displayedResultsKey = null;
                refreshResults(desiredResultsKey);
            }
        });
    });

    document.querySelector("[data-file-load-form]")?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const file = document.getElementById("experiment-file").files[0];
        if (!file) return;
        try {
            const definition = JSON.parse(await file.text());
            renderStatus(
                await requestJson("/experiment/load", {
                    method: "POST",
                    body: JSON.stringify({ definition, filename: file.name }),
                }),
            );
        } catch (error) {
            setFeedback(error instanceof SyntaxError ? "The selected file is not valid JSON." : error.message, {
                error: true,
            });
        }
    });

    document.querySelector("[data-server-load-form]")?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const path = document.getElementById("server-definition").value;
        try {
            renderStatus(
                await requestJson("/experiment/load-server", {
                    method: "POST",
                    body: JSON.stringify({ path }),
                }),
            );
        } catch (error) {
            setFeedback(error.message, { error: true });
        }
    });

    document.querySelector("[data-start-form]")?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        try {
            renderStatus(
                await requestJson("/experiment/start", {
                    method: "POST",
                    body: JSON.stringify({ output_mode: form.get("output_mode") }),
                }),
            );
        } catch (error) {
            setFeedback(error.message, { error: true });
        }
    });

    document.querySelector('input[name="ready"]')?.addEventListener("change", refreshStatus);
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
