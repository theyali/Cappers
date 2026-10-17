(() => {
    const updateFixedRouletteBadge = (rawCount) => {
        const count = Math.max(0, Number(rawCount) || 0);

        document.querySelectorAll('[data-fixed-roulette]').forEach((fixedRoulette) => {
            fixedRoulette.dataset.rouletteAvailableSpins = String(count);
            let badge = fixedRoulette.querySelector('[data-roulette-badge]');

            if (count > 0) {
                if (!badge) {
                    badge = document.createElement('span');
                    badge.className = 'nav-notification-badge';
                    badge.dataset.rouletteBadge = '';
                    fixedRoulette.appendChild(badge);
                }
                badge.textContent = String(count);
                fixedRoulette.setAttribute(
                    'aria-label',
                    `Ежедневная рулетка. Доступно попыток: ${count}`,
                );
                return;
            }

            badge?.remove();
            fixedRoulette.setAttribute('aria-label', 'Ежедневная рулетка');
        });
    };

    const init = () => {
        const initial = document.querySelector('[data-fixed-roulette]');
        if (initial) updateFixedRouletteBadge(initial.dataset.rouletteAvailableSpins);
    };

    window.addEventListener('cappers:roulette-attempts', (event) => {
        updateFixedRouletteBadge(event.detail?.availableSpins);
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
        return;
    }

    init();
})();
