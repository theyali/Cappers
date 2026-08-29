(() => {
    const loadingClass = "is-skeleton-loading";

    const asElement = (target) => {
        if (!target) return null;
        if (target instanceof Element) return target;
        if (typeof target === "string") return document.querySelector(target);
        return null;
    };

    const setLoading = (target, loading = true) => {
        const element = asElement(target);
        if (!element) return null;
        if (
            loading
            && !element.matches("img")
            && !element.hasAttribute("data-skeleton-block")
            && !element.hasAttribute("data-skeleton-image")
        ) {
            element.dataset.skeletonBlock = "";
        }
        element.classList.toggle(loadingClass, Boolean(loading));
        element.setAttribute("aria-busy", loading ? "true" : "false");
        return element;
    };

    const ready = (target) => setLoading(target, false);
    const loading = (target) => setLoading(target, true);

    const imageFor = (target) => {
        const element = asElement(target);
        if (!element) return null;
        if (element.matches("img")) return element;
        return element.querySelector("img");
    };

    const watchImage = (target) => {
        let element = asElement(target);
        const image = imageFor(element);
        if (!element || !image) return;
        if (element.matches("img")) {
            element = image.parentElement || element;
        }

        if (image.complete) {
            ready(element);
            return;
        }

        loading(element);
        const finish = () => ready(element);
        image.addEventListener("load", finish, { once: true });
        image.addEventListener("error", finish, { once: true });
    };

    const watchImages = (root = document) => {
        const scope = asElement(root) || document;
        scope.querySelectorAll("[data-skeleton-image]").forEach(watchImage);
    };

    const bind = (target, promise) => {
        loading(target);
        return Promise.resolve(promise).finally(() => ready(target));
    };

    window.CappersSkeleton = {
        bind,
        loading,
        ready,
        setLoading,
        watchImage,
        watchImages,
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => watchImages(document), { once: true });
    } else {
        watchImages(document);
    }

    document.addEventListener("matches:appended", (event) => {
        (event.detail?.nodes || []).forEach((node) => watchImages(node));
    });
})();
