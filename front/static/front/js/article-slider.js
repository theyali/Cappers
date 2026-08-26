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

    let activeIndex = 0;
    let settleTimer = null;

    const goTo = (index, smooth = true) => {
        activeIndex = Math.max(0, Math.min(index, cards.length - 1));
        track.scrollTo({
            left: cards[activeIndex].offsetLeft - track.offsetLeft,
            behavior: smooth ? "smooth" : "auto",
        });
        render();
    };

    const render = () => {
        if (current) current.textContent = String(activeIndex + 1).padStart(2, "0");
        root.querySelectorAll("[data-article-dot]").forEach((dot, index) => {
            const isActive = index === activeIndex;
            dot.classList.toggle("is-active", isActive);
            dot.setAttribute("aria-current", isActive ? "true" : "false");
        });
        if (previous) previous.disabled = activeIndex === 0;
        if (next) next.disabled = activeIndex === cards.length - 1;
    };

    if (dotsRoot) {
        cards.forEach((_, index) => {
            const dot = document.createElement("button");
            dot.type = "button";
            dot.className = "home-article-dot";
            dot.dataset.articleDot = String(index);
            dot.setAttribute("aria-label", `Статья ${index + 1}`);
            dot.addEventListener("click", () => goTo(index));
            dotsRoot.appendChild(dot);
        });
    }

    previous?.addEventListener("click", () => goTo(activeIndex - 1));
    next?.addEventListener("click", () => goTo(activeIndex + 1));

    track.addEventListener("scroll", () => {
        window.clearTimeout(settleTimer);
        settleTimer = window.setTimeout(() => {
            let nearest = 0;
            let nearestDistance = Number.POSITIVE_INFINITY;
            cards.forEach((card, index) => {
                const distance = Math.abs(card.offsetLeft - track.offsetLeft - track.scrollLeft);
                if (distance < nearestDistance) {
                    nearest = index;
                    nearestDistance = distance;
                }
            });
            activeIndex = nearest;
            render();
        }, 80);
    }, { passive: true });

    window.addEventListener("resize", () => goTo(activeIndex, false));

    render();
})();
