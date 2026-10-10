(() => {
    const slider = document.querySelector("[data-forecast-slider]");
    if (!slider) return;

    const slides = Array.from(slider.querySelectorAll("[data-slide]"));
    const previousButton = document.querySelector("[data-slider-prev]");
    const nextButton = document.querySelector("[data-slider-next]");
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (!slides.length) return;

    if (slides.length < 2) {
        previousButton?.setAttribute("hidden", "");
        nextButton?.setAttribute("hidden", "");
    }

    let activeIndex = 0;
    let timer = null;

    const show = (index) => {
        activeIndex = (index + slides.length) % slides.length;
        slides.forEach((slide, i) => {
            const active = i === activeIndex;
            slide.classList.toggle("is-active", active);

            const preview = slide.querySelector("[data-slide-select]");
            const feature = slide.querySelector(".forecast-vertical-feature");
            if (preview) {
                if (active && preview === document.activeElement) preview.blur();
                preview.tabIndex = active ? -1 : 0;
                preview.setAttribute("aria-hidden", String(active));
            }
            if (feature) {
                feature.inert = !active;
                feature.setAttribute("aria-hidden", String(!active));
            }
        });
    };

    const stopAutoplay = () => {
        if (timer !== null) window.clearInterval(timer);
        timer = null;
    };

    const startAutoplay = () => {
        stopAutoplay();
        if (slides.length < 2 || reducedMotion.matches || document.hidden ||
            slider.matches(":hover") || slider.contains(document.activeElement)) return;
        timer = window.setInterval(() => show(activeIndex + 1), 5600);
    };

    const select = (index) => {
        show(index);
        startAutoplay();
    };

    slider.addEventListener("click", (event) => {
        const preview = event.target.closest("[data-slide-select]");
        if (preview) select(Number(preview.dataset.slideSelect || 0));
    });
    previousButton?.addEventListener("click", () => select(activeIndex - 1));
    nextButton?.addEventListener("click", () => select(activeIndex + 1));
    slider.addEventListener("mouseenter", stopAutoplay);
    slider.addEventListener("mouseleave", startAutoplay);
    slider.addEventListener("focusin", stopAutoplay);
    slider.addEventListener("focusout", () => window.requestAnimationFrame(startAutoplay));
    document.addEventListener("visibilitychange", startAutoplay);
    reducedMotion.addEventListener?.("change", startAutoplay);

    slider.querySelectorAll("[data-starts-at]").forEach((node) => {
        const timestamp = Date.parse(node.dataset.startsAt);
        if (Number.isNaN(timestamp)) return;
        const minutes = Math.ceil((timestamp - Date.now()) / 60000);
        if (minutes <= 0) return;
        const hours = Math.floor(minutes / 60);
        const remainder = minutes % 60;
        node.textContent = hours
            ? `Старт через ${hours} ч ${remainder} мин`
            : `Старт через ${remainder} мин`;
        node.hidden = false;
    });

    show(0);
    startAutoplay();
})();

(() => {
    const matchesSection = document.querySelector(".home-important-matches");
    if (!matchesSection) return;

    matchesSection.addEventListener("click", (event) => {
        const option = event.target.closest("[data-bet-option]");
        if (!option || option.disabled) return;

        const card = option.closest("[data-match-card]");
        const matchLink = card?.querySelector(".home-match-main, .match-card-main");
        if (!matchLink?.href) return;

        window.location.assign(matchLink.href);
    });
})();

(() => {
    const sliders = document.querySelectorAll("[data-home-card-slider]");
    if (!sliders.length) return;

    sliders.forEach((slider) => {
        const windowNode = slider.querySelector("[data-home-card-window]");
        const track = slider.querySelector("[data-home-card-track]");
        const previousButton = slider.querySelector("[data-home-card-prev]");
        const nextButton = slider.querySelector("[data-home-card-next]");
        const dotsNode = slider.querySelector("[data-home-card-dots]");
        if (!windowNode || !track) return;

        const allCards = Array.from(track.children);
        let cards = [];

        let pages = [];
        const scrollNode = track;

        const cardLeft = (card) => card.offsetLeft - track.offsetLeft;

        const getGap = () => {
            const styles = window.getComputedStyle(track);
            return Number.parseFloat(styles.columnGap || styles.gap || "0") || 0;
        };

        const buildPages = () => {
            cards = allCards.filter((card) => window.getComputedStyle(card).display !== "none");
            if (cards.length < 2) {
                pages = [];
                dotsNode?.replaceChildren();
                previousButton?.setAttribute("disabled", "");
                nextButton?.setAttribute("disabled", "");
                return;
            }
            const cardWidth = cards[0]?.getBoundingClientRect().width || 1;
            const perPage = Math.max(1, Math.floor((scrollNode.clientWidth + getGap()) / (cardWidth + getGap())));
            pages = [];
            for (let index = 0; index < cards.length; index += perPage) pages.push(index);

            if (dotsNode) {
                dotsNode.innerHTML = pages.map((_, index) => (
                    `<button type="button" data-home-card-dot="${index}" aria-label="Страница ${index + 1}"></button>`
                )).join("");
            }
        };

        const activePage = () => {
            const current = scrollNode.scrollLeft;
            let active = 0;
            pages.forEach((cardIndex, pageIndex) => {
                if (cardLeft(cards[cardIndex]) - 4 <= current) active = pageIndex;
            });
            return active;
        };

        const render = () => {
            if (!pages.length) return;
            const active = activePage();
            previousButton?.toggleAttribute("disabled", active <= 0);
            nextButton?.toggleAttribute("disabled", active >= pages.length - 1);
            dotsNode?.querySelectorAll("button").forEach((dot, index) => {
                dot.classList.toggle("is-active", index === active);
            });
        };

        const scrollToPage = (pageIndex) => {
            if (!pages.length) return;
            const card = cards[pages[Math.max(0, Math.min(pageIndex, pages.length - 1))]];
            if (!card) return;
            scrollNode.scrollTo({ left: cardLeft(card), behavior: "smooth" });
        };

        previousButton?.addEventListener("click", () => scrollToPage(activePage() - 1));
        nextButton?.addEventListener("click", () => scrollToPage(activePage() + 1));
        dotsNode?.addEventListener("click", (event) => {
            const dot = event.target.closest("[data-home-card-dot]");
            if (dot) scrollToPage(Number(dot.dataset.homeCardDot || 0));
        });
        scrollNode.addEventListener("scroll", () => window.requestAnimationFrame(render), { passive: true });
        window.addEventListener("resize", () => {
            buildPages();
            render();
        });

        buildPages();
        render();
    });
})();

