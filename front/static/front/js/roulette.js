(() => {
    const root = document.querySelector('[data-roulette-root]');
    const canvas = root?.querySelector('[data-roulette-canvas]');
    if (!root || !canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const W = 1180;
    const H = 840;
    const TAU = Math.PI * 2;
    const cx = 590;
    const cy = 454;
    const radius = 286;
    const innerRadius = 95;
    const slice = TAU / 8;
    const colors = { blue: '#0b56fa', ink: '#131313', panel: '#1f1f21', muted: '#707072', yellow: '#fbf110', white: '#ffffff' };

    const prizes = [
        { title: '+500 ₽', sub: ['на виртуальный', 'баланс'], icon: root.dataset.rouletteIcon1 },
        { title: 'VIP', sub: ['на 1 день'], icon: root.dataset.rouletteIcon2 },
        { title: '5 бесплатных', sub: ['прогнозов'], icon: root.dataset.rouletteIcon3 },
        { title: '1000 ₽', sub: ['бонус'], icon: root.dataset.rouletteIcon4 },
        { title: 'Буст', sub: ['рейтинга'], icon: root.dataset.rouletteIcon5 },
        { title: 'Промокод', sub: [], icon: root.dataset.rouletteIcon6 },
        { title: 'Попытка', sub: ['завтра'], icon: root.dataset.rouletteIcon7 },
        { title: 'Скидка 20%', sub: ['на VIP'], icon: root.dataset.rouletteIcon8 },
    ];

    const images = new Map();
    let background = null;
    let rotation = 0;
    let spinning = false;
    let demoIndex = 0;
    let countdown = '--:--:--';

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

    const cover = (image, x, y, width, height) => {
        if (!image?.naturalWidth || !image?.naturalHeight) return;
        const scale = Math.max(width / image.naturalWidth, height / image.naturalHeight);
        const sw = width / scale;
        const sh = height / scale;
        ctx.drawImage(image, (image.naturalWidth - sw) / 2, (image.naturalHeight - sh) / 2, sw, sh, x, y, width, height);
    };

    const prepare = async () => {
        window.CappersSkeleton?.loading(root);
        const loaded = await Promise.all([loadImage(root.dataset.rouletteBg), ...prizes.map((item) => loadImage(item.icon))]);
        background = loaded[0];
        loaded.slice(1).forEach((image, index) => { if (image) images.set(prizes[index].icon, image); });
        window.CappersSkeleton?.ready(root);
    };

    const drawBackground = () => {
        ctx.clearRect(0, 0, W, H);
    };

    const drawHeader = () => {
        text('Личный кабинет   ›   Мои бонусы   ›   Ежедневная рулетка', 38, 40, 13, 'rgba(220,228,246,.62)', 700, 'left');
        text('Ежедневная рулетка', 38, 92, 40, colors.white, 800, 'left');
        text('Крути колесо и получай приятные бонусы каждый день', 38, 130, 17, 'rgba(233,238,251,.74)', 600, 'left');
    };

    const drawNotes = () => {
        ctx.save();
        ctx.translate(986, 92);
        ctx.rotate(-.10);
        text('Маленькие бонусы', 0, 0, 17, 'rgba(160,181,224,.58)', 700);
        text('большим победам', 0, 24, 17, 'rgba(160,181,224,.58)', 700);
        ctx.fillStyle = colors.blue;
        ctx.fillRect(-38, 43, 76, 3);
        ctx.restore();

        ctx.save();
        ctx.translate(1035, 352);
        ctx.rotate(-.17);
        ['УДАЧА', 'ТОЖЕ', 'СТРАТЕГИЯ'].forEach((line, i) => text(line, 0, i * 24, 19, 'rgba(170,190,232,.56)', 800));
        ctx.strokeStyle = 'rgba(170,190,232,.56)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(-38, 69);
        ctx.lineTo(39, 55);
        ctx.stroke();
        ctx.restore();

        ctx.save();
        ctx.translate(118, 646);
        ctx.rotate(-.14);
        ['СЕГОДНЯ', 'БЛИЖЕ', 'К ПОБЕДЕ'].forEach((line, i) => text(line, 0, i * 26, 20, 'rgba(170,190,232,.56)', 800));
        ctx.strokeStyle = colors.blue;
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(-34, 74);
        ctx.lineTo(45, 74);
        ctx.stroke();
        ctx.restore();
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
            item.sub.forEach((line, i) => text(line, x, y + 37 + i * 18, 14, 'rgba(255,255,255,.88)', 700));
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

    const drawFooter = () => {
        const y = 786;
        const gift = images.get(prizes[5].icon);
        if (gift) ctx.drawImage(gift, 215, y - 23, 44, 44);
        text('1 бесплатное вращение каждый день', 273, y, 16, colors.white, 800, 'left');
        ctx.fillStyle = 'rgba(255,255,255,.18)';
        ctx.fillRect(585, y - 17, 2, 34);
        ctx.strokeStyle = 'rgba(255,255,255,.85)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(625, y, 13, 0, TAU);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(625, y - 7);
        ctx.lineTo(625, y);
        ctx.lineTo(631, y + 4);
        ctx.stroke();
        text('Следующая попытка через', 651, y, 15, 'rgba(224,231,246,.68)', 700, 'left');
        text(countdown, 847, y, 17, colors.white, 800, 'left');
    };

    const draw = () => {
        ctx.clearRect(0, 0, W, H);
        drawBackground();
        drawHeader();
        drawNotes();
        drawRing();
        drawWheel();
        drawCenter();
        drawPointer();
        drawFooter();
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

    const updateCountdown = () => {
        const now = new Date();
        const next = new Date(now);
        next.setHours(24, 0, 0, 0);
        const left = Math.max(0, Math.floor((next - now) / 1000));
        countdown = [Math.floor(left / 3600), Math.floor((left % 3600) / 60), left % 60]
            .map((value) => String(value).padStart(2, '0'))
            .join(':');
        draw();
    };

    canvas.addEventListener('click', spin);
    canvas.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        spin();
    });
    window.addEventListener('resize', resize);

    prepare().finally(() => {
        resize();
        updateCountdown();
        window.setInterval(updateCountdown, 1000);
    });
})();