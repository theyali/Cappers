(() => {
    const dateInputs = document.querySelectorAll("[data-match-date-input]");
    if (!dateInputs.length) return;

    const navigateToDate = (dateInput) => {
        if (!dateInput.value) return;

        if (dateInput.dataset.urlTemplate) {
            const nextUrl = dateInput.dataset.urlTemplate.replace("__DATE__", encodeURIComponent(dateInput.value));
            if (window.CappersMatchesFilterAjax?.go) {
                window.CappersMatchesFilterAjax.go(nextUrl);
            } else {
                window.location.assign(nextUrl);
            }
            return;
        }

        const query = new URLSearchParams(window.location.search);
        query.set("scope", dateInput.dataset.scope || "all");
        query.set("date", dateInput.value);
        query.delete("page");
        query.delete("lazy");
        query.delete("window");

        const nextUrl = `${window.location.pathname}?${query.toString()}`;
        if (window.CappersMatchesFilterAjax?.go) {
            window.CappersMatchesFilterAjax.go(nextUrl);
        } else {
            window.location.assign(nextUrl);
        }
    };

    dateInputs.forEach((dateInput) => {
        dateInput.addEventListener("change", () => navigateToDate(dateInput));
    });
})();
