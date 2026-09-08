(() => {
    const slider = document.querySelector("[data-forecast-slider]");
    if (!slider) return;

    const slides = Array.from(slider.querySelectorAll("[data-slide]"));
    const dots = Array.from(slider.querySelectorAll("[data-slider-dot]"));
    const previousButton = document.querySelector("[data-slider-prev]");
    const nextButton = document.querySelector("[data-slider-next]");
    const currentCounter = slider.querySelector("[data-slider-current]");
    const progress = slider.querySelector("[data-slider-progress]");

    if (slides.length < 2) {
        previousButton?.setAttribute("hidden", "");
        nextButton?.setAttribute("hidden", "");
        progress?.closest(".slider-progress")?.setAttribute("hidden", "");
        return;
    }

    const autoplayDelay = 5600;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let activeIndex = 0;
    let timer = null;
    let pointerStartX = null;

    const restartProgress = () => {
        if (!progress || reducedMotion.matches) return;
        progress.classList.remove("is-running");
        void progress.offsetWidth;
        progress.classList.add("is-running");
    };

    const stopProgress = () => {
        progress?.classList.remove("is-running");
    };

    const getDirection = (nextIndex) => {
        if (nextIndex === activeIndex) return slider.dataset.direction || "next";
        const forwardDistance = (nextIndex - activeIndex + slides.length) % slides.length;
        const backwardDistance = (activeIndex - nextIndex + slides.length) % slides.length;
        return forwardDistance <= backwardDistance ? "next" : "prev";
    };

    const render = (nextIndex, forcedDirection = null) => {
        const normalizedIndex = (nextIndex + slides.length) % slides.length;
        slider.dataset.direction = forcedDirection || getDirection(normalizedIndex);
        activeIndex = normalizedIndex;

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
        stopProgress();
    };

    const startAutoplay = () => {
        stopAutoplay();
        if (reducedMotion.matches || document.hidden) return;
        restartProgress();
        timer = window.setInterval(() => {
            render(activeIndex + 1, "next");
            restartProgress();
        }, autoplayDelay);
    };

    const goPrevious = () => {
        render(activeIndex - 1, "prev");
        startAutoplay();
    };

    const goNext = () => {
        render(activeIndex + 1, "next");
        startAutoplay();
    };

    previousButton?.addEventListener("click", goPrevious);
    nextButton?.addEventListener("click", goNext);

    dots.forEach((dot) => {
        dot.addEventListener("click", () => {
            const nextIndex = Number(dot.dataset.sliderDot || 0);
            render(nextIndex);
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

    reducedMotion.addEventListener?.("change", () => {
        if (reducedMotion.matches) stopAutoplay();
        else startAutoplay();
    });

    render(0, "next");
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

        const cards = Array.from(track.children);
        if (cards.length < 2) return;

        let pages = [];
        const scrollNode = track;

        const cardLeft = (card) => card.offsetLeft - track.offsetLeft;

        const getGap = () => {
            const styles = window.getComputedStyle(track);
            return Number.parseFloat(styles.columnGap || styles.gap || "0") || 0;
        };

        const buildPages = () => {
            const cardWidth = cards[0]?.getBoundingClientRect().width || 1;
            const perPage = Math.max(1, Math.floor((scrollNode.clientWidth + getGap()) / (cardWidth + getGap())));
            pages = [];
            for (let index = 0; index < cards.length; index += perPage) pages.push(index);

            if (dotsNode) {
                dotsNode.innerHTML = pages.map((_, index) => (
                    `<button type="button" data-home-card-dot="${index}" aria-label="Страница матчей ${index + 1}"></button>`
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
            const active = activePage();
            previousButton?.toggleAttribute("disabled", active <= 0);
            nextButton?.toggleAttribute("disabled", active >= pages.length - 1);
            dotsNode?.querySelectorAll("button").forEach((dot, index) => {
                dot.classList.toggle("is-active", index === active);
            });
        };

        const scrollToPage = (pageIndex) => {
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
