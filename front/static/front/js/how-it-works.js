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
        if (key === "experts") url.searchParams.set("for", "experts");
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

    const params = new URLSearchParams(window.location.search);
    activate(params.get("for") === "experts" ? "experts" : "users");
})();
