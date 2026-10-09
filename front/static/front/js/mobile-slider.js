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
    });
})();
