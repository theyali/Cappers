(() => {
    const pad = (value) => String(value).padStart(2, "0");

    const formatRemaining = (milliseconds) => {
        if (milliseconds <= 0) return "";
        const totalSeconds = Math.floor(milliseconds / 1000);
        const days = Math.floor(totalSeconds / 86400);
        const hours = Math.floor((totalSeconds % 86400) / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = totalSeconds % 60;
        if (days > 0) {
            return `${days} д ${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
        }
        return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
    };

    const timers = Array.from(document.querySelectorAll("[data-countdown-target]"))
        .map((node) => ({
            node,
            target: new Date(node.dataset.countdownTarget),
            expired: node.dataset.countdownExpired || "Завершено",
        }))
        .filter((timer) => !Number.isNaN(timer.target.getTime()));

    if (!timers.length) return;

    const tick = () => {
        const now = Date.now();
        timers.forEach((timer) => {
            const remaining = timer.target.getTime() - now;
            timer.node.textContent = remaining > 0 ? formatRemaining(remaining) : timer.expired;
        });
    };

    tick();
    window.setInterval(tick, 1000);
})();
