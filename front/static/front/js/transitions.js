(() => {
    const overlay = document.querySelector(".logo-transition");
    if (!overlay) return;

    let isLeaving = false;

    const showTransition = () => {
        if (isLeaving) return;
        isLeaving = true;
        overlay.classList.add("is-active");
    };

    const transitionDuration = 420;

    const isModifiedClick = (event) => (
        event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0
    );

    document.addEventListener("click", (event) => {
        const link = event.target.closest("a[href]");
        if (!link || isModifiedClick(event)) return;
        if (link.target && link.target !== "_self") return;
        if (link.hasAttribute("download")) return;
        if (link.hasAttribute("data-profile-tab-link")) return;
        if (link.hasAttribute("data-mobile-coupon-toggle")) {
            event.preventDefault();
            return;
        }

        const url = new URL(link.href, window.location.href);
        if (url.origin !== window.location.origin) return;
        if (url.pathname === window.location.pathname && url.search === window.location.search) return;
        if (url.hash && url.pathname === window.location.pathname && url.search === window.location.search) return;

        event.preventDefault();
        showTransition();
        window.setTimeout(() => {
            window.location.href = url.href;
        }, transitionDuration);
    });

    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        if (event.defaultPrevented) return;
        if (form.matches("[data-no-transition]")) return;
        if (form.dataset.transitionSubmitted === "true") return;

        event.preventDefault();
        form.dataset.transitionSubmitted = "true";
        showTransition();
        window.setTimeout(() => {
            form.submit();
        }, transitionDuration);
    });

    window.addEventListener("pageshow", () => {
        isLeaving = false;
        overlay.classList.remove("is-active");
    });
})();
