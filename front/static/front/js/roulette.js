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
    const MAX_SECTORS = 10;
    const colors = {
        blue: '#0b56fa',
        ink: '#131313',
        panel: '#1f1f21',
        muted: '#707072',
        yellow: '#fbf110',
        white: '#ffffff',
    };
    const visualThemes = {
        virtual_balance: { fill: colors.blue, text: colors.white },
        vip_days: { fill: colors.yellow, text: colors.ink },
        free_predictions: { fill: '#1748b6', text: colors.white },
        promo_code: { fill: colors.panel, text: colors.white },
        rating_boost: { fill: '#19346f', text: colors.white },
        extra_spin: { fill: colors.blue, text: colors.white },
        nothing: { fill: colors.ink, text: colors.white },
    };

    const images = new Map();
    let prizes = [];
    let rotation = 0;
    let spinning = false;
    let demoIndex = 0;
    let enabled = false;
    let availableSpins = 0;
    let stateLoaded = false;
    let stateError = '';

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

    const clampText = (value, maxLength) => {
        const normalized = String(value || '').trim();
        if (normalized.length <= maxLength) return normalized;
        return `${normalized.slice(0, Math.max(1, maxLength - 1)).trim()}…`;
    };

    const splitSubtitle = (value, maxChars = 17, maxLines = 2) => {
        const normalized = String(value || '').trim();
        if (!normalized) return [];

        const words = normalized.split(/\s+/);
        const lines = [];
        let current = '';

        words.forEach((word) => {
            if (lines.length >= maxLines) return;
            const candidate = current ? `${current} ${word}` : word;
            if (candidate.length <= maxChars) {
                current = candidate;
                return;
            }
            if (current) lines.push(current);
            current = word;
        });

        if (current && lines.length < maxLines) lines.push(current);
        if (lines.length === maxLines && words.join(' ').length > lines.join(' ').length) {
            lines[maxLines - 1] = clampText(lines[maxLines - 1], maxChars);
        }
        return lines.slice(0, maxLines);
    };

    const normalizeSector = (item) => ({
        prizeId: Number(item?.prize_id) || 0,
        sectorOrder: Number(item?.sector_index) || 0,
        title: String(item?.title || '').trim() || 'Приз',
        sub: splitSubtitle(item?.short_text),
        icon: String(item?.icon_url || '').trim(),
        visualType: String(item?.visual_type || item?.reward_type || 'nothing'),
        rewardType: String(item?.reward_type || ''),
        rewardValue: String(item?.reward_value || ''),
    });

    const loadImage = (src) => new Promise((resolve) => {
        if (!src) return resolve(null);
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => resolve(null);
        image.src = src;
    });

    const prepareImages = async () => {
        images.clear();
        const loaded = await Promise.all(prizes.map((item) => loadImage(item.icon)));
        loaded.forEach((image, index) => {
            if (image && prizes[index]?.icon) images.set(prizes[index].icon, image);
        });
    };

    const prepare = async () => {
        const stateUrl = root.dataset.rouletteStateUrl;
        window.CappersSkeleton?.loading(root);
        canvas.setAttribute('aria-busy', 'true');
        stateError = '';

        try {
            if (!stateUrl) throw new Error('Не настроен URL состояния рулетки.');

            const response = await fetch(stateUrl, {
                method: 'GET',
                credentials: 'same-origin',
                headers: { Accept: 'application/json' },
            });
            const payload = await response.json().catch(() => null);
            if (!response.ok || !payload?.ok) {
                throw new Error(payload?.error || 'Не удалось загрузить рулетку.');
            }

            enabled = Boolean(payload.enabled);
            availableSpins = Math.max(0, Number(payload.available_spins) || 0);
            prizes = Array.isArray(payload.sectors)
                ? payload.sectors.slice(0, MAX_SECTORS).map(normalizeSector)
                : [];
            stateLoaded = true;

            await prepareImages();
        } catch (error) {
            prizes = [];
            enabled = false;
            availableSpins = 0;
            stateLoaded = true;
            stateError = error instanceof Error ? error.message : 'Не удалось загрузить рулетку.';
        } finally {
            canvas.setAttribute('aria-busy', 'false');
            window.CappersSkeleton?.ready(root);
        }
    };

    const currentSlice = () => (prizes.length ? TAU / prizes.length : TAU);

    const themeFor = (item, index) => {
        const theme = visualThemes[item.visualType];
        if (theme) return theme;
        return index % 2 === 0
            ? { fill: colors.panel, text: colors.white }
            : { fill: colors.blue, text: colors.white };
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

    const drawEmptyWheel = () => {
        ctx.save();
        ctx.translate(cx, cy);
        ctx.fillStyle = colors.panel;
        ctx.beginPath();
        ctx.arc(0, 0, radius, 0, TAU);
        ctx.fill();
        ctx.restore();
    };

    const drawWheel = () => {
        if (!prizes.length) {
            drawEmptyWheel();
            return;
        }

        const slice = currentSlice();
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(rotation);
        prizes.forEach((item, index) => {
            const mid = -Math.PI / 2 + index * slice;
            const start = mid - slice / 2;
            const end = mid + slice / 2;
            const theme = themeFor(item, index);

            ctx.fillStyle = theme.fill;
            ctx.beginPath();
            ctx.moveTo(0, 0);
            ctx.arc(0, 0, radius, start, end);
            ctx.closePath();
            ctx.fill();
        });
        ctx.restore();

        const labelRadius = prizes.length >= 9 ? 212 : 205;
        const iconSize = prizes.length >= 9 ? 44 : 54;
        prizes.forEach((item, index) => {
            const angle = -Math.PI / 2 + index * slice + rotation;
            const x = cx + Math.cos(angle) * labelRadius;
            const y = cy + Math.sin(angle) * labelRadius;
            const image = images.get(item.icon);
            const theme = themeFor(item, index);
            const title = clampText(item.title, prizes.length >= 9 ? 12 : 16);
            const titleSize = prizes.length >= 9
                ? (title.length > 10 ? 14 : 16)
                : (title.length > 11 ? 16 : 20);

            if (image) {
                ctx.drawImage(
                    image,
                    x - iconSize / 2,
                    y - (prizes.length >= 9 ? 52 : 57),
                    iconSize,
                    iconSize,
                );
            }

            text(title, x, y + 12, titleSize, theme.text, 800);
            item.sub.forEach((line, lineIndex) => {
                text(
                    line,
                    x,
                    y + 37 + lineIndex * 18,
                    prizes.length >= 9 ? 12 : 14,
                    theme.text,
                    700,
                );
            });
        });
    };

    const centerLabel = () => {
        if (!stateLoaded) return 'Загрузка…';
        if (stateError) return 'Недоступно';
        if (!enabled || !prizes.length) return 'Нет призов';
        if (availableSpins <= 0) return 'Нет попыток';
        if (spinning) return 'Крутим…';
        return 'Крутить';
    };

    const drawCenter = () => {
        ctx.save();
        ctx.translate(cx, cy);
        ctx.fillStyle = '#07111f';
        ctx.beginPath();
        ctx.arc(0, 0, innerRadius + 13, 0, TAU);
        ctx.fill();

        ctx.fillStyle = colors.blue;
        ctx.beginPath();
        ctx.arc(0, 0, innerRadius, 0, TAU);
        ctx.fill();

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

        const label = centerLabel();
        text(label, 0, 28, label.length > 10 ? 19 : 26, colors.white, 800);
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
        if (
            spinning
            || !stateLoaded
            || stateError
            || !enabled
            || availableSpins <= 0
            || !prizes.length
        ) return;

        spinning = true;
        const slice = currentSlice();
        demoIndex = (demoIndex + 3) % prizes.length;
        const start = rotation;
        const finish = rotation + TAU * 5 + slice * demoIndex;
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
