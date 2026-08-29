(() => {
    const root = document.querySelector("[data-expert-monthly-stats]");
    if (!root) return;

    const button = root.querySelector("[data-monthly-more]");
    if (!button) return;

    const hiddenRows = Array.from(root.querySelectorAll("[data-monthly-row].is-monthly-hidden"));
    const label = button.querySelector("[data-monthly-more-label]");

    button.addEventListener("click", () => {
        const expanded = button.getAttribute("aria-expanded") === "true";
        const nextExpanded = !expanded;
        button.setAttribute("aria-expanded", String(nextExpanded));
        hiddenRows.forEach((row) => row.classList.toggle("is-monthly-hidden", !nextExpanded));
        if (label) label.textContent = nextExpanded ? "Свернуть" : "Показать ещё";

        if (!nextExpanded) {
            root.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
    });
})();
