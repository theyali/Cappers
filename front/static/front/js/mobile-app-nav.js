(() => {
    const nav = document.querySelector(".mobile-app-nav");
    if (!nav) return;
    const mobile = window.matchMedia("(max-width: 1120px)");
    const root = document.scrollingElement || document.documentElement;
    const pageScrollers = ".predictions-content, .site-main, [data-page-scroll]";
    let positions = new WeakMap();
    let activeScroller = root;
    let pendingScroller = null;
    let frame = 0;
    let direction = 0;
    let travel = 0;
    let keyboardNavigation = false;

    const position = (scroller) => Math.max(0, Math.min(scroller.scrollTop, Math.max(0, scroller.scrollHeight - scroller.clientHeight)));
    const show = () => nav.classList.remove("is-scroll-hidden");
    const reset = () => {
        show();
        positions = new WeakMap();
        positions.set(root, position(root));
        positions.set(document.body, position(document.body));
        document.querySelectorAll(pageScrollers).forEach((scroller) => positions.set(scroller, position(scroller)));
        direction = 0;
        travel = 0;
        activeScroller = root;
        pendingScroller = null;
    };
    const update = () => {
        frame = 0;
        const scroller = pendingScroller;
        pendingScroller = null;
        if (!scroller || !mobile.matches) return;
        const current = position(scroller);
        const previous = positions.get(scroller) ?? current;
        positions.set(scroller, current);
        if (scroller !== activeScroller) {
            direction = 0;
            travel = 0;
            activeScroller = scroller;
        }
        if (current <= 24) {
            show();
            travel = 0;
            return;
        }
        const delta = current - previous;
        if (!delta) return;
        const nextDirection = Math.sign(delta);
        if (nextDirection !== direction) {
            direction = nextDirection;
            travel = 0;
        }
        travel += Math.abs(delta);
        if (direction < 0 && travel >= 10) {
            show();
        } else if (direction > 0 && current > 72 && travel >= 18 && !(keyboardNavigation && nav.contains(document.activeElement))) {
            nav.classList.add("is-scroll-hidden");
        }
    };
    document.addEventListener("scroll", (event) => {
        if (!mobile.matches) return;
        const target = event.target;
        const scroller = target === document || target === root ? root : target === document.body || target.matches?.(pageScrollers) ? target : null;
        // Horizontal rails and modal content do not change page navigation.
        if (!scroller) return;
        pendingScroller = scroller;
        if (!frame) frame = window.requestAnimationFrame(update);
    }, { capture: true, passive: true });
    document.addEventListener("keydown", (event) => {
        if (event.key !== "Tab") return;
        keyboardNavigation = true;
        show();
    });
    document.addEventListener("pointerdown", () => { keyboardNavigation = false; }, { passive: true });
    nav.addEventListener("focusin", show);
    mobile.addEventListener("change", reset);
    window.addEventListener("pageshow", reset);
    window.addEventListener("orientationchange", reset);
    reset();
})();
