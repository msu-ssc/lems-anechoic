const CAMERA_ROTATION_PERIOD_MS = 60_000;
const CAMERA_UPDATE_INTERVAL_MS = 50;
const rotatingPlots = new WeakMap();
const cameraRotationSettings = {
    paused: true,
    speed: 1,
};
const plotVisibilitySettings = {
    "az-el-figure": { ideal: true, quantized: true, path: true },
    "pan-tilt-figure": { ideal: true, quantized: true, path: true },
    "three-dimensional-figure": { path: true },
};

function formatRotationSpeed(speed) {
    return `${speed.toFixed(2).replace(/\.?0+$/, "")}×`;
}

function syncRotationControls(root = document) {
    root.querySelectorAll("[data-rotation-toggle]").forEach((button) => {
        button.textContent = cameraRotationSettings.paused ? "Play" : "Pause";
        button.setAttribute(
            "aria-label",
            cameraRotationSettings.paused
                ? "Play 3D view rotation"
                : "Pause 3D view rotation",
        );
    });
    root.querySelectorAll("[data-rotation-speed]").forEach((slider) => {
        slider.value = String(cameraRotationSettings.speed);
    });
    root.querySelectorAll("[data-rotation-speed-output]").forEach((output) => {
        output.value = formatRotationSpeed(cameraRotationSettings.speed);
        output.textContent = output.value;
    });
}

function syncPlotVisibilityControls(root = document) {
    root.querySelectorAll("[data-plot-visibility-controls]").forEach((controls) => {
        const settings = plotVisibilitySettings[controls.dataset.plotVisibilityControls];
        if (!settings) return;
        controls.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
            checkbox.checked = settings[checkbox.value];
        });
    });
}

function applyPlotVisibility(figure, sourceId) {
    const settings = plotVisibilitySettings[sourceId];
    if (!settings) return;
    figure.data.forEach((trace) => {
        const representation = trace.meta?.representation;
        if (representation in settings) {
            trace.visible = settings[representation];
        }
        if (trace.meta?.line_segments === "with-markers") {
            trace.mode = settings.path ? "lines+markers" : "markers";
        }
        if (trace.meta?.line_segments === "line-only") {
            trace.visible = settings.path;
        }
    });
}

function updateLineSegmentVisibility(plotElement, isVisible) {
    const tracesWithMarkers = [];
    const lineOnlyTraces = [];
    plotElement.data.forEach((trace, index) => {
        if (trace.meta?.line_segments === "with-markers") {
            tracesWithMarkers.push(index);
        }
        if (trace.meta?.line_segments === "line-only") {
            lineOnlyTraces.push(index);
        }
    });
    if (tracesWithMarkers.length) {
        window.Plotly.restyle(
            plotElement,
            { mode: isVisible ? "lines+markers" : "markers" },
            tracesWithMarkers,
        );
    }
    if (lineOnlyTraces.length) {
        window.Plotly.restyle(
            plotElement,
            { visible: isVisible },
            lineOnlyTraces,
        );
    }
}

function cameraEyeFromRelayout(eventData) {
    if (eventData["scene.camera"]?.eye) {
        return eventData["scene.camera"].eye;
    }
    if (eventData["scene.camera.eye"]) {
        return eventData["scene.camera.eye"];
    }

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
    if (rotatingPlots.has(plotElement)) return;

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
        const observer = new IntersectionObserver((entries) => {
            state.visible = entries.some((entry) => entry.isIntersecting);
            state.lastFrame = performance.now();
        });
        observer.observe(plotElement);
        state.observer = observer;
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
        const paused = (
            cameraRotationSettings.paused
            || !state.visible
            || document.hidden
        );
        if (paused || state.updating) return;

        state.angle = (
            state.angle
            + (
                elapsed
                * cameraRotationSettings.speed
                * Math.PI
                * 2
                / CAMERA_ROTATION_PERIOD_MS
            )
        ) % (Math.PI * 2);
        if (now - state.lastUpdate < CAMERA_UPDATE_INTERVAL_MS) return;

        state.lastUpdate = now;
        state.updating = true;
        const eye = {
            x: state.radius * Math.cos(state.angle),
            y: state.radius * Math.sin(state.angle),
            z: state.z,
        };
        Promise.resolve(
            window.Plotly.relayout(plotElement, {
                "scene.camera.eye": eye,
            }),
        ).finally(() => {
            state.updating = false;
        });
    }

    window.requestAnimationFrame(animate);
}

