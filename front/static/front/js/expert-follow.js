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

        document
            .querySelectorAll(".expert-public-page [data-followers-count]")
            .forEach((node) => updateCounter(node, value));
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
