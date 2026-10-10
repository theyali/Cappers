(() => {
    const slider = document.querySelector("[data-coupon-slider]");
    if (!slider) return;
    const track = slider.querySelector("[data-coupon-slider-track]");
    const slides = Array.from(track.children);
    const previous = slider.querySelector("[data-coupon-slide-prev]");
    const next = slider.querySelector("[data-coupon-slide-next]");
    const count = slider.querySelector("[data-coupon-slide-count]");
    if (!previous || !next || slides.length < 2) return;

    const currentIndex = () => Math.min(slides.length - 1, Math.max(0, Math.round(track.scrollLeft / track.clientWidth)));
    const update = () => {
        const index = currentIndex();
        previous.disabled = index === 0;
        next.disabled = index === slides.length - 1;
        if (count) count.textContent = (index + 1) + " / " + slides.length;
    };
    const show = (direction) => {
        const index = Math.min(slides.length - 1, Math.max(0, currentIndex() + direction));
        track.scrollTo({ left: index * track.clientWidth, behavior: "smooth" });
    };

    previous.addEventListener("click", () => show(-1));
    next.addEventListener("click", () => show(1));
    track.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    update();
})();
