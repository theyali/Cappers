(() => {
    const root = document.querySelector('[data-roulette-root]');
    const canvas = root?.querySelector('[data-roulette-canvas]');
    if (!root || !canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const WIDTH = 940;
    const HEIGHT = 640;
    const CENTER_X = 365;
    const CENTER_Y = 310;
    const WHEEL_RADIUS = 238;
    const SEGMENT_ANGLE = (Math.PI * 2) / 6;
    const TAU = Math.PI * 2;

    const colors = {
        blue: '#0b56fa',
        ink: '#131313',
        panel: '#1f1f21',
        muted: '#707072',
        yellow: '#fbf110',
        white: '#ffffff',
        black: '#0c0c0d',
    };

    const prizes = [
        { title: 'VIP', subtitle: 'на 1 день', icon: 'crown' },
        { title: '+500 ₽', subtitle: 'на баланс', icon: 'coins' },
        { title: '5 бесплатных', subtitle: 'прогнозов', icon: 'ticket' },
        { title: 'Промокод', subtitle: '', icon: 'gift' },
        { title: 'Буст', subtitle: 'рейтинга', icon: 'bars' },
        { title: '1000 ₽', subtitle: 'freebet', icon: 'ball' },
    ];

    const labelRotations = [0, 56, -56, 0, 56, -56].map((value) => value * Math.PI / 180);

    let rotation = 0;
    let spinning = false;
    let selectedPrize = null;
    let statusText = 'Нажми «Крутить», чтобы испытать удачу';
    let countdownText = '--:--:--';

    canvas.style.display = 'block';
    canvas.style.margin = '0 auto';
    canvas.style.maxWidth = '100%';
    canvas.style.cursor = 'pointer';
    canvas.style.touchAction = 'manipulation';

    const roundedRect = (context, x, y, width, height, radius) => {
        const r = Math.min(radius, width / 2, height / 2);
        context.beginPath();
        context.moveTo(x + r, y);
        context.arcTo(x + width, y, x + width, y + height, r);
        context.arcTo(x + width, y + height, x, y + height, r);
        context.arcTo(x, y + height, x, y, r);
        context.arcTo(x, y, x + width, y, r);
        context.closePath();
    };

    const drawText = (text, x, y, size, color, weight = 700, align = 'center') => {
        ctx.fillStyle = color;
        ctx.font = `${weight} ${size}px "Manrope Cappers", Inter, Arial, sans-serif`;
        ctx.textAlign = align;
        ctx.textBaseline = 'middle';
        ctx.fillText(text, x, y);
    };

    const drawCrown = () => {
        ctx.fillStyle = colors.yellow;
        ctx.beginPath();
        ctx.moveTo(-25, -5);
        ctx.lineTo(-15, 17);
        ctx.lineTo(0, 2);
        ctx.lineTo(15, 17);
        ctx.lineTo(25, -5);
        ctx.lineTo(19, 24);
        ctx.lineTo(-19, 24);
        ctx.closePath();
        ctx.fill();
        roundedRect(ctx, -20, 29, 40, 7, 3.5);
        ctx.fill();
    };

    const drawCoins = () => {
        ctx.fillStyle = colors.yellow;
        [-14, -5, 4].forEach((y) => {
            ctx.beginPath();
            ctx.ellipse(0, y, 23, 8, 0, 0, TAU);
            ctx.fill();
            ctx.fillRect(-23, y, 46, 8);
        });
    };

    const drawTicket = () => {
        ctx.fillStyle = colors.yellow;
        ctx.beginPath();
        ctx.moveTo(-31, -18);
        ctx.lineTo(31, -18);
        ctx.lineTo(31, -7);
        ctx.arc(31, 0, 7, -Math.PI / 2, Math.PI / 2, true);
        ctx.lineTo(31, 18);
        ctx.lineTo(-31, 18);
        ctx.lineTo(-31, 7);
        ctx.arc(-31, 0, 7, Math.PI / 2, -Math.PI / 2, true);
        ctx.closePath();
        ctx.fill();
        drawText('1+1', 0, 1, 16, colors.ink, 800);
    };

    const drawGift = () => {
        ctx.fillStyle = colors.yellow;
        roundedRect(ctx, -28, -8, 56, 38, 6);
        ctx.fill();
        ctx.fillStyle = colors.ink;
        ctx.fillRect(-4, -8, 8, 38);
        ctx.fillStyle = colors.yellow;
        ctx.beginPath();
        ctx.moveTo(0, -8);
        ctx.bezierCurveTo(-3, -28, -25, -30, -24, -15);
        ctx.bezierCurveTo(-23, -5, -10, -3, 0, 1);
        ctx.bezierCurveTo(10, -3, 23, -5, 24, -15);
        ctx.bezierCurveTo(25, -30, 3, -28, 0, -8);
        ctx.fill();
    };

    const drawBars = () => {
        ctx.fillStyle = colors.yellow;
        roundedRect(ctx, -29, 5, 14, 29, 3);
        ctx.fill();
        roundedRect(ctx, -7, -10, 14, 44, 3);
        ctx.fill();
        roundedRect(ctx, 15, -28, 14, 62, 3);
        ctx.fill();
    };

    const drawBall = () => {
        ctx.fillStyle = colors.yellow;
        ctx.beginPath();
        ctx.arc(0, 0, 28, 0, TAU);
        ctx.fill();
        ctx.fillStyle = colors.ink;
        ctx.beginPath();
        for (let i = 0; i < 5; i += 1) {
            const angle = -Math.PI / 2 + i * TAU / 5;
            const x = Math.cos(angle) * 10;
            const y = Math.sin(angle) * 10;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.fill();
        for (let i = 0; i < 5; i += 1) {
            const angle = -Math.PI / 2 + i * TAU / 5;
            ctx.beginPath();
            ctx.arc(Math.cos(angle) * 19, Math.sin(angle) * 19, 4, 0, TAU);
            ctx.fill();
        }
    };

    const drawIcon = (icon) => {
        if (icon === 'crown') drawCrown();
        if (icon === 'coins') drawCoins();
        if (icon === 'ticket') drawTicket();
        if (icon === 'gift') drawGift();
        if (icon === 'bars') drawBars();
        if (icon === 'ball') drawBall();
    };

    const drawPanel = () => {
        ctx.fillStyle = colors.ink;
        roundedRect(ctx, 18, 18, 904, 604, 28);
        ctx.fill();
    };

    const drawWheel = () => {
        ctx.save();
        ctx.translate(CENTER_X, CENTER_Y);

        ctx.fillStyle = colors.blue;
        ctx.beginPath();
        ctx.arc(0, 0, WHEEL_RADIUS + 16, 0, TAU);
        ctx.fill();

        ctx.fillStyle = colors.black;
        ctx.beginPath();
        ctx.arc(0, 0, WHEEL_RADIUS + 8, 0, TAU);
        ctx.fill();

        ctx.save();
        ctx.rotate(rotation);

        prizes.forEach((prize, index) => {
            const centerAngle = -Math.PI / 2 + index * SEGMENT_ANGLE;
            const startAngle = centerAngle - SEGMENT_ANGLE / 2;
            const endAngle = centerAngle + SEGMENT_ANGLE / 2;

            ctx.fillStyle = index % 2 === 0 ? colors.panel : colors.blue;
            ctx.beginPath();
            ctx.moveTo(0, 0);
            ctx.arc(0, 0, WHEEL_RADIUS, startAngle, endAngle);
            ctx.closePath();
            ctx.fill();

            const labelRadius = 156;
            const labelX = Math.cos(centerAngle) * labelRadius;
            const labelY = Math.sin(centerAngle) * labelRadius;

            ctx.save();
            ctx.translate(labelX, labelY);
            ctx.rotate(labelRotations[index]);
            ctx.save();
            ctx.translate(0, -34);
            drawIcon(prize.icon);
            ctx.restore();
            drawText(prize.title, 0, 16, prize.title.length > 10 ? 17 : 20, colors.white, 800);
            if (prize.subtitle) drawText(prize.subtitle, 0, 39, 14, colors.white, 700);
            ctx.restore();
        });

        ctx.restore();

        ctx.fillStyle = colors.black;
        ctx.beginPath();
        ctx.arc(0, 0, 98, 0, TAU);
        ctx.fill();

        ctx.fillStyle = colors.blue;
        ctx.beginPath();
        ctx.arc(0, 0, 87, 0, TAU);
        ctx.fill();

        ctx.strokeStyle = colors.white;
        ctx.lineWidth = 7;
        ctx.lineCap = 'round';
        ctx.beginPath();
        ctx.arc(0, -16, 28, Math.PI * 1.15, Math.PI * 1.88);
        ctx.stroke();

        ctx.fillStyle = colors.white;
        ctx.beginPath();
        ctx.moveTo(24, -40);
        ctx.lineTo(35, -19);
        ctx.lineTo(12, -18);
        ctx.closePath();
        ctx.fill();

        drawText(spinning ? 'Крутим' : 'Крутить', 0, 28, 25, colors.white, 800);
        ctx.restore();
    };

    const drawPointer = () => {
        ctx.fillStyle = colors.yellow;
        ctx.beginPath();
        ctx.moveTo(CENTER_X, 43);
        ctx.lineTo(CENTER_X + 31, 93);
        ctx.lineTo(CENTER_X - 31, 93);
        ctx.closePath();
        ctx.fill();
    };

    const drawInfo = () => {
        drawText('МАЛЕНЬКИЕ БОНУСЫ', 665, 116, 15, colors.muted, 800, 'left');
        drawText('БОЛЬШИМ ПОБЕДАМ', 665, 142, 18, colors.blue, 800, 'left');

        ctx.fillStyle = colors.panel;
        roundedRect(ctx, 650, 210, 236, 172, 18);
        ctx.fill();

        drawText('ДЕМО-РЕЖИМ', 674, 238, 12, colors.yellow, 800, 'left');
        drawText(selectedPrize ? 'ТВОЙ ПРИЗ' : 'ЕЖЕДНЕВНЫЙ ШАНС', 674, 270, 14, colors.muted, 800, 'left');

        if (selectedPrize) {
            drawText(selectedPrize.title, 674, 305, selectedPrize.title.length > 12 ? 20 : 25, colors.white, 800, 'left');
            if (selectedPrize.subtitle) drawText(selectedPrize.subtitle, 674, 334, 16, colors.white, 700, 'left');
        } else {
            drawText('6 возможных призов', 674, 306, 21, colors.white, 800, 'left');
            drawText('1 вращение каждый день', 674, 337, 15, colors.white, 700, 'left');
        }

        drawText('Начисление подключим позже', 674, 362, 12, colors.muted, 700, 'left');

        ctx.fillStyle = colors.blue;
        roundedRect(ctx, 650, 412, 236, 94, 18);
        ctx.fill();
        drawText('СЛЕДУЮЩАЯ ПОПЫТКА', 674, 437, 12, colors.white, 800, 'left');
        drawText(countdownText, 674, 472, 29, colors.white, 800, 'left');
    };

    const drawFooter = () => {
        ctx.save();
        ctx.translate(72, 575);
        drawGift();
        ctx.restore();
        drawText('1 бесплатное вращение каждый день', 112, 578, 16, colors.white, 800, 'left');
        drawText(statusText, 470, 606, 13, colors.muted, 700, 'center');
    };

    const draw = () => {
        ctx.clearRect(0, 0, WIDTH, HEIGHT);
        drawPanel();
        drawWheel();
        drawPointer();
        drawInfo();
        drawFooter();
    };

    const setCanvasSize = () => {
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const availableWidth = Math.max(220, root.clientWidth - 48);
        const displayWidth = Math.min(WIDTH, availableWidth);
        const displayHeight = Math.round(displayWidth * HEIGHT / WIDTH);

        canvas.style.width = `${displayWidth}px`;
        canvas.style.height = `${displayHeight}px`;
        canvas.width = Math.round(WIDTH * dpr);
        canvas.height = Math.round(HEIGHT * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        draw();
    };

    const normalizeDegrees = (value) => ((value % 360) + 360) % 360;
    const easeOutQuint = (value) => 1 - Math.pow(1 - value, 5);

    const spin = () => {
        if (spinning) return;

        spinning = true;
        selectedPrize = null;
        statusText = 'Рулетка крутится…';
        canvas.setAttribute('aria-disabled', 'true');

        const prizeIndex = Math.floor(Math.random() * prizes.length);
        const landingJitter = (Math.random() * 28) - 14;
        const currentDegrees = normalizeDegrees(rotation * 180 / Math.PI);
        const targetDegrees = normalizeDegrees(-prizeIndex * 60 + landingJitter);
        const delta = normalizeDegrees(targetDegrees - currentDegrees);
        const startDegrees = rotation * 180 / Math.PI;
        const endDegrees = startDegrees + 6 * 360 + delta;
        const duration = 4300;
        const startedAt = performance.now();

        const animate = (now) => {
            const progress = Math.min((now - startedAt) / duration, 1);
            const eased = easeOutQuint(progress);
            const degrees = startDegrees + (endDegrees - startDegrees) * eased;
            rotation = degrees * Math.PI / 180;
            draw();

            if (progress < 1) {
                requestAnimationFrame(animate);
                return;
            }

            rotation = normalizeDegrees(endDegrees) * Math.PI / 180;
            spinning = false;
            selectedPrize = prizes[prizeIndex];
            statusText = `Выпало: ${selectedPrize.title}${selectedPrize.subtitle ? ` — ${selectedPrize.subtitle}` : ''}`;
            canvas.removeAttribute('aria-disabled');
            canvas.setAttribute('aria-label', `${statusText}. Демо-режим, приз пока не начисляется.`);
            draw();
        };

        requestAnimationFrame(animate);
    };

    const eventPoint = (event) => {
        const rect = canvas.getBoundingClientRect();
        return {
            x: (event.clientX - rect.left) * WIDTH / rect.width,
            y: (event.clientY - rect.top) * HEIGHT / rect.height,
        };
    };

    canvas.addEventListener('click', (event) => {
        const point = eventPoint(event);
        const distance = Math.hypot(point.x - CENTER_X, point.y - CENTER_Y);
        if (distance <= 105) spin();
    });

    canvas.addEventListener('mousemove', (event) => {
        const point = eventPoint(event);
        const distance = Math.hypot(point.x - CENTER_X, point.y - CENTER_Y);
        canvas.style.cursor = distance <= 105 && !spinning ? 'pointer' : 'default';
    });

    canvas.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        spin();
    });

    const updateCountdown = () => {
        const now = new Date();
        const nextAttempt = new Date(now);
        nextAttempt.setHours(24, 0, 0, 0);
        const secondsLeft = Math.max(0, Math.floor((nextAttempt - now) / 1000));
        const hours = Math.floor(secondsLeft / 3600);
        const minutes = Math.floor((secondsLeft % 3600) / 60);
        const seconds = secondsLeft % 60;
        countdownText = [hours, minutes, seconds]
            .map((value) => String(value).padStart(2, '0'))
            .join(':');
        draw();
    };

    let resizeFrame = 0;
    const resize = () => {
        cancelAnimationFrame(resizeFrame);
        resizeFrame = requestAnimationFrame(setCanvasSize);
    };

    if ('ResizeObserver' in window) {
        const observer = new ResizeObserver(resize);
        observer.observe(root);
    } else {
        window.addEventListener('resize', resize);
    }

    setCanvasSize();
    updateCountdown();
    window.setInterval(updateCountdown, 1000);
})();
