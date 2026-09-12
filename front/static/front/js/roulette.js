(() => {
    const root = document.querySelector('[data-roulette-root]');
    const canvas = root?.querySelector('[data-roulette-canvas]');
    if (!root || !canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const W = 720;
    const H = 720;
    const TAU = Math.PI * 2;
    const cx = 360;
    const cy = 365;
    const radius = 286;
    const innerRadius = 95;
    const slice = TAU / 8;
    const colors = {
        blue: '#0b56fa',
        ink: '#131313',
        panel: '#1f1f21',
        muted: '#707072',
        yellow: '#fbf110',
        white: '#ffffff',
    };
    const iconSrc = (index) => root.getAttribute(`data-roulette-icon-${index}`);

    const prizes = [
        { title: '+500 ₽', sub: ['на виртуальный', 'баланс'], icon: iconSrc(1) },
        { title: 'VIP', sub: ['на 1 день'], icon: iconSrc(2) },
        { title: '5 бесплатных', sub: ['прогнозов'], icon: iconSrc(3) },
        { title: '1000 ₽', sub: ['бонус'], icon: iconSrc(4) },
        { title: 'Буст', sub: ['рейтинга'], icon: iconSrc(5) },
        { title: 'Промокод', sub: [], icon: iconSrc(6) },
        { title: 'Попытка', sub: ['завтра'], icon: iconSrc(7) },
        { title: 'Скидка 20%', sub: ['на VIP'], icon: iconSrc(8) },
    ];

    const images = new Map();
    let rotation = 0;
    let spinning = false;
    let demoIndex = 0;

    canvas.style.display = 'block';
    canvas.style.margin = '0 auto';
    canvas.style.maxWidth = '100%';
    canvas.style.cursor = 'pointer';
    canvas.style.touchAction = 'manipulation';

    root.style.backgroundImage = `linear-gradient(271deg, rgba(3, 10, 24, 0.18) 0%, rgba(3, 8, 18, 0.38) 55%, rgba(2, 6, 14, 0.72) 100%), url("${root.dataset.rouletteBg}")`;
    root.style.backgroundPosition = 'center';
    root.style.backgroundSize = 'cover';
    root.style.backgroundRepeat = 'no-repeat';

    const text = (value, x, y, size, color, weight = 700, align = 'center') => {
        ctx.fillStyle = color;
        ctx.font = `${weight} ${size}px "Manrope Cappers", Inter, Arial, sans-serif`;
        ctx.textAlign = align;
        ctx.textBaseline = 'middle';
        ctx.fillText(value, x, y);
    };

    const loadImage = (src) => new Promise((resolve) => {
        if (!src) return resolve(null);
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => resolve(null);
        image.src = src;
    });

    const prepare = async () => {
        window.CappersSkeleton?.loading(root);
        const loaded = await Promise.all(prizes.map((item) => loadImage(item.icon)));
        loaded.forEach((image, index) => {
            if (image) images.set(prizes[index].icon, image);
        });
        window.CappersSkeleton?.ready(root);
    };

    const drawRing = () => {
        ctx.save();
        ctx.translate(cx, cy);
        ctx.shadowColor = 'rgba(62,122,255,.72)';
        ctx.shadowBlur = 28;
        ctx.strokeStyle = 'rgba(49,101,213,.36)';
        ctx.lineWidth = 18;
        ctx.beginPath();
        ctx.arc(0, 0, radius + 24, 0, TAU);
        ctx.stroke();
        ctx.shadowBlur = 0;
        ctx.strokeStyle = '#1b2637';
        ctx.lineWidth = 17;
        ctx.beginPath();
        ctx.arc(0, 0, radius + 20, 0, TAU);
        ctx.stroke();
        ctx.strokeStyle = colors.blue;
        ctx.lineWidth = 4;
        ctx.beginPath();
        ctx.arc(0, 0, radius + 9, 0, TAU);
        ctx.stroke();

        for (let i = 0; i < 16; i += 1) {
            const angle = -Math.PI / 2 + i * TAU / 16;
            const r = radius + 24;
            ctx.save();
            ctx.shadowColor = '#fff';
            ctx.shadowBlur = 11;
            ctx.fillStyle = '#f7fbff';
            ctx.beginPath();
            ctx.arc(Math.cos(angle) * r, Math.sin(angle) * r, 4, 0, TAU);
            ctx.fill();
            ctx.restore();
        }
        ctx.restore();
    };

    const drawWheel = () => {
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(rotation);
        prizes.forEach((item, index) => {
            const mid = -Math.PI / 2 + index * slice;
            const start = mid - slice / 2;
            const end = mid + slice / 2;
            const fill = ctx.createRadialGradient(0, 0, 70, 0, 0, radius);

            if (index % 2 === 0) {
                fill.addColorStop(0, '#18243a');
                fill.addColorStop(1, '#0d1727');
            } else {
                fill.addColorStop(0, '#123d92');
                fill.addColorStop(1, colors.blue);
            }

            ctx.fillStyle = fill;
            ctx.beginPath();
            ctx.moveTo(0, 0);
            ctx.arc(0, 0, radius, start, end);
            ctx.closePath();
            ctx.fill();
            ctx.strokeStyle = '#08101c';
            ctx.lineWidth = 2;
            ctx.stroke();
        });
        ctx.restore();

        const labelRadius = 205;
        prizes.forEach((item, index) => {
            const angle = -Math.PI / 2 + index * slice + rotation;
            const x = cx + Math.cos(angle) * labelRadius;
            const y = cy + Math.sin(angle) * labelRadius;
            const image = images.get(item.icon);

            if (image) ctx.drawImage(image, x - 27, y - 57, 54, 54);
            text(item.title, x, y + 12, item.title.length > 11 ? 16 : 20, colors.white, 800);
            item.sub.forEach((line, i) => {
                text(line, x, y + 37 + i * 18, 14, 'rgba(255,255,255,.88)', 700);
            });
        });
    };

    const drawCenter = () => {
        ctx.save();
        ctx.translate(cx, cy);
        ctx.fillStyle = '#07111f';
        ctx.beginPath();
        ctx.arc(0, 0, innerRadius + 13, 0, TAU);
        ctx.fill();

        const fill = ctx.createRadialGradient(-24, -34, 12, 0, 0, innerRadius);
        fill.addColorStop(0, '#397fff');
        fill.addColorStop(.6, colors.blue);
        fill.addColorStop(1, '#0844c8');
        ctx.fillStyle = fill;
        ctx.beginPath();
        ctx.arc(0, 0, innerRadius, 0, TAU);
        ctx.fill();

        ctx.strokeStyle = 'rgba(255,255,255,.28)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(0, 0, innerRadius - 3, 0, TAU);
        ctx.stroke();

        ctx.strokeStyle = colors.white;
        ctx.lineWidth = 5;
        ctx.lineCap = 'round';
        ctx.beginPath();
        ctx.arc(0, -20, 24, Math.PI * 1.12, Math.PI * 1.86);
        ctx.stroke();

        ctx.fillStyle = colors.white;
        ctx.beginPath();
        ctx.moveTo(20, -43);
        ctx.lineTo(31, -24);
        ctx.lineTo(10, -22);
        ctx.closePath();
        ctx.fill();

        text(spinning ? 'Крутим…' : 'Крутить', 0, 28, 26, colors.white, 800);
        ctx.restore();
    };

    const drawPointer = () => {
        ctx.save();
        ctx.shadowColor = 'rgba(251,241,16,.55)';
        ctx.shadowBlur = 18;
        ctx.fillStyle = colors.yellow;
        ctx.beginPath();
        ctx.moveTo(cx, cy - radius - 50);
        ctx.lineTo(cx + 27, cy - radius - 2);
        ctx.lineTo(cx - 27, cy - radius - 2);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
    };

    const draw = () => {
        ctx.clearRect(0, 0, W, H);
        drawRing();
        drawWheel();
        drawCenter();
        drawPointer();
    };

    const resize = () => {
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const width = Math.min(W, Math.max(260, root.clientWidth - 40));
        canvas.style.width = `${width}px`;
        canvas.style.height = `${Math.round(width * H / W)}px`;
        canvas.width = Math.round(W * dpr);
        canvas.height = Math.round(H * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        draw();
    };

    const ease = (value) => 1 - Math.pow(1 - value, 5);

    const spin = () => {
        if (spinning) return;
        spinning = true;
        demoIndex = (demoIndex + 3) % prizes.length;
        const start = rotation;
        const finish = rotation + TAU * 5 + slice * 3;
        const started = performance.now();
        const duration = 4300;

        const frame = (now) => {
            const progress = Math.min((now - started) / duration, 1);
            rotation = start + (finish - start) * ease(progress);
            draw();

            if (progress < 1) return requestAnimationFrame(frame);
            rotation = finish % TAU;
            spinning = false;
            draw();
        };

        requestAnimationFrame(frame);
    };

    canvas.addEventListener('click', spin);
    canvas.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        spin();
    });
    window.addEventListener('resize', resize);

    prepare().finally(resize);
})();
