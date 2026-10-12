(() => {
    "use strict";

    // Sticky match list head: title and sport tiles fold into chips once the list scrolls,
    // and unfold again when it is scrolled back to the top.
    const ENTER_OFFSET = 24;
    const LEAVE_OFFSET = 40;
    const LEAVE_MIN_GAP = 16;

    const panel = document.querySelector(".matches-list-panel");
    const sentinel = document.querySelector("[data-matches-head-sentinel]");
    if (!panel || !sentinel) return;

    let head = null;
    let scroller = window;
    let anchor = 0;
    let isCompact = false;
    let holdUntil = 0;

    const currentHead = () => panel.querySelector(":scope > [data-matches-head]");

    // Desktop scrolls inside the list column, phones scroll the page.
    const pickScroller = () => {
        const overflow = window.getComputedStyle(panel).overflowY;
        return overflow === "auto" || overflow === "scroll" ? panel : window;
    };

    const scrollTop = () => (scroller === window ? window.scrollY : scroller.scrollTop);
    const maxScroll = () => (scroller === window
        ? document.documentElement.scrollHeight - window.innerHeight
        : scroller.scrollHeight - scroller.clientHeight);

    // The sentinel sits before the head, so its position does not move when the head folds.
    const measure = () => {
        const top = sentinel.getBoundingClientRect().top;
        anchor = scroller === window
            ? top + window.scrollY
            : top - scroller.getBoundingClientRect().top + scroller.scrollTop;
    };

    const enterAt = () => anchor + ENTER_OFFSET;
    // With room above the head it unfolds a little before its natural place, as in the mockup;
    // at the very top of the column it unfolds once the list is back at the start.
    const leaveAt = () => (anchor >= LEAVE_OFFSET + LEAVE_MIN_GAP ? anchor - LEAVE_OFFSET : anchor + ENTER_OFFSET - LEAVE_MIN_GAP);

    const laneHeight = (name) => head?.querySelector(`.matches-head-lane.is-${name} .matches-head-inner`)?.offsetHeight || 0;

    // Folding shortens the page; a short list must stay scrolled after that or it would unfold again.
    const canFold = () => {
        const shrink = laneHeight("title") + laneHeight("tiles") - laneHeight("chips");
        return maxScroll() - shrink > leaveAt() + LEAVE_MIN_GAP;
    };

    const setCompact = (value) => {
        isCompact = value;
        head?.classList.toggle("is-compact", value);
    };

    const onScroll = () => {
        if (!head || Date.now() < holdUntil) return;
        const y = scrollTop();
        if (!isCompact && y > enterAt() && canFold()) setCompact(true);
        else if (isCompact && y < leaveAt()) setCompact(false);
    };

    const bindScroller = () => {
        const next = pickScroller();
        if (next === scroller) return;
        scroller.removeEventListener("scroll", onScroll);
        scroller = next;
        scroller.addEventListener("scroll", onScroll, { passive: true });
    };

    const refresh = () => {
        head = currentHead();
        if (!head) return;
        head.classList.toggle("is-compact", isCompact);
        bindScroller();
        measure();
        onScroll();
    };

    const plural = (value, one, few, many) => {
        const mod10 = value % 10;
        const mod100 = value % 100;
        if (mod10 === 1 && mod100 !== 11) return one;
        if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
        return many;
    };

    // «обновлено N секунд назад» counts from the moment the head data arrived.
    const updateAgo = () => {
        const ago = head?.querySelector("[data-matches-head-ago]");
        if (!ago) return;
        if (!ago.dataset.loadedAt) ago.dataset.loadedAt = String(Date.now());
        const seconds = Math.floor((Date.now() - Number(ago.dataset.loadedAt)) / 1000);
        if (seconds < 5) {
            ago.textContent = "обновлено только что";
        } else if (seconds < 60) {
            ago.textContent = `обновлено ${seconds} ${plural(seconds, "секунду", "секунды", "секунд")} назад`;
        } else {
            const minutes = Math.floor(seconds / 60);
            ago.textContent = `обновлено ${minutes} ${plural(minutes, "минуту", "минуты", "минут")} назад`;
        }
    };

    // While the list is swapped its height jumps; the head keeps its state until the new list settles.
    const hold = (ms) => {
        holdUntil = Date.now() + ms;
        window.setTimeout(onScroll, ms + 20);
    };

    // Keeps a folded head folded: the list starts right under it after a filter change.
    const scrollToList = () => {
        hold(450);
        const top = isCompact ? Math.min(enterAt() + 1, maxScroll()) : 0;
        if (scroller === window) {
            if (window.scrollY > top) window.scrollTo({ top, behavior: "auto" });
        } else {
            scroller.scrollTo({ top, behavior: "auto" });
        }
    };

    scroller.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", refresh);
    document.addEventListener("matches:filters-updated", refresh);
    window.setInterval(updateAgo, 5000);
    window.CappersMatchesHead = { hold, scrollToList };

    refresh();
    updateAgo();
})();
