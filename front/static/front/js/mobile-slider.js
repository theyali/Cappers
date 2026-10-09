(() => {
    // Phone sliders scroll natively; the dots follow the card in view.
    document.querySelectorAll("[data-home-mobile-slider]").forEach((slider) => {
        const track = slider.querySelector("[data-home-mobile-track]");
        if (!track) return;

        const cards = Array.from(track.children);
        const dots = Array.from(slider.querySelectorAll("[data-home-mobile-dot]"));
        let frame = 0;

        const update = () => {
            frame = 0;
            const step = cards.length > 1 ? cards[1].offsetLeft - cards[0].offsetLeft : track.clientWidth;
            const atEnd = track.scrollLeft + track.clientWidth >= track.scrollWidth - 2;
            const index = atEnd ? cards.length - 1 : Math.round(track.scrollLeft / step);
            dots.forEach((dot, dotIndex) => dot.classList.toggle("is-active", dotIndex === index));
        };

        track.addEventListener("scroll", () => {
            if (!frame) frame = requestAnimationFrame(update);
        }, { passive: true });

        // Autoplay only for the desktop profile carousel; mobile scrolling is unchanged.
        if (slider.classList.contains("profile-best-coupons-slider") && cards.length > 1) {
            const desktop = window.matchMedia("(min-width: 1121px)");
            const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
            let paused = false;
            slider.addEventListener("mouseenter", () => { paused = true; });
            slider.addEventListener("mouseleave", () => { paused = false; });
            slider.addEventListener("focusin", () => { paused = true; });
            slider.addEventListener("focusout", (event) => {
                if (!slider.contains(event.relatedTarget)) paused = false;
            });
            window.setInterval(() => {
                if (!desktop.matches || reducedMotion.matches || paused || document.hidden) return;
                if (!slider.closest(".profile-tab-panel")?.classList.contains("is-active")) return;
                const step = cards[1].offsetLeft - cards[0].offsetLeft;
                if (!step) return;
                const current = Math.round(track.scrollLeft / step);
                const next = (current + 1) % cards.length;
                track.scrollTo({ left: cards[next].offsetLeft - cards[0].offsetLeft, behavior: "smooth" });
            }, 5500);
        }
    });
})();
