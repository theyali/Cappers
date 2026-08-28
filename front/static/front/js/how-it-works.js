(() => {
    const root = document.querySelector("[data-how-page]");
    if (!root) return;

    const buttons = Array.from(root.querySelectorAll("[data-how-tab]"));
    const panels = Array.from(root.querySelectorAll("[data-how-panel]"));

    const activate = (key) => {
        buttons.forEach((button) => {
            const isActive = button.dataset.howTab === key;
            button.classList.toggle("is-active", isActive);
            button.setAttribute("aria-selected", isActive ? "true" : "false");
            button.tabIndex = isActive ? 0 : -1;
        });

        panels.forEach((panel) => {
            const isActive = panel.dataset.howPanel === key;
            panel.classList.toggle("is-active", isActive);
            panel.hidden = !isActive;
        });

        const url = new URL(window.location.href);
        if (key === "expert") url.searchParams.set("for", "expert");
        else url.searchParams.delete("for");
        window.history.replaceState({}, "", url);
    };

    buttons.forEach((button) => {
        button.addEventListener("click", () => activate(button.dataset.howTab));
        button.addEventListener("keydown", (event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            const index = buttons.indexOf(button);
            const direction = event.key === "ArrowRight" ? 1 : -1;
            const next = buttons[(index + direction + buttons.length) % buttons.length];
            next.focus();
            activate(next.dataset.howTab);
        });
    });

    root.querySelectorAll(".how-jump-nav a[href^='#']").forEach((link) => {
        link.addEventListener("click", (event) => {
            const id = link.getAttribute("href")?.slice(1);
            if (!id) return;
            const target = document.getElementById(id);
            if (!target) return;

            event.preventDefault();
            const panel = target.closest("[data-how-panel]");
            if (panel) activate(panel.dataset.howPanel);

            window.requestAnimationFrame(() => {
                target.scrollIntoView({ behavior: "smooth", block: "start" });
                const url = new URL(window.location.href);
                url.hash = id;
                window.history.replaceState({}, "", url);
            });
        });
    });

    const params = new URLSearchParams(window.location.search);
    const hashId = window.location.hash ? decodeURIComponent(window.location.hash.slice(1)) : "";
    const hashTarget = hashId ? document.getElementById(hashId) : null;
    const hashPanel = hashTarget?.closest("[data-how-panel]");
    activate(hashPanel?.dataset.howPanel || (params.get("for") === "expert" ? "expert" : "reader"));
})();
