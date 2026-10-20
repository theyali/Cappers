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

(() => {
    const page = document.querySelector("[data-coupon-open-url]");
    if (!page) return;
    let sent = false;
    let pending = false;
    const record = () => {
        if (sent || pending || document.visibilityState !== "visible") return;
        pending = true;
        // Wait for the visible content to paint; document prefetches never POST.
        requestAnimationFrame(() => requestAnimationFrame(async () => {
            if (document.visibilityState !== "visible") {
                pending = false;
                return;
            }
            const token = document.cookie.split(";").map((part) => part.trim())
                .find((part) => part.startsWith("csrftoken="))?.slice(10) || "";
            try {
                const response = await fetch(page.dataset.couponOpenUrl, {
                    method: "POST", credentials: "same-origin",
                    headers: { "X-CSRFToken": decodeURIComponent(token), "X-Requested-With": "XMLHttpRequest" },
                });
                if (!response.ok) return;
                const result = await response.json();
                if (!result.ok) return;
                sent = true;
                document.querySelectorAll(`[data-coupon-open-count="${CSS.escape(page.dataset.couponId)}"]`).forEach((node) => {
                    node.textContent = result.label;
                    node.hidden = result.unique_opens_count === 0 && node.dataset.showZero !== "true";
                });
            } catch (_) {
                // Analytics failure must never block reading the coupon.
            } finally {
                pending = false;
            }
        }));
    };
    document.addEventListener("visibilitychange", record);
    window.addEventListener("pageshow", record);
    record();
})();
