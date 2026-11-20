/*
 * nav.js: the global nav's flyout menus, search panel and phone menu, and the local nav's
 * menu on small screens. Works like the navigation on apple.com:
 *   - hover (or keyboard focus) on "Explore" or "Data" opens its flyout; the page behind blurs
 *   - the magnifying glass (or Command/Ctrl + K) opens search with suggestions as you type
 *   - Escape, a click on the blurred page, or moving the pointer away closes everything
 */
(function () {
    "use strict";

    var nav = document.getElementById("gn");
    var curtain = document.getElementById("gn-curtain");
    if (!nav || !curtain) {
        return;
    }
    var searchButton = document.getElementById("gn-search-open");
    var searchInput = document.getElementById("gn-search-input");
    var menuButton = document.getElementById("gn-menu-open");
    var flyoutItems = Array.prototype.slice.call(nav.querySelectorAll(".gn-item.has-flyout"));
    var closeTimer = null;

    function setCurtain() {
        var open = nav.querySelector(".gn-item.is-open") || nav.classList.contains("is-searching")
            || nav.classList.contains("is-menu");
        curtain.classList.toggle("is-visible", Boolean(open));
        nav.classList.toggle("is-open", Boolean(nav.querySelector(".gn-item.is-open")));
    }

    function closeFlyouts() {
        flyoutItems.forEach(function (item) {
            item.classList.remove("is-open");
            var link = item.querySelector(".gn-link");
            if (link) {
                link.setAttribute("aria-expanded", "false");
            }
        });
        setCurtain();
    }

    function openFlyout(item) {
        clearTimeout(closeTimer);
        closeSearch();
        flyoutItems.forEach(function (other) {
            if (other !== item) {
                other.classList.remove("is-open");
            }
        });
        item.classList.add("is-open");
        item.querySelector(".gn-link").setAttribute("aria-expanded", "true");
        setCurtain();
    }

    function openSearch() {
        closeFlyouts();
        closeMenu();
        nav.classList.add("is-searching");
        searchButton.setAttribute("aria-expanded", "true");
        setCurtain();
        setTimeout(function () {
            searchInput.focus();
        }, 60);
    }

    function closeSearch() {
        if (!nav.classList.contains("is-searching")) {
            return;
        }
        nav.classList.remove("is-searching");
        searchButton.setAttribute("aria-expanded", "false");
        setCurtain();
    }

    function closeMenu() {
        if (!nav.classList.contains("is-menu")) {
            return;
        }
        nav.classList.remove("is-menu");
        menuButton.setAttribute("aria-expanded", "false");
        document.body.style.overflow = "";
        setCurtain();
    }

    function closeAll() {
        closeFlyouts();
        closeSearch();
        closeMenu();
    }

    var hoverCapable = window.matchMedia && window.matchMedia("(hover: hover)").matches;

    flyoutItems.forEach(function (item) {
        if (hoverCapable) {
            item.addEventListener("mouseenter", function () {
                openFlyout(item);
            });
        }
        item.addEventListener("focusin", function () {
            openFlyout(item);
        });
    });

    // Moving to a top-level item without a flyout closes the open one
    Array.prototype.forEach.call(nav.querySelectorAll(".gn-item:not(.has-flyout)"), function (item) {
        item.addEventListener("mouseenter", function () {
            if (nav.querySelector(".gn-item.is-open")) {
                closeFlyouts();
            }
        });
        item.addEventListener("focusin", closeFlyouts);
    });

    nav.addEventListener("mouseleave", function () {
        closeTimer = setTimeout(closeFlyouts, 120);
    });
    nav.addEventListener("mouseenter", function () {
        clearTimeout(closeTimer);
    });

    curtain.addEventListener("click", closeAll);

    searchButton.addEventListener("click", function () {
        if (nav.classList.contains("is-searching")) {
            closeSearch();
        } else {
            openSearch();
        }
    });

    menuButton.addEventListener("click", function () {
        if (nav.classList.contains("is-menu")) {
            closeMenu();
            return;
        }
        closeFlyouts();
        closeSearch();
        window.scrollTo(0, 0);
        nav.classList.add("is-menu");
        menuButton.setAttribute("aria-expanded", "true");
        document.body.style.overflow = "hidden";
        setCurtain();
    });

    document.addEventListener("keydown", function (event) {
        if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
            event.preventDefault();
            openSearch();
        } else if (event.key === "Escape") {
            closeAll();
        }
    });

    if (typeof attachSuggest === "function") {
        attachSuggest(searchInput, document.getElementById("gn-search-results"));
    }

    // Local nav: on small screens the page links fold into a menu under the title
    var localNav = document.getElementById("ln");
    var localToggle = document.getElementById("ln-toggle");
    if (localNav && localToggle) {
        localToggle.addEventListener("click", function () {
            var open = !localNav.classList.contains("is-open");
            localNav.classList.toggle("is-open", open);
            localToggle.setAttribute("aria-expanded", open ? "true" : "false");
        });
        document.addEventListener("click", function (event) {
            if (localNav.classList.contains("is-open") && !localNav.contains(event.target)) {
                localNav.classList.remove("is-open");
                localToggle.setAttribute("aria-expanded", "false");
            }
        });
    }
})();
