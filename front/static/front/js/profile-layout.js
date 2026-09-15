(() => {
    const page = document.querySelector(".profile-page.matches-page");
    if (!page) return;

    const shell = page.querySelector(".matches-shell");
    const content = shell?.querySelector(":scope > .matches-list-panel.profile-page");
    const head = content?.querySelector(".profile-dashboard-head");
    const hero = head?.querySelector(".profile-hero");
    const promoSidebar = shell?.querySelector(":scope > .coupon-sidebar");
    const promoBlock = promoSidebar?.querySelector(".profile-pro-promo");

    if (!shell || !content || !head || !hero || !promoSidebar || !promoBlock) return;

    const heroIndex = Math.floor(Math.random() * 5) + 1;
    hero.classList.add("expert-public-hero", `is-bg-${heroIndex}`);

    promoBlock.className = "adv-banner";
    promoBlock.setAttribute("data-skeleton-block", "");
    promoBlock.setAttribute("aria-label", "Промо");
    promoBlock.replaceChildren();

    head.classList.remove("is-reader");
    head.appendChild(promoBlock);
    promoSidebar.remove();

    window.CappersSkeleton?.loading(promoBlock);

    const collapsePromo = () => {
        promoBlock.remove();
        head.classList.add("is-reader");
    };

    const createImage = (data) => {
        const image = document.createElement("img");
        image.src = data.url;
        image.alt = "";
        image.width = data.width;
        image.height = data.height;
        image.loading = "eager";
        image.decoding = "async";
        return image;
    };

    fetch("/cabinet/profile/promo-banner/", {
        credentials: "same-origin",
        cache: "no-store",
        headers: { "X-Requested-With": "XMLHttpRequest" },
    })
        .then((response) => {
            if (!response.ok) throw new Error("Не удалось загрузить промо-баннер.");
            return response.json();
        })
        .then((payload) => {
            const banner = payload?.banner;
            if (!payload?.ok || !banner?.image?.url) {
                collapsePromo();
                return;
            }

            const picture = document.createElement("picture");
            picture.setAttribute("data-skeleton-image", "");

            if (banner.mobile_image?.url) {
                const source = document.createElement("source");
                source.media = "(max-width: 767px)";
                source.srcset = banner.mobile_image.url;
                source.setAttribute("width", banner.mobile_image.width);
                source.setAttribute("height", banner.mobile_image.height);
                picture.appendChild(source);
            }

            const image = createImage(banner.image);
            picture.appendChild(image);

            const link = document.createElement("a");
            link.className = "adv-banner";
            link.href = banner.url || "#";
            link.setAttribute("aria-label", banner.name || "Открыть промо-баннер");
            link.setAttribute("data-skeleton-block", "");
            link.appendChild(picture);
            window.CappersSkeleton?.loading(link);

            promoBlock.replaceWith(link);
            window.CappersSkeleton?.watchImage(picture);

            const ready = () => window.CappersSkeleton?.ready(link);
            if (image.complete) {
                ready();
            } else {
                image.addEventListener("load", ready, { once: true });
                image.addEventListener("error", ready, { once: true });
            }
        })
        .catch(() => {
            collapsePromo();
        });
})();