function maskShape(path, color) {
    return {
        type: "path",
        xref: "x",
        yref: "y",
        path,
        fillcolor: color,
        opacity: 0.28,
        line: { width: 0 },
        layer: "below",
    };
}

function azimuthElevationMaskShapes(regions, color) {
    return regions.map((region) => {
        const boundaryPoints = region.azimuths.map(
            (azimuth, index) => [azimuth, region.elevations[index]],
        );
        const pathPoints = [
            [region.azimuths[0], region.mask_edge],
            ...boundaryPoints,
            [region.azimuths.at(-1), region.mask_edge],
        ];
        const path = pathPoints
            .map(([x, y], pointIndex) => (
                `${pointIndex === 0 ? "M" : "L"} ${x} ${y}`
            ))
            .join(" ");
        return maskShape(`${path} Z`, color);
    });
}

function panTiltMaskShapes(maximumTilt, color) {
    return [{
        type: "rect",
        xref: "paper",
        yref: "y",
        x0: 0,
        x1: 1,
        y0: maximumTilt,
        y1: 90,
        fillcolor: color,
        opacity: 0.28,
        line: { width: 0 },
        layer: "below",
    }];
}

function applyInaccessibleMasks(plotElement, metadata, color) {
    const fullLayout = plotElement._fullLayout;
    if (!fullLayout?.xaxis?.range || !fullLayout?.yaxis?.range) return;

    const xRange = [...fullLayout.xaxis.range];
    const yRange = [...fullLayout.yaxis.range];
    const shapes = metadata.coordinate_system === "az_el"
        ? azimuthElevationMaskShapes(
            metadata.inaccessible_regions,
            color,
        )
        : panTiltMaskShapes(metadata.maximum_turntable_tilt, color);

    window.Plotly.relayout(plotElement, {
        shapes,
        "xaxis.range": xRange,
        "xaxis.autorange": false,
        "yaxis.range": yRange,
        "yaxis.autorange": false,
    });
}

function updateCoordinateFields() {
    const selected = document.querySelector('input[name="input_system"]:checked')?.value;
    document.querySelectorAll("[data-coordinate-fields]").forEach((element) => {
        const isActive = element.dataset.coordinateFields === selected;
        element.hidden = !isActive;
        element.querySelectorAll("input").forEach((input) => {
            input.disabled = !isActive;
        });
    });
}

function updateSimpleGridList() {
    const cards = [...document.querySelectorAll("[data-simple-grid]")];
    cards.forEach((card, index) => {
        const number = card.querySelector("[data-simple-grid-number]");
        if (number) number.textContent = String(index + 1);
        card.querySelectorAll("[data-simple-grid-option]").forEach((control) => {
            control.name = `${control.dataset.simpleGridOption}_${index}`;
        });
        const removeButton = card.querySelector("[data-remove-simple-grid]");
        if (removeButton) removeButton.disabled = cards.length === 1;
    });
}

function notifyGridFormChanged() {
    document.getElementById("grid-form")?.dispatchEvent(
        new Event("change", { bubbles: true }),
    );
}

function addSimpleGrid() {
    const list = document.querySelector("[data-simple-grid-list]");
    const source = list?.querySelector("[data-simple-grid]:last-child");
    if (!list || !source) return;

    const clone = source.cloneNode(true);
    const sourceInputs = source.querySelectorAll("input");
    clone.querySelectorAll("input").forEach((input, index) => {
        if (input.type === "checkbox" || input.type === "radio") {
            input.checked = sourceInputs[index].checked;
        } else {
            input.value = sourceInputs[index].value;
        }
    });
    list.append(clone);
    updateCoordinateFields();
    updateSimpleGridList();
    clone.querySelector('input:not(:disabled)')?.focus();
    notifyGridFormChanged();
}

