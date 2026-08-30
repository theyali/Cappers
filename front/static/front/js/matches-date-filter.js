(() => {
    const dateInputs = document.querySelectorAll("[data-match-date-input]");
    if (!dateInputs.length) return;

    const navigateToDate = (dateInput) => {
        if (!dateInput.value) return;

        if (dateInput.dataset.urlTemplate) {
            window.location.assign(
                dateInput.dataset.urlTemplate.replace("__DATE__", encodeURIComponent(dateInput.value)),
            );
            return;
        }

        const query = new URLSearchParams(window.location.search);
        query.set("scope", dateInput.dataset.scope || "all");
        query.set("date", dateInput.value);
        query.delete("page");
        query.delete("lazy");
        query.delete("window");

        window.location.assign(`${window.location.pathname}?${query.toString()}`);
    };

    dateInputs.forEach((dateInput) => {
        dateInput.addEventListener("change", () => navigateToDate(dateInput));
    });
})();
