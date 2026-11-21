/*
 * epaData charts: draws every Plotly figure on the page from its JSON block
 * (<script type="application/json" id="spec-ID">) and brings the card around it to life, the way the
 * charts in Apple's Health and Stocks apps behave:
 *   - each card rises into view as you scroll to it, and its lines draw in and its bars grow
 *   - moving over a single-line chart shows that year in the big headline number, with a dot on the line
 *   - the 5Y / 10Y / 20Y / All buttons change the years shown
 *   - the legend chips hide and show their series
 *   - "PNG image" saves the chart with its title; "Reset zoom" appears after zooming in
 * The figures themselves are built in Python (dashboard.py, comparison.py, model_charts.py).
 */
(function () {
    "use strict";

    window.epaCharts = true;

    // Where the U.S. map outline is stored (static/vendor/topojson), so maps don't need the internet
    var script = document.currentScript;
    var topojsonURL = script ? script.getAttribute("data-topojson") : null;

    var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var touchOnly = window.matchMedia && window.matchMedia("(hover: none)").matches;
    var EASE = "cubic-bezier(0.28, 0.11, 0.32, 1)";
    var FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", Helvetica, Arial, sans-serif';

    var cards = Array.prototype.slice.call(document.querySelectorAll(".chart-card"));
    var specs = {};

    function specFor(id) {
        if (specs[id]) {
            return specs[id];
        }
        var block = document.getElementById("spec-" + id);
        if (!block) {
            return null;
        }
        specs[id] = JSON.parse(block.textContent);
        return specs[id];
    }

    function showMessage(node, message) {
        var paragraph = document.createElement("p");
        paragraph.className = "chart-empty";
        paragraph.textContent = message;
        node.style.minHeight = "0";
        node.appendChild(paragraph);
    }

    if (!window.Plotly) {
        cards.forEach(function (card) {
            card.classList.add("is-shown");
            var node = card.querySelector("[data-chart]");
            if (node) {
                showMessage(node, "The chart library (static/vendor/plotly-2.35.2.min.js) didn't load. "
                    + "The numbers are in the table below.");
            }
        });
        return;
    }

    // ---------- Numbers, written the same way as the page (analysis.format_compact) ----------

    function plain(value) {
        var size = Math.abs(value);
        if (size === 0) {
            return "0";
        }
        if (size >= 1000) {
            return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
        }
        if (size >= 100) {
            return value.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
        }
        if (size >= 1) {
            return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }
        return String(Number(value.toPrecision(4)));
    }

    function minus(text) {
        return text.replace("-", "−");
    }

    // 406123456 -> ["406", "million"]
    function compact(value) {
        var tiers = [[1e12, "trillion"], [1e9, "billion"], [1e6, "million"]];
        for (var i = 0; i < tiers.length; i++) {
            if (Math.abs(value) >= tiers[i][0]) {
                var shown = Number((value / tiers[i][0]).toPrecision(3));
                if (Math.abs(shown) >= 1000 && i > 0) {
                    return [minus(String(Number((value / tiers[i - 1][0]).toPrecision(3)))), tiers[i - 1][1]];
                }
                return [minus(String(shown)), tiers[i][1]];
            }
        }
        return [minus(plain(value)), ""];
    }

    function escapeHTML(text) {
        return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function yearStep(span) {
        return span <= 12 ? 1 : (span <= 24 ? 2 : 5);
    }

    // ---------- Drawing ----------

    function configFor(spec) {
        var config = {
            displaylogo: false,
            displayModeBar: false,
            responsive: true,
            scrollZoom: false,
            doubleClick: "reset",
            toImageButtonOptions: { format: "png", scale: 2, filename: spec.filename }
        };
        if (topojsonURL) {
            config.topojsonURL = topojsonURL;
        }
        return config;
    }

    // Phones: no room for names at the ends of lines (the legend above has them), and no drag-to-zoom,
    // so a finger on a chart scrolls the page
    function fitToWidth(layout, width) {
        var fitted = JSON.parse(JSON.stringify(layout));
        if (touchOnly) {
            fitted.dragmode = false;
            ["xaxis", "yaxis"].forEach(function (name) {
                if (fitted[name]) {
                    fitted[name].fixedrange = true;
                }
            });
        }
        if (width < 440 && fitted.annotations) {
            var before = fitted.annotations.length;
            // names at the ends of lines, and labels along the top edge (the legend or note has them)
            fitted.annotations = fitted.annotations.filter(function (note) {
                if (note.xshift) {
                    return note.xref === "x" && note.yref === "paper";
                }
                return !(note.yref === "paper" && note.y >= 1);
            });
            if (fitted.annotations.length < before && fitted.margin) {
                fitted.margin.r = 12;
            }
        }
        return fitted;
    }

    // Phones: heat maps drop the numbers written in their cells (tap a cell for its value), and color
    // keys and maps get the room they need
    function fitData(data, layout, width) {
        // A U.S. map is about twice as wide as it is tall: size the chart to the card so it has no empty bands
        if (layout.geo && width) {
            layout.height = Math.round(Math.max(240, width / 1.9 + 64));
        }
        if (window.innerWidth >= 735) {
            return data;
        }
        data.forEach(function (trace) {
            var bar = trace.colorbar || (trace.marker && trace.marker.colorbar);
            if (bar && bar.orientation === "h") {
                bar.len = 0.8;
                bar.nticks = 4;
            }
            if (trace.type === "heatmap") {
                layout.annotations = [];
                ["xaxis", "yaxis"].forEach(function (name) {
                    layout[name].tickfont = Object.assign({}, layout[name].tickfont, { size: 10 });
                });
                layout.xaxis.tickangle = -90;
                if (trace.colorbar) {
                    trace.colorbar.thickness = 6;
                }
            }
        });
        return data;
    }

    function draw(card) {
        var node = card.querySelector("[data-chart]");
        if (!node) {
            return Promise.resolve(null);
        }
        if (node.epaDrawing) {
            return node.epaDrawing;
        }
        var spec = specFor(node.getAttribute("data-chart"));
        if (!spec) {
            return Promise.resolve(null);
        }
        var layout = fitToWidth(spec.layout, node.offsetWidth);
        var data = fitData(JSON.parse(JSON.stringify(spec.data)), layout, node.offsetWidth);
        node.epaDrawing = Plotly.newPlot(node, data, layout, configFor(spec))
            .then(function () {
                node.style.minHeight = "";
                wire(card, node, spec);
                return node;
            });
        return node.epaDrawing;
    }

    function wire(card, node, spec) {
        if (spec.details || spec.detail_template || spec.explain) {
            details(card, node, spec);
        }
        if (spec.readout) {
            readout(card, node, spec);
        }
        if (spec.ranges) {
            ranges(card, node, spec);
        }
        if (spec.legend) {
            legend(card, node);
        }
        resetButton(card, node, spec);
    }

    // ---------- Scroll reveal and draw-in ----------

    function play(element, frames, options) {
        if (element.animate) {
            element.animate(frames, Object.assign({ fill: "backwards", easing: EASE }, options));
        }
    }

    function each(node, selector, callback) {
        Array.prototype.forEach.call(node.querySelectorAll(selector), callback);
    }

    function drawIn(node) {
        if (reduceMotion) {
            return;
        }
        var xa = node._fullLayout && node._fullLayout.xaxis;

        // Lines draw from left to right (dashed reference lines just fade in)
        each(node, ".scatterlayer .trace .js-line", function (path) {
            var dashed = path.style.strokeDasharray && path.style.strokeDasharray !== "none";
            var length = path.getTotalLength ? path.getTotalLength() : 0;
            if (dashed || !length) {
                play(path, [{ opacity: 0 }, { opacity: 1 }], { duration: 700, delay: 500 });
                return;
            }
            play(path, [
                { strokeDasharray: length + "px " + length + "px", strokeDashoffset: length + "px" },
                { strokeDasharray: length + "px " + length + "px", strokeDashoffset: "0px" }
            ], { duration: 1500, easing: "cubic-bezier(0.45, 0, 0.2, 1)" });
        });
        each(node, ".scatterlayer .trace .js-fill", function (path) {
            play(path, [{ opacity: 0 }, { opacity: 1 }], { duration: 1000, delay: 750 });
        });
        each(node, ".scatterlayer .trace .points path, .scatterlayer .trace .textpoint", function (point) {
            play(point, [{ opacity: 0 }, { opacity: 1 }], { duration: 500, delay: 1250 });
        });

        // Bars grow out of their baseline, one after another
        each(node, ".barlayer .trace", function (traceGroup, traceIndex) {
            var data = traceGroup.__data__;
            var trace = data && data[0] && data[0].trace;
            var horizontal = trace && trace.orientation === "h";
            var zero = horizontal && xa && xa.type !== "log" ? xa.l2p(0) : null;
            var bars = traceGroup.querySelectorAll(".point path");
            var stagger = Math.min(40, 600 / Math.max(bars.length, 1));
            Array.prototype.forEach.call(bars, function (bar, index) {
                var box = bar.getBBox();
                var origin = "center bottom";
                if (horizontal) {
                    origin = zero !== null && box.x + box.width / 2 < zero ? "right center" : "left center";
                }
                bar.style.transformBox = "fill-box";
                bar.style.transformOrigin = origin;
                play(bar, [{ transform: horizontal ? "scaleX(0)" : "scaleY(0)" },
                    { transform: horizontal ? "scaleX(1)" : "scaleY(1)" }],
                    { duration: 900, delay: traceIndex * 120 + index * stagger });
            });
        });
        each(node, ".barlayer .bartext", function (label) {
            play(label, [{ opacity: 0 }, { opacity: 1 }], { duration: 500, delay: 800 });
        });

        // Everything else fades in
        each(node, ".boxlayer .trace, .heatmaplayer image, .geo .choroplethlayer, .geo .scattergeolayer, "
            + ".gl-container canvas", function (layer) {
            play(layer, [{ opacity: 0 }, { opacity: 1 }], { duration: 900, delay: 150 });
        });
        each(node, ".annotation, .layer-above .shapelayer path, .colorbar", function (layer) {
            play(layer, [{ opacity: 0 }, { opacity: 1 }], { duration: 600, delay: 900 });
        });
    }

    function reveal(card) {
        card.classList.add("is-shown");
        draw(card).then(function (node) {
            if (node && node._fullLayout) {
                drawIn(node);
            }
        });
    }

    if ("IntersectionObserver" in window) {
        var watcher = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    watcher.unobserve(entry.target);
                    reveal(entry.target);
                }
            });
        }, { rootMargin: "0px 0px -6% 0px", threshold: 0.08 });
        cards.forEach(function (card) {
            watcher.observe(card);
        });
    } else {
        cards.forEach(reveal);
    }

    // Printing draws everything at once
    window.addEventListener("beforeprint", function () {
        cards.forEach(function (card) {
            card.classList.add("is-shown");
            draw(card);
        });
    });

    // ---------- The headline follows the pointer (Stocks-style scrubbing) ----------

    function readout(card, node, spec) {
        var box = card.querySelector("[data-readout]");
        var info = spec.readout;
        var trace = spec.data[info.trace];
        if (!box || !trace) {
            return;
        }
        var parts = {
            value: box.querySelector("[data-value]"),
            unit: box.querySelector("[data-unit]"),
            context: box.querySelector("[data-context]"),
            delta: box.querySelector("[data-delta]"),
            deltaText: box.querySelector("[data-delta-text]"),
            deltaWord: box.querySelector("[data-delta-word]"),
            deltaAfter: box.querySelector("[data-delta-after]")
        };
        var xs = trace.x;
        var ys = trace.y;
        var dot = document.createElement("span");
        dot.className = "chart-hover-dot";
        dot.style.setProperty("--dot", (trace.line && trace.line.color) || "#0071e3");
        dot.setAttribute("aria-hidden", "true");
        node.appendChild(dot);

        var state = { start: null };
        node.epaRange = state;

        // The year changes are measured from: the first one shown, but never one of the shaded early
        // years with too few units reporting (info.base is the first year with enough)
        function firstIndex() {
            var from = Math.max(state.start === null ? -Infinity : state.start, info.base || -Infinity);
            for (var i = 0; i < xs.length; i++) {
                if (ys[i] !== null && xs[i] >= from) {
                    return i;
                }
            }
            return -1;
        }

        function lastIndex() {
            for (var i = xs.length - 1; i >= 0; i--) {
                if (ys[i] !== null) {
                    return i;
                }
            }
            return -1;
        }

        function show(index, hovering) {
            if (index < 0) {
                return;
            }
            var words = compact(ys[index]);
            if (parts.value) {
                parts.value.textContent = words[0];
            }
            if (parts.unit) {
                parts.unit.textContent = (words[1] + " " + info.unit).trim();
            }
            if (parts.context) {
                var context = "In " + xs[index];
                var counts = trace.customdata;
                if (hovering && info.count && counts && counts[index]) {
                    context += " · " + Number(counts[index][0]).toLocaleString("en-US") + " " + info.count;
                }
                parts.context.textContent = context;
            }
            if (info.delta && parts.delta) {
                var base = firstIndex();
                var old = base >= 0 ? ys[base] : null;
                var visible = base >= 0 && index > base && old > 0;
                parts.delta.hidden = !visible;
                parts.deltaAfter.hidden = !visible;
                if (visible) {
                    var change = (ys[index] - old) / old * 100;
                    var direction = change >= 0.05 ? "up" : (change <= -0.05 ? "down" : "flat");
                    parts.delta.className = "chart-delta is-" + direction;
                    parts.deltaText.textContent = Math.abs(change).toLocaleString("en-US",
                        { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + "%";
                    parts.deltaWord.textContent = { up: "Up", down: "Down", flat: "About the same," }[direction];
                    parts.deltaAfter.textContent = "since " + xs[base];
                }
            }
        }

        node.epaReadout = function () {
            show(lastIndex(), false);
        };

        node.on("plotly_hover", function (event) {
            var point = (event.points || []).filter(function (item) {
                return item.curveNumber === info.trace;
            })[0];
            if (!point) {
                return;
            }
            show(point.pointIndex, true);
            var xa = point.xaxis;
            var ya = point.yaxis;
            var x = xa._offset + xa.l2p(xa.d2l(point.x));
            var y = ya._offset + ya.l2p(ya.d2l(point.y));
            dot.style.transform = "translate(" + x + "px, " + y + "px)";
            card.classList.add("is-scrubbing");
        });
        node.on("plotly_unhover", function () {
            card.classList.remove("is-scrubbing");
            show(lastIndex(), false);
        });
    }

    // ---------- 5Y / 10Y / 20Y / All ----------

    function yRangeFor(node, start, end) {
        var low = Infinity;
        var high = -Infinity;
        node.data.forEach(function (trace) {
            if (trace.visible === false || trace.visible === "legendonly" || !trace.x || !trace.y) {
                return;
            }
            for (var i = 0; i < trace.x.length; i++) {
                var y = trace.y[i];
                // the year just before the range is included too, since the line runs in from it
                if (y !== null && y !== undefined && trace.x[i] >= start - 1 && trace.x[i] <= end) {
                    low = Math.min(low, y);
                    high = Math.max(high, y);
                }
            }
        });
        if (!isFinite(low)) {
            return null;
        }
        var toZero = node.layout.yaxis && node.layout.yaxis.rangemode === "tozero";
        if (toZero) {
            low = Math.min(0, low);
            high = Math.max(0, high);
        }
        var pad = (high - low) * 0.08 || Math.abs(high) * 0.08 || 1;
        return [toZero && low === 0 ? 0 : low - pad, toZero && high === 0 ? 0 : high + pad];
    }

    function ranges(card, node, spec) {
        var group = card.querySelector("[data-ranges]");
        var trace = spec.data[spec.readout ? spec.readout.trace : 0];
        if (!group || !trace) {
            return;
        }
        var years = trace.x.filter(function (x, i) {
            return trace.y[i] !== null;
        });
        var first = years[0];
        var last = years[years.length - 1];

        group.addEventListener("click", function (event) {
            var button = event.target.closest("button[data-years]");
            if (!button || button.getAttribute("aria-pressed") === "true") {
                return;
            }
            Array.prototype.forEach.call(group.querySelectorAll("button"), function (other) {
                other.setAttribute("aria-pressed", other === button ? "true" : "false");
            });
            var count = Number(button.getAttribute("data-years"));
            var start = count ? Math.max(first, last - count + 1) : first;
            if (node.epaRange) {
                node.epaRange.start = count ? start : null;
            }
            var update = {
                "xaxis.range": [start - 0.4, last + 0.4],
                "xaxis.dtick": yearStep(last - start)
            };
            var yRange = yRangeFor(node, start, last);
            if (yRange) {
                update["yaxis.range"] = yRange;
            }
            node.epaInternal = true;
            Plotly.relayout(node, update).then(function () {
                node.epaInternal = false;
                if (node.epaReadout) {
                    node.epaReadout();
                }
                var reset = card.querySelector("[data-reset]");
                if (reset) {
                    reset.hidden = true;
                }
                if (!reduceMotion) {
                    drawIn(node);
                }
            });
        });
    }

    // ---------- Legend chips show and hide their series ----------

    function legend(card, node) {
        var keys = Array.prototype.slice.call(card.querySelectorAll("button.chart-key[data-group]"));
        keys.forEach(function (key) {
            key.addEventListener("click", function () {
                var group = key.getAttribute("data-group");
                var showing = key.getAttribute("aria-pressed") === "true";
                var on = keys.filter(function (other) {
                    return other.getAttribute("aria-pressed") === "true";
                });
                if (showing && on.length === 1) {
                    return;   // keep at least one series on the chart
                }
                var indices = [];
                node.data.forEach(function (trace, index) {
                    if (trace.legendgroup === group || trace.name === group) {
                        indices.push(index);
                    }
                });
                key.setAttribute("aria-pressed", showing ? "false" : "true");
                var layoutUpdate = {};
                (node.layout.annotations || []).forEach(function (note, index) {
                    if (note.text === "<b>" + group + "</b>") {
                        layoutUpdate["annotations[" + index + "].visible"] = !showing;
                    }
                });
                node.epaInternal = true;
                Plotly.update(node, { visible: !showing }, layoutUpdate, indices).then(function () {
                    node.epaInternal = false;
                });
            });
        });
    }

    // ---------- Zooming ----------

    function resetButton(card, node, spec) {
        var button = card.querySelector("[data-reset]");
        if (!button || !node._fullLayout || !node._fullLayout.xaxis || touchOnly) {
            return;
        }
        node.on("plotly_relayout", function (event) {
            if (node.epaInternal) {
                return;
            }
            var names = Object.keys(event);
            if (names.some(function (name) { return /^[xy]axis\.range/.test(name); })) {
                button.hidden = false;
            } else if (names.some(function (name) { return /autorange$/.test(name); })) {
                button.hidden = true;
            }
        });
        button.addEventListener("click", function () {
            var update = {};
            ["xaxis", "yaxis"].forEach(function (name) {
                var axis = spec.layout[name] || {};
                if (axis.range) {
                    update[name + ".range"] = axis.range.slice();
                } else {
                    update[name + ".autorange"] = axis.autorange || true;
                }
                if (axis.dtick !== undefined) {
                    update[name + ".dtick"] = axis.dtick;
                }
            });
            node.epaInternal = true;
            Plotly.relayout(node, update).then(function () {
                node.epaInternal = false;
                button.hidden = true;
                if (node.epaRange) {
                    node.epaRange.start = null;
                }
                var group = card.querySelector("[data-ranges]");
                if (group) {
                    var buttons = group.querySelectorAll("button");
                    Array.prototype.forEach.call(buttons, function (other, index) {
                        other.setAttribute("aria-pressed", index === buttons.length - 1 ? "true" : "false");
                    });
                }
                if (node.epaReadout) {
                    node.epaReadout();
                }
            });
        });
    }

    // ---------- Where a number comes from: the detail sheet under the chart ----------
    //
    // Selecting a point, bar, box, state or cell opens a sheet with its value, the calculation behind it
    // with the real numbers, facts about the records, and a link to those records in Explore. Most charts
    // carry their details from the server (spec.details, built by explain.py); the two with thousands
    // of points (the scatter plot and the facility map) carry a template, and the sheet is filled in here.

    function make(tag, className, text) {
        var element = document.createElement(tag);
        if (className) {
            element.className = className;
        }
        if (text !== undefined && text !== null && text !== "") {
            element.textContent = text;
        }
        return element;
    }

    // Numbers in calculations: commas from 1,000 up, otherwise 4 significant digits (explain.number)
    function precise(value) {
        if (value === null || value === undefined || isNaN(value)) {
            return "—";
        }
        var size = Math.abs(value);
        var text;
        if (size === 0) {
            return "0";
        }
        if (size >= 999.95) {
            text = value.toLocaleString("en-US", { maximumFractionDigits: 0 });
        } else if (size >= 1e-4) {
            text = value.toPrecision(4);
        } else {
            text = plain(value);
        }
        return minus(text);
    }

    function withUnit(value, unit) {
        return value === null || value === undefined ? "—" : (precise(value) + " " + (unit || "")).trim();
    }

    function signedPercent(value) {
        if (value === null || value === undefined || isNaN(value)) {
            return "—";
        }
        if (Math.abs(value) < 0.05) {
            return "0%";
        }
        return (value > 0 ? "+" : "−") + Math.abs(value).toLocaleString("en-US",
            { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + "%";
    }

    function plural(count, noun) {
        return Number(count).toLocaleString("en-US") + " " + noun + (Number(count) === 1 ? "" : "s");
    }

    function exploreLink(drill) {
        var holder = document.querySelector("[data-explore-base]");
        var url = new URL(holder ? holder.getAttribute("data-explore-base") : "/explore", window.location.origin);
        Object.keys(drill).forEach(function (key) {
            url.searchParams.set(key, drill[key]);
        });
        url.searchParams.delete("page");
        return url.pathname + url.search;
    }

    // Details built here, from a template and the point's own numbers
    function fromTemplate(spec, point) {
        var template = spec.detail_template;
        var data = point.customdata || [];
        if (template.kind === "record") {
            var year = data[2];
            var drill = {};
            if (data[0] !== null && data[0] !== undefined) {
                drill.epa_facility_id = data[0];
                if (data[1]) {
                    drill.epa_unit_id = data[1];
                }
                drill.reporting_year = year;
            }
            var words = compact(point.y);
            return {
                kicker: "One record · " + (point.data.name || ""),
                title: point.text || "",
                value: words[0], unit: (words[1] + " " + template.y.unit).trim(),
                summary: template.y.label + " and " + template.x.label.toLowerCase() + " as reported to EPA for this "
                    + "unit in " + year + ".",
                calc: [],
                facts: [[template.x.label, withUnit(point.x, template.x.unit)],
                    [template.y.label, withUnit(point.y, template.y.unit)],
                    ["Fuel family", point.data.name || "—"], ["Year", String(year)]],
                note: template.x.label + ": " + template.x.definition + " " + template.y.label + ": "
                    + template.y.definition,
                drill: drill, drill_label: "See this record in Explore"
            };
        }
        if (template.kind === "facility") {
            var records = data[1];
            var used = data[2];
            var value = point["marker.color"];
            var calc;
            if (template.ratio) {
                calc = [{ op: "", label: "Total " + template.num[0], value: withUnit(data[3], template.num[1]) }];
                if (template.scale) {
                    calc.push({ op: "×", label: template.scale[0].toLocaleString("en-US") + " " + template.scale[1],
                        value: "" });
                }
                calc.push({ op: "÷", label: "Total " + template.den[0], value: withUnit(data[4], template.den[1]) });
                calc.push({ op: "=", label: template.label, value: withUnit(value, template.unit), result: true });
            } else {
                calc = [{ op: "Σ", label: template.label + " of " + plural(used, "record") + ", added up", value: "" },
                    { op: "=", label: "Total", value: withUnit(value, template.unit), result: true }];
            }
            var parts = compact(value);
            var missing = records - used;
            return {
                kicker: "Facility · " + template.kicker,
                title: point.text || "",
                value: parts[0], unit: (parts[1] + " " + template.unit).trim(),
                summary: template.ratio
                    ? "The overall " + template.label + " of " + plural(used, "record") + ": their totals divided."
                    : "The " + template.label + " of " + plural(used, "record") + " added together.",
                calc: calc,
                facts: [["Facility ID", String(data[0])], ["Records", Number(records).toLocaleString("en-US")]],
                note: missing > 0 ? plural(missing, "record") + " left out because a value is missing"
                    + (template.ratio ? " or the denominator is 0." : ".") : "",
                drill: { epa_facility_id: data[0] },
                drill_label: "See " + (records === 1 ? "this record" : "these " + plural(records, "record")) + " in Explore"
            };
        }
        if (template.kind === "prediction") {
            var miss = point.y - point.x;
            var predicted = compact(point.y);
            return {
                kicker: template.model + " · " + template.year,
                title: data[0] || "",
                value: predicted[0], unit: ("predicted " + predicted[1] + " short tons").trim(),
                summary: "Predicted from this unit's inputs alone; the model never saw its " + template.year + " "
                    + template.target + ".",
                calc: [{ op: "", label: "Predicted", value: withUnit(point.y, "short tons") },
                    { op: "−", label: "Actual", value: withUnit(point.x, "short tons") },
                    { op: "=", label: "Miss", value: (miss > 0 ? "+" : "") + withUnit(miss, "short tons"), result: true },
                    { op: "÷", label: "Actual", value: withUnit(point.x, "short tons") },
                    { op: "=", label: "Miss in %", value: signedPercent(data[1]), result: true }],
                facts: [["Fuel family", point.data.name || "—"], ["Unit type", data[5] || "—"],
                    ["Gross load", withUnit(data[2], "MWh")], ["Heat input", withUnit(data[3], "mmBtu")],
                    ["Operating time", withUnit(data[4], "hours")]],
                note: miss > 0 ? "Above the dashed line: the model predicted too much."
                    : "Below the dashed line: the model predicted too little.",
                drill: {}
            };
        }
        return null;
    }

    // The impact charts carry their worked calculation as lines of text (traci.calculation_lines)
    function fromLines(point) {
        var data = point.customdata;
        if (!Array.isArray(data)) {
            return null;
        }
        var lines = data[data.length - 1];
        if (!Array.isArray(lines) || lines.length === 0) {
            return null;
        }
        return {
            kicker: "Worked calculation", title: lines[0], value: "", unit: "",
            summary: typeof data[0] === "string" ? data[0] : "",
            calc: lines.slice(1).map(function (line) {
                return { op: "", label: line, value: "", line: true };
            }),
            facts: [], note: "", drill: {}
        };
    }

    function detailFor(spec, point) {
        if (spec.details) {
            var key;
            if (spec.detail_key === "x") {
                key = String(point.x);
            } else if (spec.detail_key === "yx") {
                key = point.y + "|" + point.x;
            } else {
                key = point.curveNumber + ":" + (point.pointNumber !== undefined ? point.pointNumber : point.pointIndex);
            }
            if (spec.details[key]) {
                return spec.details[key];
            }
        }
        if (spec.detail_template) {
            return fromTemplate(spec, point);
        }
        if (spec.explain) {
            return fromLines(point);
        }
        return null;
    }

    function section(heading) {
        var block = make("section", "detail-section");
        block.appendChild(make("h5", "detail-heading", heading));
        return block;
    }

    function renderDetail(card, detail) {
        var sheet = card.querySelector(".chart-detail");
        if (!sheet) {
            return;
        }
        sheet.textContent = "";
        var head = make("div", "detail-head");
        var titles = make("div", "detail-titles");
        if (detail.kicker) {
            titles.appendChild(make("p", "detail-kicker", detail.kicker));
        }
        titles.appendChild(make("h4", "detail-title", detail.title));
        head.appendChild(titles);
        var close = make("button", "detail-close");
        close.type = "button";
        close.setAttribute("aria-label", "Close");
        close.innerHTML = '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M1.5 1.5l9 9m0-9l-9 9" '
            + 'stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';
        head.appendChild(close);
        sheet.appendChild(head);

        if (detail.value) {
            var figure = make("p", "detail-figure");
            figure.appendChild(make("span", "detail-value", detail.value));
            if (detail.unit) {
                figure.appendChild(make("span", "detail-unit", detail.unit));
            }
            sheet.appendChild(figure);
        }
        if (detail.summary) {
            sheet.appendChild(make("p", "detail-summary", detail.summary));
        }

        var body = make("div", "detail-body");
        if (detail.calc && detail.calc.length) {
            var calcBlock = section("How it’s calculated");
            var receipt = make("div", "detail-receipt");
            detail.calc.forEach(function (row) {
                var line = make("div", "calc-row" + (row.result ? " is-result" : "") + (row.line ? " is-line" : ""));
                line.appendChild(make("span", "calc-op", row.op || ""));
                line.appendChild(make("span", "calc-label", row.label));
                line.appendChild(make("span", "calc-value", row.value || ""));
                receipt.appendChild(line);
            });
            calcBlock.appendChild(receipt);
            body.appendChild(calcBlock);
        }
        if (detail.facts && detail.facts.length) {
            var factBlock = section("Details");
            var list = make("dl", "detail-facts");
            detail.facts.forEach(function (fact) {
                var row = make("div", "fact-row");
                row.appendChild(make("dt", "", fact[0]));
                row.appendChild(make("dd", "", fact[1]));
                list.appendChild(row);
            });
            factBlock.appendChild(list);
            body.appendChild(factBlock);
        }
        if (body.children.length) {
            sheet.appendChild(body);
        }
        if (detail.note) {
            sheet.appendChild(make("p", "detail-note", detail.note));
        }
        if (detail.drill && Object.keys(detail.drill).length) {
            var link = make("a", "detail-link", detail.drill_label || "See these records in Explore");
            link.href = exploreLink(detail.drill);
            sheet.appendChild(link);
        }

        var opening = sheet.hidden;
        sheet.hidden = false;
        card.classList.add("has-detail");
        if (opening && !reduceMotion) {
            play(sheet, [{ opacity: 0, transform: "translateY(12px)" }, { opacity: 1, transform: "none" }],
                { duration: 420 });
        } else if (!reduceMotion) {
            play(sheet, [{ opacity: 0.4 }, { opacity: 1 }], { duration: 260 });
        }
        var box = sheet.getBoundingClientRect();
        if (box.bottom > window.innerHeight || box.top < 0) {
            sheet.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "nearest" });
        }
    }

    // The selected bar, dot or state stays bright and the rest dim, as in Apple's charts
    function highlight(node, point) {
        var selectable = { bar: true, scatter: true, scattergl: true, choropleth: true, scattergeo: true };
        var update = [];
        var indices = [];
        node.data.forEach(function (trace, index) {
            var markers = trace.type !== "scatter" || /markers/.test(trace.mode || "");
            if (!selectable[trace.type] || !markers || trace.hoverinfo === "skip") {
                return;
            }
            indices.push(index);
            update.push(index === point.curveNumber ? [point.pointNumber] : []);
        });
        if (!indices.length || indices.indexOf(point.curveNumber) < 0) {
            return false;
        }
        // The selected mark turns Apple blue; everything else fades back
        var style = { selectedpoints: update };
        var colored = indices.filter(function (index) {
            return node.data[index].type !== "choropleth";
        });
        node.epaInternal = true;
        Plotly.restyle(node, style, indices).then(function () {
            return colored.length ? Plotly.restyle(node, { "selected.marker.color": "#0071e3",
                "unselected.marker.opacity": 0.28 }, colored) : null;
        }).then(function () {
            node.epaInternal = false;
        });
        node.epaSelected = indices;
        return true;
    }

    function clearHighlight(node) {
        if (!node.epaSelected) {
            return;
        }
        var indices = node.epaSelected;
        node.epaSelected = null;
        node.epaInternal = true;
        Plotly.restyle(node, { selectedpoints: indices.map(function () { return null; }) }, indices).then(function () {
            node.epaInternal = false;
        });
    }

    function pin(card, node, point) {
        var dot = card.querySelector(".chart-pin-dot");
        if (!dot) {
            dot = make("span", "chart-pin-dot");
            dot.setAttribute("aria-hidden", "true");
            node.appendChild(dot);
        }
        var xa = point.xaxis;
        var ya = point.yaxis;
        if (!xa || !ya || point.y === undefined) {
            dot.hidden = true;
            return;
        }
        var color = (point.data.line && point.data.line.color) || (point.data.marker && point.data.marker.color) || "#0071e3";
        dot.style.setProperty("--dot", typeof color === "string" ? color : "#0071e3");
        dot.style.transform = "translate(" + (xa._offset + xa.l2p(xa.d2l(point.x))) + "px, "
            + (ya._offset + ya.l2p(ya.d2l(point.y))) + "px)";
        dot.hidden = false;
    }

    function closeDetail(card, node) {
        var sheet = card.querySelector(".chart-detail");
        if (sheet) {
            sheet.hidden = true;
        }
        card.classList.remove("has-detail");
        var dot = card.querySelector(".chart-pin-dot");
        if (dot) {
            dot.hidden = true;
        }
        clearHighlight(node);
    }

    function details(card, node, spec) {
        node.on("plotly_click", function (event) {
            var points = (event.points || []).filter(function (item) {
                return item.data && item.data.hoverinfo !== "skip";
            });
            var point = points[0];
            if (!point) {
                return;
            }
            // Several lines share the clicked year: take the one nearest the pointer
            if (points.length > 1 && event.event && point.yaxis) {
                var top = node.getBoundingClientRect().top;
                var distance = function (item) {
                    var ya = item.yaxis;
                    return Math.abs(top + ya._offset + ya.l2p(ya.d2l(item.y)) - event.event.clientY);
                };
                points.sort(function (one, two) {
                    return distance(one) - distance(two);
                });
                point = points[0];
            }
            var detail = detailFor(spec, point);
            if (!detail) {
                return;
            }
            renderDetail(card, detail);
            var isLine = point.data.type === "scatter" && !/markers/.test(point.data.mode || "");
            if (isLine) {
                clearHighlight(node);
                pin(card, node, point);
            } else {
                var dot = card.querySelector(".chart-pin-dot");
                if (dot) {
                    dot.hidden = true;
                }
                highlight(node, point);
            }
        });
        card.addEventListener("click", function (event) {
            if (event.target.closest(".detail-close")) {
                closeDetail(card, node);
            }
        });
        card.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && card.classList.contains("has-detail")) {
                closeDetail(card, node);
            }
        });
        node.on("plotly_relayout", function () {
            if (!node.epaInternal) {
                var dot = card.querySelector(".chart-pin-dot");
                if (dot) {
                    dot.hidden = true;
                }
            }
        });
    }

    // ---------- About this chart ----------

    document.addEventListener("click", function (event) {
        var button = event.target.closest("[data-about]");
        if (!button) {
            return;
        }
        var panel = document.getElementById("about-" + button.getAttribute("data-about"));
        if (!panel) {
            return;
        }
        var open = panel.hidden;
        panel.hidden = !open;
        button.setAttribute("aria-expanded", open ? "true" : "false");
        if (open && !reduceMotion) {
            play(panel, [{ opacity: 0, transform: "translateY(-6px)" }, { opacity: 1, transform: "none" }],
                { duration: 360 });
        }
    });

    // ---------- PNG image, with the title and headline written into it ----------

    function headlineText(card) {
        var box = card.querySelector("[data-readout]");
        if (!box) {
            return "";
        }
        function text(selector) {
            var part = box.querySelector(selector);
            return part && !part.hidden ? part.textContent.replace(/\s+/g, " ").trim() : "";
        }
        var bits = [[text("[data-value]"), text("[data-unit]")].join(" ").trim(), text("[data-context]")];
        if (text("[data-delta-text]") && !box.querySelector("[data-delta]").hidden) {
            bits.push((text("[data-delta-word]").replace(",", "").toLowerCase() + " " + text("[data-delta-text]")
                + " " + text("[data-delta-after]")).trim());
        }
        return bits.filter(Boolean).join("  \u00b7  ");
    }

    function savePNG(card, node, spec) {
        var layout = JSON.parse(JSON.stringify(node.layout));
        var subtitle = headlineText(card);
        var extra = subtitle ? 66 : 46;
        layout.title = {
            text: "<b>" + escapeHTML(spec.title) + "</b>"
                + (subtitle ? "<br><span style=\"font-size:13px;color:#6e6e73\">" + escapeHTML(subtitle) + "</span>" : ""),
            x: 0, xref: "paper", xanchor: "left", y: 1, yref: "container", yanchor: "top", pad: { t: 16 },
            font: { family: FONT, size: 17, color: "#1d1d1f" }
        };
        var named = node.data.filter(function (trace) {
            return trace.name && trace.showlegend !== false && trace.visible !== false;
        });
        if (spec.legend && named.length > 1) {
            layout.showlegend = true;
            layout.legend = Object.assign({}, layout.legend, { orientation: "h", x: 0, y: 1.02, yanchor: "bottom" });
            extra += 30;
        }
        var margin = layout.margin || {};
        layout.margin = Object.assign({}, margin, {
            t: (margin.t || 0) + extra,
            l: Math.max(margin.l || 0, 24),
            r: Math.max(margin.r || 0, 24),
            b: Math.max(margin.b || 0, 16)
        });
        extra += Math.max(0, 16 - (margin.b || 0));
        layout.height = (node._fullLayout ? node._fullLayout.height : spec.layout.height || 380) + extra;
        Plotly.toImage({ data: JSON.parse(JSON.stringify(node.data)), layout: layout, config: configFor(spec) },
            { format: "png", scale: 2, height: layout.height,
                width: (node.offsetWidth || 900) + layout.margin.l - (margin.l || 0) + layout.margin.r - (margin.r || 0) })
            .then(function (url) {
            var link = document.createElement("a");
            link.href = url;
            link.download = spec.filename + ".png";
            document.body.appendChild(link);
            link.click();
            link.remove();
        });
    }

    document.addEventListener("click", function (event) {
        var button = event.target.closest("[data-png]");
        if (!button) {
            return;
        }
        var card = button.closest(".chart-card");
        var spec = specFor(button.getAttribute("data-png"));
        if (!card || !spec) {
            return;
        }
        draw(card).then(function (node) {
            if (node && node.data) {
                savePNG(card, node, spec);
            }
        });
    });
})();
