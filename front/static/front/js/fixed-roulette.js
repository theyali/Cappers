(() => {
    const initFixedRouletteHover = () => {
        document.querySelectorAll('.fixed-roulette').forEach((fixedRoulette) => {
            if (fixedRoulette.dataset.hoverSpinReady === '1') return;
            fixedRoulette.dataset.hoverSpinReady = '1';

            const spinTarget = fixedRoulette.querySelector('[data-fixed-roulette-wheel], img, svg, canvas') || fixedRoulette;
            const restingBottom = fixedRoulette.style.bottom;
            const restingLeft = fixedRoulette.style.left;
            const restingScale = fixedRoulette.style.scale;
            const currentTransition = fixedRoulette.style.transition;
            const hoverTransition = [
                'bottom 420ms cubic-bezier(0.22, 1, 0.36, 1)',
                'left 420ms cubic-bezier(0.22, 1, 0.36, 1)',
                'scale 420ms cubic-bezier(0.22, 1, 0.36, 1)',
            ].join(', ');

            fixedRoulette.style.transition = currentTransition
                ? `${currentTransition}, ${hoverTransition}`
                : hoverTransition;

            let hovering = false;
            let frameId = null;
            let previousTime = 0;
            let angle = 0;
            let speed = 0;

            const animateSpin = (now) => {
                if (!previousTime) previousTime = now;
                const delta = Math.min((now - previousTime) / 1000, 0.05);
                previousTime = now;

                const targetSpeed = hovering ? 180 : 0;
                const smoothing = 1 - Math.exp(-8 * delta);
                speed += (targetSpeed - speed) * smoothing;
                angle = (angle + speed * delta) % 360;
                spinTarget.style.rotate = `${angle}deg`;

                if (hovering || speed > 0.15) {
                    frameId = requestAnimationFrame(animateSpin);
                    return;
                }

                speed = 0;
                previousTime = 0;
                frameId = null;
            };

            const ensureSpin = () => {
                if (!frameId) frameId = requestAnimationFrame(animateSpin);
            };

            fixedRoulette.addEventListener('mouseenter', () => {
                hovering = true;
                fixedRoulette.style.bottom = '45px';
                fixedRoulette.style.left = '42px';
                fixedRoulette.style.scale = '2';
                ensureSpin();
            });

            fixedRoulette.addEventListener('mouseleave', () => {
                hovering = false;
                fixedRoulette.style.bottom = restingBottom;
                fixedRoulette.style.left = restingLeft;
                fixedRoulette.style.scale = restingScale;
                ensureSpin();
            });
        });
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initFixedRouletteHover, { once: true });
        return;
    }

    initFixedRouletteHover();
})();
