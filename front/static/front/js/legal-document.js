(() => {
    const root = document.querySelector("[data-legal-document]");
    if (!root) return;
    const sections = Array.from(root.querySelectorAll("[data-document-section]"));
    const links = Array.from(root.querySelectorAll("[data-document-link]"));
    const current = root.querySelector("[data-document-current]");
    const mobileToc = root.querySelector("[data-document-mobile-toc]");
    const previous = root.querySelector("[data-document-previous]");
    const next = root.querySelector("[data-document-next]");
    let active = -1;
    const select = (index) => {
        if (index === active || !sections[index]) return;
        active = index;
        links.forEach((link) => {
            const selected = link.dataset.documentLink === sections[index].id;
            link.classList.toggle("is-active", selected);
            if (selected) link.setAttribute("aria-current", "location");
            else link.removeAttribute("aria-current");
        });
        if (current) current.textContent = sections[index].dataset.documentTitle;
        if (previous) {
            previous.hidden = index === 0;
            previous.href = "#" + sections[Math.max(0, index - 1)].id;
        }
        if (next) {
            next.hidden = index === sections.length - 1;
            next.href = "#" + sections[Math.min(sections.length - 1, index + 1)].id;
        }
    };
    const update = () => {
        let index = 0;
        sections.forEach((section, candidate) => {
            if (section.getBoundingClientRect().top <= 160) index = candidate;
        });
        select(index);
    };
    let scheduled = false;
    window.addEventListener("scroll", () => {
        if (scheduled) return;
        scheduled = true;
        window.requestAnimationFrame(() => { update(); scheduled = false; });
    }, { passive: true });
    window.addEventListener("hashchange", update);
    window.addEventListener("pageshow", update);
    links.forEach((link) => link.addEventListener("click", () => {
        if (mobileToc) mobileToc.open = false;
        const index = sections.findIndex((section) => section.id === link.dataset.documentLink);
        select(index);
    }));
    document.addEventListener("cookie-consent:changed", () => {
        const status = root.querySelector("[data-document-cookie-status]");
        if (status) status.textContent = status.dataset.savedLabel;
    });
    update();
})();
