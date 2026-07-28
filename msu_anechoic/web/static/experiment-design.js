"use strict";

const GRID_STORAGE_KEY = "experiment-designer-grid";
let gridDefinition = null;

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
    if (!persist) return;
    try {
        window.localStorage.setItem("grid-designer-color-mode", mode);
    } catch {
        // The control remains useful without local storage.
    }
}

function setExperimentDesignFeedback(message, { error = false, link = null } = {}) {
    const feedback = document.querySelector("[data-experiment-design-feedback]");
    if (!feedback) return;
    feedback.replaceChildren(document.createTextNode(message));
    feedback.classList.toggle("is-error", error);
    if (link) {
        feedback.append(document.createTextNode(" "));
        const anchor = document.createElement("a");
        anchor.href = link.href;
        anchor.textContent = link.label;
        feedback.append(anchor);
    }
}

function readGridDefinition() {
    const suppliedByUrl = new URLSearchParams(window.location.search);
    if (suppliedByUrl.has("input_system")) {
        try {
            window.sessionStorage.setItem(
                GRID_STORAGE_KEY,
                suppliedByUrl.toString(),
            );
        } catch {
            // The in-memory copy below remains usable for this page load.
        }
        window.history.replaceState({}, "", "/experiment/design");
        return suppliedByUrl;
    }

    try {
        const stored = window.sessionStorage.getItem(GRID_STORAGE_KEY);
        return stored ? new URLSearchParams(stored) : null;
    } catch {
        return null;
    }
}

function renderGridDefinition() {
    const button = document.querySelector("[data-save-experiment]");
    const status = document.querySelector("[data-grid-source-status]");
    const description = document.querySelector("[data-grid-source-description]");
    const facts = document.querySelector("[data-grid-source-facts]");
    const chooseLink = document.querySelector("[data-choose-grid]");

    gridDefinition = readGridDefinition();
    if (!gridDefinition?.has("input_system")) {
        if (status) status.textContent = "No grid selected";
        if (description) {
            description.textContent = "Open Grid Designer and choose “Use this grid in an experiment.”";
        }
        if (button) button.disabled = true;
        setExperimentDesignFeedback("Choose a grid before saving.", { error: true });
        return;
    }

    const inputSystem = gridDefinition.get("input_system");
    const names = gridDefinition.getAll("grid_name").filter(Boolean);
    const coordinateLabel = inputSystem === "pan_tilt"
        ? "Pan / tilt"
        : "Azimuth / elevation";
    document.querySelector("[data-grid-coordinate-system]").textContent = coordinateLabel;
    document.querySelector("[data-grid-count]").textContent = String(Math.max(1, names.length));
    document.querySelector("[data-grid-names]").textContent = names.join(", ") || "Grid 1";
    if (status) status.textContent = "Grid loaded";
    if (description) {
        description.textContent = inputSystem === "pan_tilt"
            ? "This experiment will use the current Grid Designer route."
            : "Azimuth/elevation experiment conversion is not supported yet; saving will report an error.";
    }
    if (facts) facts.hidden = false;
    if (chooseLink) chooseLink.textContent = "Change grid";
    if (button) button.disabled = false;
    setExperimentDesignFeedback(
        inputSystem === "pan_tilt"
            ? "Ready to create parameters.json."
            : "Azimuth/elevation grids are not supported yet.",
        { error: inputSystem !== "pan_tilt" },
    );
}

async function saveExperimentDesign() {
    const form = document.getElementById("experiment-design-form");
    const button = document.querySelector("[data-save-experiment]");
    if (!form || !button || !gridDefinition || !form.reportValidity()) return;

    button.disabled = true;
    setExperimentDesignFeedback("Saving parameters.json…");
    try {
        const query = new URLSearchParams(gridDefinition);
        for (const [name, value] of new FormData(form)) {
            query.set(name, value);
        }
        const response = await window.fetch(`/experiment/design?${query}`, {
            method: "POST",
            headers: { Accept: "application/json" },
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || "Could not save the experiment.");
        setExperimentDesignFeedback(
            `Saved ${payload.point_count.toLocaleString()} points in ${payload.cut_count.toLocaleString()} cuts to ${payload.path}.`,
            {
                link: {
                    href: "/experiment",
                    label: "Open Experiment",
                },
            },
        );
    } catch (error) {
        setExperimentDesignFeedback(error.message, { error: true });
    } finally {
        button.disabled = false;
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
    renderGridDefinition();
    document.getElementById("experiment-design-form")?.addEventListener(
        "submit",
        (event) => {
            event.preventDefault();
            saveExperimentDesign();
        },
    );
});
