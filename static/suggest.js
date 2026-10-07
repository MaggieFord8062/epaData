/*
 * suggest.js
 * Suggestions under a search box while typing: ready-made searches and facilities.
 * Used by the Explore page's search bar and the search button in the top bar.
 *
 * attachSuggest(input, list)
 *   input: the text box
 *   list:  an empty <ul class="suggest"> to fill
 * Pressing Enter with nothing highlighted leaves the box's form to submit normally.
 */
function attachSuggest(input, list) {
    let active = -1;
    let timer = null;

    function escapeHtml(text) {
        const replacements = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
        return String(text).replace(/[&<>"']/g, character => replacements[character]);
    }

    function links() {
        return Array.from(list.querySelectorAll("a"));
    }

    function close() {
        list.hidden = true;
        active = -1;
    }

    function highlight(index) {
        const items = links();
        items.forEach(item => {
            item.classList.remove("is-active");
        });
        active = Math.max(-1, Math.min(index, items.length - 1));
        if (active >= 0) {
            items[active].classList.add("is-active");
        }
    }

    async function lookup() {
        const text = input.value.trim();
        if (!text) {
            close();
            return;
        }
        const response = await fetch(`/api/suggest?q=${encodeURIComponent(text)}`);
        const data = await response.json();

        const parts = [];
        if (data.searches.length > 0) {
            parts.push('<li class="group">Searches</li>');
            data.searches.forEach(search => {
                parts.push(`<li><a href="/explore?q=${encodeURIComponent(search)}">${escapeHtml(search)}</a></li>`);
            });
        }
        if (data.facilities.length > 0) {
            parts.push('<li class="group">Facilities</li>');
            data.facilities.forEach(facility => {
                parts.push(`<li><a href="/facility/${facility.id}">${escapeHtml(facility.name)}<span class="meta">${escapeHtml(facility.state || "")}</span></a></li>`);
            });
        }
        list.innerHTML = parts.join("");
        list.hidden = parts.length === 0;
        active = -1;
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
        } else if (event.key === "Enter" && active >= 0) {
            event.preventDefault();
            window.location = links()[active].href;
        } else if (event.key === "Escape") {
            close();
        }
    });

    input.addEventListener("blur", () => {
        setTimeout(close, 150);
    });
}