function removeSimpleGrid(button) {
    const cards = document.querySelectorAll("[data-simple-grid]");
    if (cards.length <= 1) return;
    button.closest("[data-simple-grid]")?.remove();
    updateSimpleGridList();
    notifyGridFormChanged();
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
        // The control remains functional when storage is unavailable.
    }
}

function setColorMode(mode, { persist = true } = {}) {
    if (mode !== "light" && mode !== "dark") return;

    document.documentElement.dataset.colorMode = mode;
    const control = document.querySelector(`input[name="color_mode"][value="${mode}"]`);
    if (control) control.checked = true;
    if (persist) storeColorMode(mode);
    renderPlots();
}

function plotColors() {
    const styles = window.getComputedStyle(document.documentElement);
    const value = (name, fallback) => styles.getPropertyValue(name).trim() || fallback;
    return {
        paper: value("--plot-paper", "#e6eeff"),
        background: value("--plot-background", "#d1e0ff"),
        text: value("--plot-text", "#343434"),
        grid: value("--plot-grid", "#8fa6d2"),
        zero: value("--plot-zero", "#5f79ad"),
        line: value("--plot-line", "#4368aa"),
        start: value("--plot-start", "#0033a0"),
        end: value("--plot-end", "#c49300"),
        turntable: value("--plot-turntable", "#808080"),
        origin: value("--plot-origin", "#d62728"),
        source: value("--plot-source", "#2ca02c"),
        boresight: value("--plot-boresight", "#005eb8"),
        screen: value("--plot-screen", "#7a7a7a"),
        inaccessible: value("--plot-inaccessible", "#6f7680"),
        ideal: value("--plot-ideal", "#626a76"),
    };
}

function applyTraceColors(trace, colors) {
    const role = trace.meta?.role;

    if (role === "turntable") {
        trace.color = colors.turntable;
        return;
    }
    if (role === "origin") {
        trace.color = colors.origin;
        return;
    }
    if (role === "source") {
        trace.color = colors.source;
        return;
    }
    if (role === "boresight") {
        trace.line.color = colors.boresight;
        return;
    }
    if (role === "grid-screen") {
        trace.color = colors.screen;
        return;
    }
    if (role === "grid-ideal") {
        trace.line.color = colors.ideal;
        trace.marker.color = colors.ideal;
        trace.marker.line.color = colors.ideal;
        return;
    }
    if (role === "grid-route") {
        trace.line.color = colors.line;
        return;
    }
    if (role === "grid-points") {
        trace.marker.colorscale = [[0, colors.start], [1, colors.end]];
        trace.marker.line.color = colors.paper;
        return;
    }
    if (role === "grid-path") {
        trace.line.color = colors.line;
        trace.marker.colorscale = [[0, colors.start], [1, colors.end]];
        trace.marker.line.color = colors.paper;
        return;
    }
    if (role === "quantization-error") {
        trace.marker.colorscale = [[0, colors.start], [1, colors.end]];
        trace.marker.line.color = colors.paper;
        return;
    }
    if (role === "grid-start") {
        trace.marker.color = colors.start;
        trace.marker.line.color = colors.paper;
        return;
    }
    if (role === "grid-end") {
        trace.marker.color = colors.end;
        trace.marker.line.color = colors.paper;
    }
}

