(() => {
    const tabs = document.querySelector(".matches-page .matches-tabs");
    if (!tabs) return;

    const script = document.querySelector("script[data-match-date-filter]");
    const params = new URLSearchParams(window.location.search);
    const activeScope = params.get("scope") || "all";

    const pad = (value) => String(value).padStart(2, "0");
    const toIso = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;

    const fromIso = (value) => {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "")) return null;
        const [year, month, day] = value.split("-").map(Number);
        const date = new Date(year, month - 1, day);
        if (
            date.getFullYear() !== year
            || date.getMonth() !== month - 1
            || date.getDate() !== day
        ) return null;
        return date;
    };

    const browserToday = new Date();
    browserToday.setHours(0, 0, 0, 0);
    const today = fromIso(script?.dataset.todayDate) || browserToday;
    const selectedDate = (
        fromIso(params.get("date"))
        || fromIso(script?.dataset.selectedDate)
        || new Date(today)
    );
    const selectedIso = toIso(selectedDate);

    const moveDate = (date, days) => {
        const next = new Date(date);
        next.setDate(next.getDate() + days);
        return next;
    };

    const dayMonthFormatter = new Intl.DateTimeFormat("ru-RU", {
        day: "numeric",
        month: "short",
    });
    const longDateFormatter = new Intl.DateTimeFormat("ru-RU", {
        weekday: "long",
        day: "numeric",
        month: "long",
    });

    const buildHref = (date, scope = activeScope) => {
        const query = new URLSearchParams();
        query.set("scope", scope);
        query.set("date", toIso(date));
        return `${window.location.pathname}?${query.toString()}`;
    };

    const calendarIcon = `
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M7 3v3M17 3v3M4.5 9h15M6 5h12a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
        </svg>`;
    const leftIcon = `
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="m14.5 6-6 6 6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>`;
    const rightIcon = `
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="m9.5 6 6 6-6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>`;

    const filter = document.createElement("section");
    filter.className = "matches-date-filter";
    filter.setAttribute("aria-label", "Фильтр матчей по дате");

    const current = document.createElement("div");
    current.className = "matches-date-current";
    current.innerHTML = `
        <span class="matches-date-current-icon">${calendarIcon}</span>
        <span class="matches-date-current-copy">
            <span>Матчи по дате</span>
            <strong>${longDateFormatter.format(selectedDate)}</strong>
        </span>`;

    const controls = document.createElement("div");
    controls.className = "matches-date-controls";

    const previous = document.createElement("a");
    previous.className = "matches-date-step";
    previous.href = buildHref(moveDate(selectedDate, -1));
    previous.setAttribute("aria-label", "Предыдущий день");
    previous.title = "Предыдущий день";
    previous.innerHTML = leftIcon;

    const shortcuts = document.createElement("div");
    shortcuts.className = "matches-date-shortcuts";

    [
        { label: "Вчера", date: moveDate(today, -1) },
        { label: "Сегодня", date: today },
        { label: "Завтра", date: moveDate(today, 1) },
    ].forEach((item) => {
        const link = document.createElement("a");
        link.className = "matches-date-option";
        if (toIso(item.date) === selectedIso) link.classList.add("is-active");
        link.href = buildHref(item.date);

        const label = document.createElement("span");
        label.textContent = item.label;
        const dateLabel = document.createElement("small");
        dateLabel.textContent = dayMonthFormatter.format(item.date);
        link.append(label, dateLabel);
        shortcuts.append(link);
    });

    const next = document.createElement("a");
    next.className = "matches-date-step";
    next.href = buildHref(moveDate(selectedDate, 1));
    next.setAttribute("aria-label", "Следующий день");
    next.title = "Следующий день";
    next.innerHTML = rightIcon;

    const picker = document.createElement("label");
    picker.className = "matches-date-picker";
    picker.innerHTML = `${calendarIcon}<span>Календарь</span>`;
    const dateInput = document.createElement("input");
    dateInput.type = "date";
    dateInput.value = selectedIso;
    dateInput.setAttribute("aria-label", "Выбрать дату матчей");
    dateInput.addEventListener("change", () => {
        const date = fromIso(dateInput.value);
        if (date) window.location.assign(buildHref(date));
    });
    picker.append(dateInput);

    controls.append(previous, shortcuts, next, picker);
    filter.append(current, controls);
    tabs.insertAdjacentElement("afterend", filter);

    tabs.querySelectorAll("a").forEach((link) => {
        const url = new URL(link.href, window.location.href);
        url.searchParams.set("date", selectedIso);
        link.href = `${url.pathname}?${url.searchParams.toString()}`;
    });

    const heroMetaLabel = document.querySelector(".matches-hero-meta small");
    if (heroMetaLabel) {
        heroMetaLabel.textContent = `игр на ${dayMonthFormatter.format(selectedDate)}`;
    }

    const emptyText = document.querySelector(".matches-empty p");
    if (emptyText) {
        emptyText.textContent = `На ${dayMonthFormatter.format(selectedDate)} матчей в этой вкладке нет.`;
    }
})();
