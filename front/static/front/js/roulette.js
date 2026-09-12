(() => {
    const root = document.querySelector('[data-roulette-root]');
    if (!root) return;

    const rotor = root.querySelector('[data-roulette-rotor]');
    const spinButton = root.querySelector('[data-roulette-spin]');
    const countdown = root.querySelector('[data-roulette-countdown]');
    const result = root.querySelector('[data-roulette-result]');

    if (!rotor || !spinButton) return;

    const prizes = [
        'VIP на 1 день',
        '+500 ₽ на виртуальный баланс',
        '5 бесплатных прогнозов',
        'Промокод',
        'Буст рейтинга',
        '1000 ₽ freebet',
    ];

    let rotation = 0;
    let spinning = false;

    const normalize = (angle) => ((angle % 360) + 360) % 360;
    const easeOutQuint = (value) => 1 - Math.pow(1 - value, 5);

    const setRotation = (angle) => {
        rotor.setAttribute('transform', `rotate(${angle} 470 350)`);
    };

    const spin = () => {
        if (spinning) return;

        spinning = true;
        spinButton.setAttribute('aria-disabled', 'true');
        if (result) result.textContent = 'Рулетка крутится…';

        const prizeIndex = Math.floor(Math.random() * prizes.length);
        const targetAngle = normalize(330 - prizeIndex * 60);
        const currentAngle = normalize(rotation);
        const offset = normalize(targetAngle - currentAngle);
        const startRotation = rotation;
        const endRotation = rotation + 5 * 360 + offset;
        const duration = 3300;
        const startedAt = performance.now();

        const animate = (now) => {
            const progress = Math.min((now - startedAt) / duration, 1);
            rotation = startRotation + (endRotation - startRotation) * easeOutQuint(progress);
            setRotation(rotation);

            if (progress < 1) {
                requestAnimationFrame(animate);
                return;
            }

            rotation = normalize(endRotation);
            setRotation(rotation);
            spinning = false;
            spinButton.removeAttribute('aria-disabled');

            if (result) {
                result.textContent = `Демо: выпало «${prizes[prizeIndex]}». Приз пока не начисляется.`;
            }
        };

        requestAnimationFrame(animate);
    };

    spinButton.addEventListener('click', spin);
    spinButton.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        spin();
    });

    if (countdown) {
        let secondsLeft = 23 * 60 * 60 + 41 * 60 + 12;

        const renderCountdown = () => {
            const hours = Math.floor(secondsLeft / 3600);
            const minutes = Math.floor((secondsLeft % 3600) / 60);
            const seconds = secondsLeft % 60;
            countdown.textContent = [hours, minutes, seconds]
                .map((value) => String(value).padStart(2, '0'))
                .join(':');
            secondsLeft = secondsLeft > 0 ? secondsLeft - 1 : 24 * 60 * 60 - 1;
        };

        renderCountdown();
        window.setInterval(renderCountdown, 1000);
    }
})();
