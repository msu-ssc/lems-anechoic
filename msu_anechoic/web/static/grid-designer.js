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
});

document.addEventListener("change", (event) => {
    if (event.target.matches('input[name="input_system"]')) {
        updateCoordinateFields();
    }
});

document.body.addEventListener("htmx:afterSwap", () => {
    const preview = document.getElementById("grid-preview");
    if (preview) {
        renderPlots(preview);
    }
});
