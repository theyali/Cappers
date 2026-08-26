(() => {
    const root = document.querySelector("[data-article-slider]");
    if (!root) return;

    const track = root.querySelector("[data-article-track]");
    const cards = Array.from(root.querySelectorAll("[data-article-card]"));
    const previous = root.querySelector("[data-article-prev]");
    const next = root.querySelector("[data-article-next]");
    const dotsRoot = root.querySelector("[data-article-dots]");
    const current = root.querySelector("[data-article-current]");

    if (!track || cards.length < 1) return;

    let pages = [];
    let activePage = 0;
    let settleFrame = null;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

    const cardsPerView = () => {
        if (window.matchMedia("(max-width: 680px)").matches) return 1;
        if (window.matchMedia("(max-width: 980px)").matches) return 2;
        return 3;
    };

    const buildPages = () => {
        const perView = cardsPerView();
        const maxStart = Math.max(0, cards.length - perView);
        const starts = [];

        for (let index = 0; index <= maxStart; index += perView) {
            starts.push(index);
        }
        if (starts[starts.length - 1] !== maxStart) starts.push(maxStart);

        pages = starts.map((startIndex) => ({ startIndex }));
        activePage = Math.min(activePage, Math.max(0, pages.length - 1));
        renderDots();
        render();
    };

    const targetLeft = (pageIndex) => {
        const page = pages[pageIndex];
        if (!page) return 0;
        const card = cards[page.startIndex];
        const maxScroll = Math.max(0, track.scrollWidth - track.clientWidth);
        return Math.min(card.offsetLeft - cards[0].offsetLeft, maxScroll);
    };

    const goToPage = (pageIndex, smooth = true) => {
        activePage = Math.max(0, Math.min(pageIndex, pages.length - 1));
        track.scrollTo({
            left: targetLeft(activePage),
            behavior: smooth && !reducedMotion.matches ? "smooth" : "auto",
        });
        render();
    };

    const renderDots = () => {
        if (!dotsRoot) return;
        dotsRoot.replaceChildren();

        pages.forEach((page, index) => {
            const dot = document.createElement("button");
            dot.type = "button";
            dot.className = "home-article-dot";
            dot.dataset.articleDot = String(index);
            dot.setAttribute("aria-label", `Страница статей ${index + 1}`);
            dot.addEventListener("click", () => goToPage(index));
            dotsRoot.appendChild(dot);
        });
    };

    const render = () => {
        const page = pages[activePage] || { startIndex: 0 };
        const perView = cardsPerView();

        if (current) current.textContent = String(page.startIndex + 1).padStart(2, "0");

        root.querySelectorAll("[data-article-dot]").forEach((dot, index) => {
            const isActive = index === activePage;
            dot.classList.toggle("is-active", isActive);
            dot.setAttribute("aria-current", isActive ? "true" : "false");
        });

        cards.forEach((card, index) => {
            const isVisible = index >= page.startIndex && index < page.startIndex + perView;
            card.classList.toggle("is-in-view", isVisible);
        });

        if (previous) previous.disabled = activePage === 0;
        if (next) next.disabled = activePage >= pages.length - 1;
    };

    const syncFromScroll = () => {
        if (!pages.length) return;
        const left = track.scrollLeft;
        let nearestPage = 0;
        let nearestDistance = Number.POSITIVE_INFINITY;

        pages.forEach((_, index) => {
            const distance = Math.abs(targetLeft(index) - left);
            if (distance < nearestDistance) {
                nearestDistance = distance;
                nearestPage = index;
            }
        });

        if (nearestPage !== activePage) {
            activePage = nearestPage;
            render();
        }
    };

    previous?.addEventListener("click", () => goToPage(activePage - 1));
    next?.addEventListener("click", () => goToPage(activePage + 1));

    root.addEventListener("keydown", (event) => {
        if (event.key === "ArrowLeft") {
            event.preventDefault();
            goToPage(activePage - 1);
        }
        if (event.key === "ArrowRight") {
            event.preventDefault();
            goToPage(activePage + 1);
        }
    });

    track.addEventListener("scroll", () => {
        if (settleFrame) window.cancelAnimationFrame(settleFrame);
        settleFrame = window.requestAnimationFrame(syncFromScroll);
    }, { passive: true });

    let resizeTimer = null;
    window.addEventListener("resize", () => {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(() => {
            const firstVisibleIndex = (pages[activePage] || { startIndex: 0 }).startIndex;
            buildPages();
            const newPage = pages.findIndex((page) => page.startIndex >= firstVisibleIndex);
            goToPage(newPage >= 0 ? newPage : pages.length - 1, false);
        }, 120);
    });

    buildPages();
    goToPage(0, false);
})();
