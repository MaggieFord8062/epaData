/*
 * touches.js: small things that make the pages nicer to use.
 *   - Tables marked data-sortable (every chart's "Show the numbers") sort when a heading is clicked:
 *     numbers highest first, then lowest first, then back to the original order; text A to Z first.
 *     Blank values always stay at the bottom.
 *   - Numbers in a [data-count-up] row count up from zero the first time they scroll into view,
 *     unless the visitor has asked for reduced motion.
 */
(function () {
    "use strict";

    var each = function (list, callback) {
        Array.prototype.forEach.call(list, callback);
    };

    // ---------- Sortable tables ----------

    function numberIn(cell) {
        var raw = cell ? cell.getAttribute("data-value") : null;
        if (raw === null || raw === "" || isNaN(Number(raw))) {
            return null;
        }
        return Number(raw);
    }

    function textIn(cell) {
        return cell ? cell.textContent.trim() : "";
    }

    function sortable(table) {
        var head = table.tHead && table.tHead.rows[0];
        var body = table.tBodies[0];
        if (!head || !body || body.rows.length < 2) {
            return;
        }
        var original = Array.prototype.slice.call(body.rows);
        each(head.cells, function (th, column) {
            var numeric = original.some(function (row) {
                return row.cells[column] && row.cells[column].hasAttribute("data-value");
            });
            var first = numeric ? "descending" : "ascending";
            var second = numeric ? "ascending" : "descending";
            if (numeric) {
                th.classList.add("num");
            }
            var button = document.createElement("button");
            button.type = "button";
            button.className = "th-sort";
            button.title = numeric ? "Sort, highest first" : "Sort, A to Z";
            while (th.firstChild) {
                button.appendChild(th.firstChild);
            }
            th.appendChild(button);
            th.setAttribute("aria-sort", "none");

            button.addEventListener("click", function () {
                var now = th.getAttribute("aria-sort");
                var next = now === "none" ? first : now === first ? second : "none";
                each(head.cells, function (other) {
                    other.setAttribute("aria-sort", "none");
                });
                th.setAttribute("aria-sort", next);
                var rows = original.slice();
                if (next !== "none") {
                    var sign = next === "ascending" ? 1 : -1;
                    rows.sort(function (a, b) {
                        if (!numeric) {
                            return sign * textIn(a.cells[column]).localeCompare(textIn(b.cells[column]), undefined,
                                                                               { numeric: true, sensitivity: "base" });
                        }
                        var x = numberIn(a.cells[column]);
                        var y = numberIn(b.cells[column]);
                        if (x === null || y === null) {
                            return (x === null) - (y === null);   // blanks last either way
                        }
                        return sign * (x - y);
                    });
                }
                rows.forEach(function (row) {
                    body.appendChild(row);
                });
            });
        });
    }

    each(document.querySelectorAll("table[data-sortable]"), sortable);

    // ---------- Numbers that count up ----------

    var still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function withCommas(text) {
        var parts = text.split(".");
        parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
        return parts.join(".");
    }

    function countUp(value) {
        var node = value.firstChild;
        if (!node || node.nodeType !== 3) {
            return;
        }
        var final = node.nodeValue;
        var match = /^(\s*)(\d[\d,]*(?:\.\d+)?)([\s\S]*)$/.exec(final);
        if (!match) {
            return;
        }
        var target = Number(match[2].replace(/,/g, ""));
        if (!isFinite(target) || target <= 0) {
            return;
        }
        var decimals = (match[2].split(".")[1] || "").length;
        var commas = match[2].indexOf(",") >= 0;
        var show = function (amount) {
            var text = amount.toFixed(decimals);
            node.nodeValue = match[1] + (commas ? withCommas(text) : text) + match[3];
        };
        var duration = 1100;
        var start = null;
        var step = function (time) {
            start = start === null ? time : start;
            var progress = Math.min(1, (time - start) / duration);
            if (progress >= 1) {
                node.nodeValue = final;
                return;
            }
            show(target * (1 - Math.pow(1 - progress, 3)));   // ease out
            window.requestAnimationFrame(step);
        };
        show(0);
        window.requestAnimationFrame(step);
    }

    var rows = document.querySelectorAll("[data-count-up]");
    if (rows.length && !still && "IntersectionObserver" in window) {
        var watcher = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    watcher.unobserve(entry.target);
                    each(entry.target.querySelectorAll(".value"), countUp);
                }
            });
        }, { threshold: 0.5 });
        each(rows, function (row) {
            watcher.observe(row);
        });
    }
})();