(() => {
    const expertRows = document.querySelectorAll(".experts-card .expert-row");
    if (!expertRows.length) return;

    expertRows.forEach((row) => {
        const usernameNode = row.querySelector(".expert-copy > span");
        const username = usernameNode?.textContent.trim().replace(/^@/, "");
        if (!username) return;

        const link = document.createElement("a");
        link.className = row.className;
        link.href = `/experts/${encodeURIComponent(username)}/`;
        link.setAttribute("aria-label", `Открыть профиль ${username}`);
        link.style.color = "inherit";
        link.style.textDecoration = "none";

        while (row.firstChild) {
            link.appendChild(row.firstChild);
        }
        row.replaceWith(link);
    });
})();

(() => {
    // "Показать ещё" opens the rest of the high-odds list on phones.
    const button = document.querySelector("[data-home-mobile-best-show]");
    if (!button) return;
    button.addEventListener("click", () => {
        document.querySelectorAll("[data-home-mobile-best-more]").forEach((row) => { row.hidden = false; });
        button.remove();
    });
})();

(($) => {
    "use strict";

    if (!$ || !document.querySelector("#home-best-experts")) return;

    let activeRequest = null;
    let requestVersion = 0;

    const loadExperts = (url, updateHistory = false) => {
        const target = new URL(url, window.location.href);
        const requestUrl = new URL(target);
        requestUrl.hash = "";
        requestUrl.searchParams.set("fragment", "best_experts");

        const version = ++requestVersion;
        if (activeRequest) activeRequest.abort();

        const section = document.querySelector("#home-best-experts");
        window.CappersSkeleton?.loading(section);

        activeRequest = $.ajax({
            url: requestUrl.toString(),
            method: "GET",
            dataType: "html",
            headers: { "X-Requested-With": "XMLHttpRequest" },
        }).done((html) => {
            if (version !== requestVersion) return;

            const $next = $($.parseHTML(html, document, false)).filter("#home-best-experts").first();
            if (!$next.length) {
                window.location.assign(target.toString());
                return;
            }

            $("#home-best-experts").replaceWith($next);
            window.CappersSkeleton?.ready($next[0]);
            window.CappersSkeleton?.watchImages($next[0]);

            if (updateHistory) window.history.pushState(null, "", target.toString());
        }).fail((_xhr, status) => {
            if (version !== requestVersion || status === "abort") return;
            window.location.assign(target.toString());
        }).always(() => {
            if (version !== requestVersion) return;
            activeRequest = null;
            window.CappersSkeleton?.ready(document.querySelector("#home-best-experts"));
        });
    };

    $(document).on("click", "#home-best-experts .home-best-experts-periods a", function (event) {
        if (event.isDefaultPrevented() || event.button !== 0 ||
            event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;

        const selected = new URL(this.href, window.location.href);
        if (selected.origin !== window.location.origin) return;

        event.preventDefault();
        if ($(this).hasClass("is-active")) return;

        const next = new URL(window.location.href);
        next.searchParams.set("experts_period", selected.searchParams.get("experts_period"));
        next.hash = "";
        loadExperts(next, true);
    });

    window.addEventListener("popstate", () => {
        const period = new URL(window.location.href).searchParams.get("experts_period") || "30";
        const active = document.querySelector("#home-best-experts .home-best-experts-periods a.is-active");
        const displayed = active && new URL(active.href, window.location.href).searchParams.get("experts_period");
        if (period !== displayed) loadExperts(window.location.href);
    });
})(window.jQuery);
