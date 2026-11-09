/*
 * epaData charts: draws every Plotly figure on the page from its JSON block
 * (<script type="application/json" id="spec-ID">), and wires up the "PNG image" buttons.
 * The figures themselves are built in Python (dashboard.py), so this file stays small.
 */
(function () {
    "use strict";

    function specFor(id) {
        var block = document.getElementById("spec-" + id);
        if (!block) {
            return null;
        }
        return JSON.parse(block.textContent);
    }

    function configFor(spec) {
        return {
            displaylogo: false,
            responsive: true,
            modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d", "toggleSpikelines"],
            toImageButtonOptions: { format: "png", scale: 2, filename: spec.filename }
        };
    }

    function showMessage(node, message) {
        var paragraph = document.createElement("p");
        paragraph.className = "chart-empty";
        paragraph.textContent = message;
        node.style.minHeight = "0";
        node.appendChild(paragraph);
    }

    var plots = document.querySelectorAll("[data-chart]");

    if (!window.Plotly) {
        for (var i = 0; i < plots.length; i++) {
            showMessage(plots[i], "The chart library (Plotly) didn't load. Charts need an internet connection; "
                + "the numbers are in the table below.");
        }
        return;
    }

    // On a phone: a smaller title broken over two lines, and the legend under the chart
    function fitToWidth(layout, width) {
        if (width >= 520) {
            return layout;
        }
        var fitted = JSON.parse(JSON.stringify(layout));
        if (fitted.title && fitted.title.text) {
            var title = fitted.title.text;
            var limit = Math.max(24, Math.floor(width / 8));
            if (title.length > limit) {
                var cut = title.lastIndexOf(" ", limit);
                if (cut > 0) {
                    title = title.slice(0, cut) + "<br>" + title.slice(cut + 1);
                }
            }
            fitted.title.text = title;
            fitted.title.font = Object.assign({}, fitted.title.font, { size: 14 });
            fitted.margin = Object.assign({}, fitted.margin, { t: 76 });
        }
        if (fitted.showlegend && fitted.legend) {
            fitted.legend = Object.assign({}, fitted.legend, { y: -0.28, yanchor: "top" });
            fitted.margin = Object.assign({}, fitted.margin, { b: 110 });
            fitted.height = (fitted.height || 400) + 60;
        }
        return fitted;
    }

    for (var j = 0; j < plots.length; j++) {
        var node = plots[j];
        var spec = specFor(node.getAttribute("data-chart"));
        if (!spec) {
            continue;
        }
        Plotly.newPlot(node, spec.data, fitToWidth(spec.layout, node.offsetWidth), configFor(spec));
    }

    document.addEventListener("click", function (event) {
        var button = event.target.closest("[data-png]");
        if (!button) {
            return;
        }
        var id = button.getAttribute("data-png");
        var target = document.querySelector('[data-chart="' + id + '"]');
        var spec = specFor(id);
        if (!target || !spec) {
            return;
        }
        Plotly.downloadImage(target, {
            format: "png",
            scale: 2,
            filename: spec.filename,
            width: target.offsetWidth,
            height: spec.layout.height || 400
        });
    });
})();
