(() => {
    const source = document.querySelector("[data-public-presence-source]");
    const username = document.querySelector(".expert-public-username");
    if (!source || !username) return;

    const status = document.createElement("span");
    status.className = "public-presence-status";
    const online = source.dataset.online === "1";
    if (online) status.classList.add("is-online");

    const dot = document.createElement("span");
    dot.className = "public-presence-dot";
    dot.setAttribute("aria-hidden", "true");

    const label = document.createElement("span");
    label.textContent = source.dataset.label || "Нет данных о последней активности";

    status.append(dot, label);
    username.insertAdjacentElement("afterend", status);
})();
