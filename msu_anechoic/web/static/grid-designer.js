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

function renderPlots(root = document) {
    if (!window.Plotly) {
        window.setTimeout(() => renderPlots(root), 30);
        return;
    }

    root.querySelectorAll("[data-plot-source]").forEach((plotElement) => {
        const source = document.getElementById(plotElement.dataset.plotSource);
        if (!source) return;

        const figure = JSON.parse(source.textContent);
        window.Plotly.react(
            plotElement,
            figure.data,
            figure.layout,
            figure.config,
        );
    });
}

document.addEventListener("DOMContentLoaded", () => {
    updateCoordinateFields();
    renderPlots();

    document.getElementById("menu-toggle")?.addEventListener("click", (event) => {
        event.stopPropagation();
        const isOpen = event.currentTarget.getAttribute("aria-expanded") === "true";
        setMenuOpen(!isOpen);
    });

    document.getElementById("application-menu")?.addEventListener("click", (event) => {
        event.stopPropagation();
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
