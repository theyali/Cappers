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

// Each responsive copy owns its reader so opening one never changes the other.
(() => {
    document.querySelectorAll("[data-prediction-article]").forEach((article) => {
        const preview = article.querySelector("[data-article-preview]");
        const full = article.querySelector("[data-article-full]");
        const expand = article.querySelector("[data-article-expand]");
        const collapse = article.querySelector("[data-article-collapse]");
        if (!preview || !full || !expand || !collapse) return;
        const title = article.querySelector(".coupon-prediction-article-title");
        const hero = article.querySelector(".coupon-prediction-article-hero");
        article.dataset.articleEnhanced = "true";
        const sync = () => {
            if (!hero.getClientRects().length) return;
            const clipped = preview.scrollHeight > preview.clientHeight + 1;
            const short = !clipped && preview.scrollHeight <= parseFloat(getComputedStyle(preview).lineHeight) * 2 + 1
                && title.scrollHeight <= parseFloat(getComputedStyle(title).lineHeight) + 3;
            article.classList.toggle("is-long", clipped);
            article.classList.toggle("is-short", short);
            expand.hidden = !clipped;
            if (!clipped) full.open = false;
            expand.setAttribute("aria-expanded", String(full.open));
        };
        expand.addEventListener("click", () => {
            full.open = !full.open;
            expand.setAttribute("aria-expanded", String(full.open));
        });
        collapse.addEventListener("click", () => {
            full.open = false;
            expand.setAttribute("aria-expanded", "false");
            expand.focus({ preventScroll: true });
        });
        full.addEventListener("toggle", () => expand.setAttribute("aria-expanded", String(full.open)));
        if (typeof ResizeObserver !== "undefined") new ResizeObserver(sync).observe(hero);
        window.addEventListener("resize", sync, { passive: true });
        document.fonts?.ready.then(sync);
        sync();
    });
})();

(() => {
    document.querySelectorAll("[data-coupon-back]").forEach((link) => {
        link.addEventListener("click", (event) => {
            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            if (window.history.length > 1 && document.referrer && link.href === document.referrer) {
                event.preventDefault();
                window.history.back();
            }
        });
    });
})();