function renderPlots(root = document) {
    if (!window.Plotly) {
        window.setTimeout(() => renderPlots(root), 30);
        return;
    }

    root.querySelectorAll("[data-plot-source]").forEach((plotElement) => {
        const source = document.getElementById(plotElement.dataset.plotSource);
        if (!source) return;

        const figure = JSON.parse(source.textContent);
        applyPlotVisibility(figure, plotElement.dataset.plotSource);
        const colors = plotColors();
        figure.layout.paper_bgcolor = colors.paper;
        figure.layout.plot_bgcolor = colors.background;
        figure.layout.font.color = colors.text;
        if (figure.layout.xaxis && figure.layout.yaxis) {
            figure.layout.xaxis.gridcolor = colors.grid;
            figure.layout.xaxis.zerolinecolor = colors.zero;
            figure.layout.yaxis.gridcolor = colors.grid;
            figure.layout.yaxis.zerolinecolor = colors.zero;
        }
        if (figure.layout.scene) {
            figure.layout.scene.bgcolor = colors.background;
            ["xaxis", "yaxis", "zaxis"].forEach((axisName) => {
                figure.layout.scene[axisName].gridcolor = colors.grid;
                figure.layout.scene[axisName].zerolinecolor = colors.zero;
            });
        }
        figure.data.forEach((trace) => applyTraceColors(trace, colors));
        const render = window.Plotly.react(
            plotElement,
            figure.data,
            figure.layout,
            figure.config,
        );
        Promise.resolve(render).then(() => {
            if (figure.layout.meta?.maximum_turntable_tilt !== undefined) {
                applyInaccessibleMasks(
                    plotElement,
                    figure.layout.meta,
                    colors.inaccessible,
                );
            }
            if (plotElement.dataset.plotSource === "three-dimensional-figure") {
                startCameraRotation(
                    plotElement,
                    figure.layout.scene.camera.eye,
                );
            }
        });
    });
}

document.addEventListener("DOMContentLoaded", () => {
    updateCoordinateFields();
    updateSimpleGridList();
    syncRotationControls();
    syncPlotVisibilityControls();
    setColorMode(document.documentElement.dataset.colorMode || "light", { persist: false });

    document.getElementById("menu-toggle")?.addEventListener("click", (event) => {
        event.stopPropagation();
        const isOpen = event.currentTarget.getAttribute("aria-expanded") === "true";
        setMenuOpen(!isOpen);
    });

    document.getElementById("application-menu")?.addEventListener("click", (event) => {
        event.stopPropagation();
    });

    document.querySelectorAll('input[name="color_mode"]').forEach((control) => {
        control.addEventListener("change", (event) => {
            if (event.currentTarget.checked) {
                setColorMode(event.currentTarget.value);
            }
        });
    });
});

document.addEventListener("change", (event) => {
    if (event.target.matches('input[name="input_system"]')) {
        updateCoordinateFields();
    }

    const controls = event.target.closest("[data-plot-visibility-controls]");
    if (!controls || !event.target.matches('input[type="checkbox"]')) return;
    const sourceId = controls.dataset.plotVisibilityControls;
    const settings = plotVisibilitySettings[sourceId];
    if (!settings || !(event.target.value in settings)) return;

    settings[event.target.value] = event.target.checked;
    syncPlotVisibilityControls(controls);
    const plotElement = document.querySelector(`[data-plot-source="${sourceId}"]`);
    if (!plotElement?.data) return;
    if (event.target.value === "path") {
        updateLineSegmentVisibility(plotElement, event.target.checked);
        return;
    }
    const traceIndexes = plotElement.data
        .map((trace, index) => (
            trace.meta?.representation === event.target.value ? index : -1
        ))
        .filter((index) => index >= 0);
    if (traceIndexes.length) {
        window.Plotly.restyle(
            plotElement,
            { visible: event.target.checked },
            traceIndexes,
        );
    }
});

document.addEventListener("click", (event) => {
    if (event.target.closest("[data-add-simple-grid]")) {
        addSimpleGrid();
        return;
    }
    const removeButton = event.target.closest("[data-remove-simple-grid]");
    if (removeButton) {
        removeSimpleGrid(removeButton);
        return;
    }
    if (!event.target.closest("[data-rotation-toggle]")) return;
    cameraRotationSettings.paused = !cameraRotationSettings.paused;
    syncRotationControls();
});

document.addEventListener("input", (event) => {
    if (!event.target.matches("[data-rotation-speed]")) return;
    const speed = Number.parseFloat(event.target.value);
    if (!Number.isFinite(speed)) return;
    cameraRotationSettings.speed = speed;
    syncRotationControls();
});

document.addEventListener("click", () => setMenuOpen(false));

document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
        setMenuOpen(false);
        document.getElementById("menu-toggle")?.focus();
    }
});

document.body.addEventListener("htmx:afterSwap", () => {
    const preview = document.getElementById("grid-preview");
    if (preview) {
        syncRotationControls(preview);
        syncPlotVisibilityControls(preview);
        renderPlots(preview);
    }
});
