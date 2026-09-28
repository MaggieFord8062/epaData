/*
 * picker.js
 * A type-ahead for choosing a facility by name, used by the Compare and History pages.
 *
 * attachFacilityPicker(input, onPick)
 *   input:  the text box the user types in
 *   onPick: called with { epa_facility_id, facility_name, state, units } when a facility is chosen
 */
function attachFacilityPicker(input, onPick) {
    const list = document.createElement("ul");
    list.className = "picker-list";
    list.hidden = true;
    input.insertAdjacentElement("afterend", list);

    let matches = [];
    let active = -1;
    let timer = null;

    function escapeHtml(text) {
        const replacements = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
        return String(text).replace(/[&<>"']/g, character => replacements[character]);
    }

    function close() {
        list.hidden = true;
        active = -1;
    }

    function highlight(index) {
        const items = list.querySelectorAll("li");
        items.forEach(item => {
            item.classList.remove("is-active");
        });
        active = Math.max(-1, Math.min(index, items.length - 1));
        if (active >= 0) {
            items[active].classList.add("is-active");
        }
    }

    function pick(index) {
        const match = matches[index];
        if (!match) {
            return;
        }
        input.value = "";
        close();
        onPick(match);
    }

    async function lookup() {
        const text = input.value.trim();
        if (!text) {
            close();
            return;
        }
        const response = await fetch(`/api/facilities?q=${encodeURIComponent(text)}`);
        matches = await response.json();

        if (matches.length === 0) {
            list.innerHTML = `<li class="picker-empty">No facility name contains "${escapeHtml(text)}"</li>`;
            list.hidden = false;
            active = -1;
            return;
        }

        list.innerHTML = matches.map((match, index) => {
            const units = `${match.units} unit${match.units === 1 ? "" : "s"}`;
            return `<li data-index="${index}">
                <span>${escapeHtml(match.facility_name)}</span>
                <span class="picker-meta">${escapeHtml(match.state || "")}, ${units}</span>
            </li>`;
        }).join("");
        list.hidden = false;
        highlight(0);
    }

    input.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(lookup, 120);
    });

    input.addEventListener("keydown", event => {
        if (list.hidden) {
            return;
        }
        if (event.key === "ArrowDown") {
            event.preventDefault();
            highlight(active + 1);
        } else if (event.key === "ArrowUp") {
            event.preventDefault();
            highlight(active - 1);
        } else if (event.key === "Enter") {
            event.preventDefault();
            pick(active);
        } else if (event.key === "Escape") {
            close();
        }
    });

    // mousedown instead of click, so it runs before the text box loses focus
    list.addEventListener("mousedown", event => {
        const item = event.target.closest("li[data-index]");
        if (!item) {
            return;
        }
        event.preventDefault();
        pick(Number(item.dataset.index));
    });

    input.addEventListener("blur", () => {
        setTimeout(close, 100);
    });
}