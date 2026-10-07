(() => {
    const card = document.querySelector("[data-payment-status]");
    if (!card || card.dataset.paymentState !== "pending") return;

    const title = card.querySelector("[data-payment-status-title]");
    const text = card.querySelector("[data-payment-status-text]");
    const retry = card.querySelector("[data-payment-status-retry]");
    const pollDelay = 3000;
    const maxPolls = 100;
    let polls = 0;

    const render = (status) => {
        card.dataset.paymentState = status.state;
        if (title) title.textContent = status.title;
        if (text) text.textContent = status.text;
        if (retry) {
            retry.hidden = !status.retry_url;
            if (status.retry_url) retry.href = status.retry_url;
        }
    };

    const poll = async () => {
        polls += 1;
        try {
            const response = await fetch(card.dataset.paymentStatusUrl, {
                headers: { Accept: "application/json" },
                credentials: "same-origin",
            });
            if (response.ok) render(await response.json());
        } catch (error) {
            // A dropped request is retried on the next tick.
        }
        if (card.dataset.paymentState !== "pending") return;
        if (polls >= maxPolls) {
            if (text) text.textContent = card.dataset.paymentStatusTimeoutText;
            return;
        }
        window.setTimeout(poll, pollDelay);
    };

    window.setTimeout(poll, pollDelay);
})();
