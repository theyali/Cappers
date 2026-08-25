(() => {
    const slider = document.querySelector("[data-forecast-slider]");
    if (!slider) return;

    const slides = Array.from(slider.querySelectorAll("[data-slide]"));
    const dots = Array.from(slider.querySelectorAll("[data-slider-dot]"));
    const previousButton = document.querySelector("[data-slider-prev]");
    const nextButton = document.querySelector("[data-slider-next]");
    const currentCounter = slider.querySelector("[data-slider-current]");

    if (slides.length < 2) {
        previousButton?.setAttribute("hidden", "");
        nextButton?.setAttribute("hidden", "");
        return;
    }

    const autoplayDelay = 5600;
    let activeIndex = 0;
    let timer = null;
    let pointerStartX = null;

    const render = (nextIndex) => {
        activeIndex = (nextIndex + slides.length) % slides.length;

        slides.forEach((slide, index) => {
            const isActive = index === activeIndex;
            slide.classList.toggle("is-active", isActive);
            slide.setAttribute("aria-hidden", isActive ? "false" : "true");
        });

        dots.forEach((dot, index) => {
            const isActive = index === activeIndex;
            dot.classList.toggle("is-active", isActive);
            dot.setAttribute("aria-selected", isActive ? "true" : "false");
            dot.tabIndex = isActive ? 0 : -1;
        });

        if (currentCounter) {
            currentCounter.textContent = String(activeIndex + 1).padStart(2, "0");
        }
    };

    const stopAutoplay = () => {
        if (timer) window.clearInterval(timer);
        timer = null;
    };

    const startAutoplay = () => {
        stopAutoplay();
        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
        timer = window.setInterval(() => render(activeIndex + 1), autoplayDelay);
    };

    const goPrevious = () => {
        render(activeIndex - 1);
        startAutoplay();
    };

    const goNext = () => {
        render(activeIndex + 1);
        startAutoplay();
    };

    previousButton?.addEventListener("click", goPrevious);
    nextButton?.addEventListener("click", goNext);

    dots.forEach((dot) => {
        dot.addEventListener("click", () => {
            render(Number(dot.dataset.sliderDot || 0));
            startAutoplay();
        });
    });

    slider.addEventListener("mouseenter", stopAutoplay);
    slider.addEventListener("mouseleave", startAutoplay);
    slider.addEventListener("focusin", stopAutoplay);
    slider.addEventListener("focusout", (event) => {
        if (!slider.contains(event.relatedTarget)) startAutoplay();
    });

    slider.addEventListener("pointerdown", (event) => {
        if (event.pointerType === "mouse") return;
        pointerStartX = event.clientX;
    });

    slider.addEventListener("pointerup", (event) => {
        if (pointerStartX === null) return;
        const distance = event.clientX - pointerStartX;
        pointerStartX = null;

        if (Math.abs(distance) < 45) return;
        if (distance > 0) goPrevious();
        else goNext();
    });

    slider.addEventListener("pointercancel", () => {
        pointerStartX = null;
    });

    slider.addEventListener("keydown", (event) => {
        if (event.key === "ArrowLeft") {
            event.preventDefault();
            goPrevious();
        }
        if (event.key === "ArrowRight") {
            event.preventDefault();
            goNext();
        }
    });

    document.addEventListener("visibilitychange", () => {
        if (document.hidden) stopAutoplay();
        else startAutoplay();
    });

    render(0);
    startAutoplay();
})();
