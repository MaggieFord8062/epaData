/*
 * nav.js: the navigation bar's flyout menus, search panel and phone menu. Works like the
 * navigation on apple.com:
 *   - hover (or keyboard focus) on "Explore" or "Data" opens its flyout; the page behind blurs
 *   - the magnifying glass (or "/" or Command/Ctrl + K) opens search with suggestions as you type
 *   - Escape, a click on the blurred page, or moving the pointer away closes everything
 * It also keeps the dashboard's section links in step with the page, and copies a page's link.
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

    // Chapter links (the dashboard's sections): the one being read is highlighted, and it stays in view
    var chapters = document.querySelector("[data-chapters]");
    if (chapters) {
        var links = Array.prototype.slice.call(chapters.querySelectorAll("a[href^='#']"));
        var sections = links.map(function (link) {
            return document.getElementById(link.getAttribute("href").slice(1));
        });
        var current = null;
        var mark = function (id) {
            if (id === current) {
                return;
            }
            current = id;
            links.forEach(function (link) {
                var active = link.getAttribute("href") === "#" + id;
                if (active) {
                    link.setAttribute("aria-current", "true");
                    var box = link.getBoundingClientRect();
                    var bar = chapters.firstElementChild;
                    var edge = bar.getBoundingClientRect();
                    if (box.left < edge.left || box.right > edge.right) {
                        bar.scrollLeft += box.left - edge.left - 16;
                    }
                } else {
                    link.removeAttribute("aria-current");
                }
            });
        };
        var update = function () {
            // the last section whose top has passed a line just under the bars
            var found = null;
            sections.forEach(function (section) {
                if (section && section.getBoundingClientRect().top <= 140) {
                    found = section.id;
                }
            });
            mark(found || (sections[0] && sections[0].id));
        };
        update();
        window.addEventListener("scroll", update, { passive: true });
        var smooth = !(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
        links.forEach(function (link) {
            link.addEventListener("click", function (event) {
                var target = document.getElementById(link.getAttribute("href").slice(1));
                if (!target) {
                    return;
                }
                event.preventDefault();
                target.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
                history.replaceState(null, "", link.getAttribute("href"));
            });
        });
    }

    // A hairline under the bar once the page scrolls beneath it
    var onScroll = function () {
        nav.classList.toggle("is-scrolled", window.scrollY > 4);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });

    // "Copy link": every choice on a page lives in its address, so the link reopens exactly this view
    Array.prototype.forEach.call(document.querySelectorAll("[data-copy-link]"), function (button) {
        var label = button.querySelector("[data-copy-text]");
        button.addEventListener("click", function () {
            var done = function (text) {
                if (label) {
                    label.textContent = text;
                }
                button.classList.add("is-done");
                setTimeout(function () {
                    if (label) {
                        label.textContent = "Copy link";
                    }
                    button.classList.remove("is-done");
                }, 1800);
            };
            var address = window.location.href.split("#")[0];
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(address).then(function () {
                    done("Link copied");
                }, function () {
                    window.prompt("Copy this link:", address);
                });
            } else {
                window.prompt("Copy this link:", address);
            }
        });
    });
})();
