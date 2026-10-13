(() => {
    const page = document.querySelector(".match-page-v2");
    if (!page) return;

    page.querySelectorAll(".match-v2-tabs a[href^='#']").forEach((link) => {
        link.addEventListener("click", (event) => {
            const target = page.querySelector(link.getAttribute("href"));
            if (!target) return;
            event.preventDefault();
            target.scrollIntoView({ behavior: "smooth", block: "start" });
        });
    });

    const allOdds = page.querySelector("[data-match-v2-odds-all]");
    const revealAllOdds = () => {
        if (!allOdds) return;
        allOdds.hidden = false;
        page.querySelectorAll("[data-match-v2-odds-toggle]").forEach((toggle) => {
            toggle.setAttribute("aria-expanded", "true");
            toggle.textContent = "Скрыть исходы ↑";
        });
    };

    page.querySelectorAll("[data-match-v2-odds-toggle]").forEach((button) => {
        if (!allOdds) return;
        button.addEventListener("click", () => {
            const isOpen = allOdds.hidden;
            if (isOpen) {
                revealAllOdds();
            } else {
                allOdds.hidden = true;
                page.querySelectorAll("[data-match-v2-odds-toggle]").forEach((toggle) => {
                    toggle.setAttribute("aria-expanded", "false");
                    toggle.textContent = "Все исходы →";
                });
            }
            button.setAttribute("aria-expanded", String(isOpen));
        });
    });
})();
