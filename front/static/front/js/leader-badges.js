(() => {
    const selector = "[data-leader-badge]";
    const tooltipId = "expert-leader-tooltip";
    let tooltip = null;
    let active = null;
    let pendingOwner = null;
    let hoverTimer = 0;
    let hideTimer = 0;

    function close() {
        window.clearTimeout(hoverTimer);
        window.clearTimeout(hideTimer);
        pendingOwner = null;
        if (active) {
            const ids = (active.owner.getAttribute("aria-describedby") || "")
                .split(/\s+/).filter((id) => id && id !== tooltipId);
            if (ids.length) active.owner.setAttribute("aria-describedby", ids.join(" "));
            else active.owner.removeAttribute("aria-describedby");
        }
        active = null;
        if (tooltip) tooltip.hidden = true;
    }

    function show(badge, owner) {
        close();
        if (!badge.isConnected || !owner.isConnected) return;
        const label = badge.getAttribute("aria-label");
        if (!label) return;
        if (!tooltip) {
            tooltip = document.createElement("div");
            tooltip.id = tooltipId;
            tooltip.className = "expert-leader-tooltip";
            tooltip.setAttribute("role", "tooltip");
            document.body.append(tooltip);
            // A single delegated owner also covers AJAX replacement and lazy cards.
            new MutationObserver(() => {
                if (active && (!active.badge.isConnected || !active.owner.isConnected)) close();
            }).observe(document.body, { childList: true, subtree: true });
        }
        active = { badge, owner };
        const ids = new Set((owner.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean));
        ids.add(tooltipId);
        owner.setAttribute("aria-describedby", Array.from(ids).join(" "));
        tooltip.textContent = label;
        tooltip.hidden = false;
        const anchor = badge.getBoundingClientRect();
        const bounds = tooltip.getBoundingClientRect();
        const width = document.documentElement.clientWidth;
        const height = document.documentElement.clientHeight;
        const left = Math.max(12, Math.min(width - bounds.width - 12, anchor.left + anchor.width / 2 - bounds.width / 2));
        const top = anchor.top - bounds.height - 10 >= 12
            ? anchor.top - bounds.height - 10
            : Math.max(12, Math.min(height - bounds.height - 12, anchor.bottom + 10));
        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${top}px`;
    }

    document.addEventListener("pointerover", (event) => {
        if (event.pointerType === "touch") return;
        if (tooltip?.contains(event.target)) {
            window.clearTimeout(hideTimer);
            return;
        }
        const badge = event.target.closest(selector);
        if (!badge || badge.contains(event.relatedTarget)) return;
        const owner = badge.closest("a, summary") || badge;
        window.clearTimeout(hideTimer);
        window.clearTimeout(hoverTimer);
        pendingOwner = owner;
        hoverTimer = window.setTimeout(() => show(badge, owner), 300);
    });

    document.addEventListener("pointerout", (event) => {
        const owner = active?.owner || pendingOwner;
        if (!owner) return;
        if (active && owner.contains(document.activeElement)) return;
        const next = event.relatedTarget;
        if (next instanceof Node && (owner.contains(next) || tooltip?.contains(next))) return;
        window.clearTimeout(hoverTimer);
        window.clearTimeout(hideTimer);
        hideTimer = window.setTimeout(close, 100);
    });

    document.addEventListener("focusin", (event) => {
        const owner = event.target.closest("a, summary");
        const badge = owner?.matches(selector) ? owner : owner?.querySelector(selector);
        if (badge) show(badge, owner);
        else close();
    });
    document.addEventListener("focusout", (event) => {
        if (active && !active.owner.contains(event.relatedTarget)) close();
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") close();
    });
    document.addEventListener("click", close);
    document.addEventListener("scroll", (event) => {
        if (!tooltip?.contains(event.target)) close();
    }, true);
    window.addEventListener("resize", close);
    window.addEventListener("pagehide", close);
})();
