const CAMERA_ROTATION_PERIOD_MS = 60_000;
const CAMERA_UPDATE_INTERVAL_MS = 50;
const rotatingPlots = new WeakMap();

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

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const state = {
        angle: 0,
        radius: 1,
        z: 1,
        hovered: false,
        visible: true,
        updating: false,
        lastFrame: performance.now(),
        lastUpdate: 0,
        observer: null,
    };
    updateRotationFromEye(state, initialEye);
    rotatingPlots.set(plotElement, state);

    plotElement.addEventListener("pointerenter", () => {
        state.hovered = true;
    });
    plotElement.addEventListener("pointerleave", () => {
        state.hovered = false;
        state.lastFrame = performance.now();
    });

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
            state.hovered
            || !state.visible
            || document.hidden
            || reducedMotion.matches
        );
        if (paused || state.updating) return;

        state.angle = (
            state.angle
            + elapsed * Math.PI * 2 / CAMERA_ROTATION_PERIOD_MS
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
    if (role === "grid-path") {
        trace.line.color = colors.line;
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
        if (plotElement.dataset.plotSource === "three-dimensional-figure") {
            Promise.resolve(render).then(() => {
                startCameraRotation(
                    plotElement,
                    figure.layout.scene.camera.eye,
                );
            });
        }
    });
}

document.addEventListener("DOMContentLoaded", () => {
    updateCoordinateFields();
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
        renderPlots(preview);
    }
});
