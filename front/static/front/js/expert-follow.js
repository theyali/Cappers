(() => {
    const getCookie = (name) => {
        const prefix = `${name}=`;
        return document.cookie
            .split(";")
            .map((item) => item.trim())
            .find((item) => item.startsWith(prefix))
            ?.slice(prefix.length) || "";
    };

    const syncButtons = (url, active) => {
        document.querySelectorAll("[data-expert-follow]").forEach((item) => {
            if (item.dataset.url !== url) return;
            item.classList.toggle("is-active", Boolean(active));
            item.setAttribute("aria-pressed", active ? "true" : "false");
            const label = item.querySelector("[data-follow-label]");
            if (label) label.textContent = active ? "Вы подписаны" : "Подписаться";
        });
    };

    const updateCounter = (node, value) => {
        if (!node) return;
        node.textContent = String(value);
        node.animate?.(
            [
                { transform: "scale(1)" },
                { transform: "scale(1.12)" },
                { transform: "scale(1)" },
            ],
            { duration: 220, easing: "ease-out" },
        );
    };

    const syncFollowersCount = (button, followersCount) => {
        const value = Number(followersCount);
        if (!Number.isFinite(value)) return;

        const card = button.closest("[data-follow-card]");
        if (card) {
            card.querySelectorAll("[data-followers-count]").forEach((node) => {
                updateCounter(node, value);
            });
        }

        // Only the profile's own follow buttons change its counters, not the recommended experts below.
        if (!button.closest(".expert-public-page, [data-expert-mobile], [data-expert-mobile-tabs]")) return;
        document
            .querySelectorAll(".expert-public-page [data-followers-count], [data-expert-mobile] [data-followers-count]")
            .forEach((node) => updateCounter(node, value));
    };

    const hideCopybettingForCapper = () => {
        const analystNavLink = document.querySelector(
            '.nav-profile-dropdown a[href*="/cabinet/profile/"][href*="tab=predictions"]'
        );
        if (!analystNavLink) return;

        document
            .querySelectorAll('.expert-public-name-row a[href^="/wallets/copybetting/"]')
            .forEach((link) => link.remove());
    };

    const copyShareUrl = async (url) => {
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(url);
            return;
        }

        const textarea = document.createElement("textarea");
        textarea.value = url;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.append(textarea);
        textarea.select();
        document.execCommand("copy");
        textarea.remove();
    };

    const showShareCopied = (shareLink) => {
        const label = shareLink.querySelector("[data-expert-share-label]");
        if (!label) return;

        label.textContent = "Ссылка скопирована";
        window.setTimeout(() => {
            label.textContent = "Поделиться профилем";
        }, 1800);
    };

    const initShareButton = () => {
        const side = document.querySelector(".expert-public-side");
        if (!side || side.querySelector("[data-expert-share]")) return;

        const shareLink = document.createElement("a");
        shareLink.className = "expert-public-edit expert-public-social";
        shareLink.href = window.location.href;
        shareLink.setAttribute("role", "button");
        shareLink.setAttribute("aria-label", "Поделиться профилем");
        shareLink.setAttribute("data-expert-share", "");

        const icon = document.createElement("span");
        icon.className = "expert-public-social-icon";
        icon.setAttribute("aria-hidden", "true");
        icon.setAttribute("data-skeleton-image", "");

        const image = document.createElement("img");
        const logoSrc = side.querySelector(".expert-public-brand-logo img")?.src;
        image.src = logoSrc
            ? new URL("../svgs/share.svg", logoSrc).href
            : "/static/front/svgs/share.svg";
        image.width = 20;
        image.height = 20;
        image.alt = "";
        icon.append(image);

        const label = document.createElement("span");
        label.setAttribute("data-expert-share-label", "");
        label.textContent = "Поделиться профилем";

        shareLink.append(icon, label);
        side.append(shareLink);
        window.CappersSkeleton?.watchImage(icon);
    };

    const initRecommendationsSlider = () => {
        const section = document.querySelector("[data-expert-recommendations]");
        if (!section) return;

        const track = section.querySelector("[data-expert-recommendations-track]");
        const previous = section.querySelector("[data-expert-recommendations-prev]");
        const next = section.querySelector("[data-expert-recommendations-next]");
        const dots = section.querySelector("[data-expert-recommendations-dots]");
        const card = track?.querySelector(".expert-recommendation-card");
        if (!track || !card || !previous || !next || !dots) return;

        let positions = [0];
        const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
        const moveTo = (position) => {
            track.scrollTo({
                left: Math.max(0, Math.min(position, track.scrollWidth - track.clientWidth)),
                behavior: reducedMotion.matches ? "instant" : "smooth",
            });
        };

        const updateControls = () => {
            const current = track.scrollLeft;
            const max = Math.max(0, track.scrollWidth - track.clientWidth);
            previous.disabled = current <= 2;
            next.disabled = current >= max - 2;
            let closest = 0;
            positions.forEach((position, index) => {
                if (Math.abs(position - current) < Math.abs(positions[closest] - current)) {
                    closest = index;
                }
            });
            dots.querySelectorAll("button").forEach((dot, index) => {
                dot.classList.toggle("is-active", index === closest);
                dot.setAttribute("aria-current", index === closest ? "true" : "false");
            });
        };

        const rebuild = () => {
            const max = Math.max(0, track.scrollWidth - track.clientWidth);
            const gap = Number.parseFloat(window.getComputedStyle(track).columnGap) || 0;
            const step = card.getBoundingClientRect().width + gap;
            positions = [0];
            if (step > 0 && max > 2) {
                for (let offset = step; offset < max - 2; offset += step) {
                    positions.push(Math.round(offset));
                }
                positions.push(max);
            }
            dots.replaceChildren();
            positions.forEach((position, index) => {
                const dot = document.createElement("button");
                dot.type = "button";
                dot.setAttribute("aria-label", `Показать карточки, позиция ${index + 1} из ${positions.length}`);
                dot.addEventListener("click", () => moveTo(position));
                dots.append(dot);
            });
            dots.hidden = positions.length <= 1;
            updateControls();
        };

        previous.addEventListener("click", () => {
            const index = positions.findLastIndex((position) => position < track.scrollLeft - 2);
            moveTo(positions[Math.max(0, index)]);
        });
        next.addEventListener("click", () => {
            const position = positions.find((position) => position > track.scrollLeft + 2);
            moveTo(position ?? positions[positions.length - 1]);
        });
        track.addEventListener("scroll", updateControls, { passive: true });
        if (typeof ResizeObserver !== "undefined") {
            new ResizeObserver(rebuild).observe(track);
        } else {
            window.addEventListener("resize", rebuild);
        }
        rebuild();
    };

    initRecommendationsSlider();

    hideCopybettingForCapper();
    initShareButton();

    document.addEventListener("click", async (event) => {
        if (!(event.target instanceof Element)) return;

        const shareLink = event.target.closest("[data-expert-share]");
        if (shareLink) {
            event.preventDefault();

            const url = window.location.href;
            const expertName = document.querySelector(".expert-public-name-row h1")?.textContent?.trim();

            if (navigator.share) {
                try {
                    await navigator.share({
                        title: expertName ? `${expertName} — КапперХаб` : document.title,
                        url,
                    });
                    return;
                } catch (error) {
                    if (error?.name === "AbortError") return;
                }
            }

            try {
                await copyShareUrl(url);
                showShareCopied(shareLink);
            } catch (error) {
                console.error(error);
            }
            return;
        }

        const button = event.target.closest("[data-expert-follow]");
        if (!button || button.disabled || !button.dataset.url) return;

        event.preventDefault();
        button.disabled = true;

        try {
            const response = await fetch(button.dataset.url, {
                method: "POST",
                headers: {
                    "X-CSRFToken": decodeURIComponent(getCookie("csrftoken")),
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json",
                },
                credentials: "same-origin",
            });
            const result = await response.json();
            if (!response.ok || !result.ok) {
                if (result.payment_required && result.payment_url) {
                    const paymentUrl = new URL(result.payment_url, window.location.origin);
                    if (!paymentUrl.searchParams.has("next")) {
                        paymentUrl.searchParams.set(
                            "next",
                            `${window.location.pathname}${window.location.search}`,
                        );
                    }
                    window.location.href = paymentUrl.toString();
                    return;
                }
                throw new Error(result.error || "Не удалось изменить подписку.");
            }

            syncButtons(button.dataset.url, Boolean(result.active));
            syncFollowersCount(button, result.followers_count);
        } catch (error) {
            console.error(error);
        } finally {
            button.disabled = false;
        }
    });
})();
