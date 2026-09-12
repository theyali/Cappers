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
    const deterministicErrorCodes = new Set([
        'authentication_required',
        'invalid_json',
        'missing_operation_id',
        'invalid_operation_id',
        'operation_id_conflict',
        'no_spins',
        'no_available_prizes',
        'roulette_disabled',
        'invalid_prize_weights',
        'reward_configuration_error',
    ]);

    const images = new Map();
    let prizes = [];
    let rotation = 0;
    let spinning = false;
    let requestPending = false;
    let pendingOperationId = '';
    let enabled = false;
    let availableSpins = 0;
    let nextSpinAt = null;
    let stateLoaded = false;
    let stateError = '';
    let transientError = '';
    let transientErrorTimer = null;
    let winningPrizeId = 0;
    let winCard = null;
    let winCardProgress = 0;
    let winHighlight = 0;
    let serverClockBaseMs = 0;
    let serverClockPerfMs = 0;
    let countdownRefreshAfterPerfMs = 0;

    canvas.style.display = 'block';
    canvas.style.margin = '0 auto';
    canvas.style.maxWidth = '100%';
    canvas.style.cursor = 'pointer';
    canvas.style.touchAction = 'manipulation';

    if (root.dataset.rouletteBg) {
        root.style.backgroundImage = `url("${root.dataset.rouletteBg}")`;
        root.style.backgroundPosition = 'center';
        root.style.backgroundSize = 'cover';
        root.style.backgroundRepeat = 'no-repeat';
    }

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

    const splitLines = (value, maxChars = 17, maxLines = 2) => {
        const normalized = String(value || '').trim();
        if (!normalized) return [];

        const words = normalized.split(/\s+/);
        const lines = [];
        let current = '';
        let consumedWords = 0;

        for (const word of words) {
            if (lines.length >= maxLines) break;
            const candidate = current ? `${current} ${word}` : word;
            if (candidate.length <= maxChars) {
                current = candidate;
                consumedWords += 1;
                continue;
            }
            if (current) lines.push(current);
            if (lines.length >= maxLines) break;
            current = word;
            consumedWords += 1;
        }

        if (current && lines.length < maxLines) lines.push(current);
        if (consumedWords < words.length && lines.length) {
            lines[lines.length - 1] = clampText(lines[lines.length - 1], maxChars);
        }
        return lines.slice(0, maxLines);
    };

    const normalizeSector = (item) => ({
        prizeId: Number(item?.prize_id) || 0,
        sectorOrder: Number(item?.sector_index) || 0,
        title: String(item?.title || '').trim() || 'Приз',
        shortText: String(item?.short_text || '').trim(),
        sub: splitLines(item?.short_text),
        icon: String(item?.icon_url || '').trim(),
        visualType: String(item?.visual_type || item?.reward_type || 'nothing'),
        rewardType: String(item?.reward_type || ''),
        rewardValue: String(item?.reward_value || ''),
        rewardText: String(item?.reward_text || ''),
    });

    const syncServerClock = (serverTime) => {
        const parsed = Date.parse(serverTime || '');
        if (!Number.isFinite(parsed)) return;
        serverClockBaseMs = parsed;
        serverClockPerfMs = performance.now();
    };

    const serverNowMs = () => {
        if (!serverClockBaseMs) return Date.now();
        return serverClockBaseMs + (performance.now() - serverClockPerfMs);
    };

    const nextSpinRemainingMs = () => {
        if (!nextSpinAt) return 0;
        const target = Date.parse(nextSpinAt);
        if (!Number.isFinite(target)) return 0;
        return Math.max(0, target - serverNowMs());
    };

    const formatCountdown = (milliseconds) => {
        const totalSeconds = Math.max(0, Math.ceil(milliseconds / 1000));
        const hours = Math.floor(totalSeconds / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = totalSeconds % 60;
        return [hours, minutes, seconds]
            .map((value) => String(value).padStart(2, '0'))
            .join(':');
    };

    const attemptStatusText = () => {
        if (!stateLoaded) return 'Загрузка состояния рулетки…';
        if (stateError) return stateError;
        if (!enabled || !prizes.length) return 'Рулетка сейчас недоступна';
        if (availableSpins > 0) return `Доступно попыток: ${availableSpins}`;
        if (nextSpinAt) return `Следующая попытка через ${formatCountdown(nextSpinRemainingMs())}`;
        return 'Доступных попыток пока нет';
    };

    const publishAttempts = () => {
        window.dispatchEvent(new CustomEvent('cappers:roulette-attempts', {
            detail: { availableSpins },
        }));
    };

    const updateCanvasA11y = () => {
        canvas.setAttribute(
            'aria-label',
            `${attemptStatusText()}. ${availableSpins > 0 ? 'Нажмите, чтобы крутить.' : ''}`.trim(),
        );
    };

    const loadImage = (src) => new Promise((resolve) => {
        if (!src) return resolve(null);
        if (images.has(src)) return resolve(images.get(src));
        const image = new Image();
        image.onload = () => {
            images.set(src, image);
            resolve(image);
        };
        image.onerror = () => resolve(null);
        image.src = src;
    });

    const prepareImages = async () => {
        const loaded = await Promise.all(prizes.map((item) => loadImage(item.icon)));
        loaded.forEach((image, index) => {
            if (image && prizes[index]?.icon) images.set(prizes[index].icon, image);
        });
    };

    const applyStatePayload = async (payload) => {
        syncServerClock(payload.server_time);
        enabled = Boolean(payload.enabled);
        availableSpins = Math.max(0, Number(payload.available_spins) || 0);
        nextSpinAt = payload.next_spin_at || null;
        prizes = Array.isArray(payload.sectors)
            ? payload.sectors.slice(0, MAX_SECTORS).map(normalizeSector)
            : [];
        stateLoaded = true;
        stateError = '';
        countdownRefreshAfterPerfMs = 0;
        await prepareImages();
        publishAttempts();
        updateCanvasA11y();
    };

    const fetchState = async ({ withSkeleton = false } = {}) => {
        const stateUrl = root.dataset.rouletteStateUrl;
        if (!stateUrl) throw new Error('Не настроен URL состояния рулетки.');

        if (withSkeleton) {
            window.CappersSkeleton?.loading(root);
            canvas.setAttribute('aria-busy', 'true');
        }

        try {
            const response = await fetch(stateUrl, {
                method: 'GET',
                credentials: 'same-origin',
                headers: { Accept: 'application/json' },
            });
            const payload = await response.json().catch(() => null);
            if (!response.ok || !payload?.ok) {
                throw new Error(payload?.error || 'Не удалось загрузить рулетку.');
            }
            await applyStatePayload(payload);
            return payload;
        } finally {
            if (withSkeleton) {
                canvas.setAttribute('aria-busy', 'false');
                window.CappersSkeleton?.ready(root);
            }
        }
    };

    const prepare = async () => {
        stateError = '';
        try {
            await fetchState({ withSkeleton: true });
        } catch (error) {
            prizes = [];
            enabled = false;
            availableSpins = 0;
            nextSpinAt = null;
            stateLoaded = true;
            stateError = error instanceof Error ? error.message : 'Не удалось загрузить рулетку.';
            publishAttempts();
            updateCanvasA11y();
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
            const isWinner = item.prizeId === winningPrizeId && winHighlight > 0;

            ctx.save();
            if (isWinner) {
                ctx.shadowColor = colors.yellow;
                ctx.shadowBlur = 34 * winHighlight;
            }
            ctx.fillStyle = theme.fill;
            ctx.beginPath();
            ctx.moveTo(0, 0);
            ctx.arc(0, 0, radius, start, end);
            ctx.closePath();
            ctx.fill();
            ctx.restore();
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

    const canSpin = () => (
        stateLoaded
        && !stateError
        && enabled
        && availableSpins > 0
        && prizes.length > 0
        && !requestPending
        && !spinning
    );

    const centerLabel = () => {
        if (!stateLoaded) return 'Загрузка…';
        if (requestPending) return 'Проверяем…';
        if (spinning) return 'Крутим…';
        if (stateError) return 'Недоступно';
        if (!enabled || !prizes.length) return 'Нет призов';
        if (availableSpins <= 0) return 'Нет попыток';
        return 'Крутить';
    };

    const drawCenter = () => {
        ctx.save();
        ctx.translate(cx, cy);
        ctx.fillStyle = '#07111f';
        ctx.beginPath();
        ctx.arc(0, 0, innerRadius + 13, 0, TAU);
        ctx.fill();

        ctx.fillStyle = canSpin() || requestPending || spinning ? colors.blue : '#303033';
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

    const drawAttemptStatus = () => {
        if (winCard) return;
        const label = attemptStatusText();
        const color = availableSpins > 0 ? colors.yellow : colors.white;
        text(clampText(label, 66), cx, H - 26, 15, color, 800);
    };

    const roundedRect = (x, y, width, height, radiusValue) => {
        const r = Math.min(radiusValue, width / 2, height / 2);
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.lineTo(x + width - r, y);
        ctx.quadraticCurveTo(x + width, y, x + width, y + r);
        ctx.lineTo(x + width, y + height - r);
        ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
        ctx.lineTo(x + r, y + height);
        ctx.quadraticCurveTo(x, y + height, x, y + height - r);
        ctx.lineTo(x, y + r);
        ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.closePath();
    };

    const popScale = (progress) => {
        const c1 = 1.70158;
        const c3 = c1 + 1;
        const value = Math.max(0, Math.min(progress, 1));
        return 1 + c3 * Math.pow(value - 1, 3) + c1 * Math.pow(value - 1, 2);
    };

    const drawWinCard = () => {
        if (!winCard || winCardProgress <= 0) return;

        const progress = Math.max(0, Math.min(winCardProgress, 1));
        const scale = 0.82 + 0.18 * popScale(progress);
        const alpha = Math.min(1, progress * 1.7);
        const cardWidth = 400;
        const cardHeight = 260;
        const cardX = cx - cardWidth / 2;
        const cardY = cy - cardHeight / 2 + 4;

        ctx.save();
        ctx.globalAlpha = alpha;
        ctx.translate(cx, cy);
        ctx.scale(scale, scale);
        ctx.translate(-cx, -cy);

        ctx.fillStyle = colors.panel;
        roundedRect(cardX, cardY, cardWidth, cardHeight, 22);
        ctx.fill();

        ctx.fillStyle = colors.yellow;
        roundedRect(cx - 70, cardY + 18, 140, 30, 10);
        ctx.fill();
        text('ВЫ ВЫИГРАЛИ', cx, cardY + 33, 13, colors.ink, 800);

        const image = images.get(winCard.icon);
        const iconY = cardY + 76;
        if (image) {
            ctx.drawImage(image, cx - 30, iconY, 60, 60);
        } else {
            ctx.fillStyle = colors.blue;
            roundedRect(cx - 28, iconY + 2, 56, 56, 14);
            ctx.fill();
            text('★', cx, iconY + 31, 28, colors.white, 800);
        }

        text(clampText(winCard.title, 28), cx, cardY + 153, 25, colors.white, 800);

        const subtitleLines = splitLines(winCard.shortText, 34, 1);
        subtitleLines.forEach((line, index) => {
            text(line, cx, cardY + 181 + index * 18, 14, '#d1d1d3', 700);
        });

        const actionLines = splitLines(winCard.action, 42, 2);
        actionLines.forEach((line, index) => {
            text(line, cx, cardY + 211 + index * 19, 14, colors.yellow, 800);
        });

        ctx.restore();
    };

    const drawStatusMessage = () => {
        if (!transientError || winCard) return;
        text(clampText(transientError, 72), cx, H - 50, 14, colors.yellow, 700);
    };

    const draw = () => {
        ctx.clearRect(0, 0, W, H);
        drawRing();
        drawWheel();
        drawCenter();
        drawPointer();
        drawAttemptStatus();
        drawWinCard();
        drawStatusMessage();
        updateCanvasA11y();
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
    const normalizeAngle = (value) => ((value % TAU) + TAU) % TAU;

    const makeOperationId = () => {
        if (window.crypto?.randomUUID) return window.crypto.randomUUID();
        const bytes = new Uint8Array(16);
        window.crypto?.getRandomValues?.(bytes);
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
        return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    };

    const requestSpin = async () => {
        const spinUrl = root.dataset.rouletteSpinUrl;
        const csrfToken = root.dataset.rouletteCsrf;
        if (!spinUrl) throw new Error('Не настроен URL прокрутки рулетки.');

        const operationId = pendingOperationId || makeOperationId();
        pendingOperationId = operationId;
        window.CappersSkeleton?.loading(root);
        canvas.setAttribute('aria-busy', 'true');

        try {
            const response = await fetch(spinUrl, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    Accept: 'application/json',
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                },
                body: JSON.stringify({ operation_id: operationId }),
            });
            const payload = await response.json().catch(() => null);

            if (!response.ok || !payload?.ok) {
                const error = new Error(payload?.error || 'Не удалось выполнить прокрутку.');
                error.code = payload?.code || 'spin_request_failed';
                if (deterministicErrorCodes.has(error.code)) pendingOperationId = '';
                throw error;
            }

            pendingOperationId = '';
            return payload;
        } finally {
            canvas.setAttribute('aria-busy', 'false');
            window.CappersSkeleton?.ready(root);
        }
    };

    const ensureWinnerOnWheel = async (payload) => {
        const prizeId = Number(payload?.prize_id) || Number(payload?.prize?.prize_id) || 0;
        let winnerIndex = prizes.findIndex((item) => item.prizeId === prizeId);
        if (winnerIndex >= 0) return winnerIndex;

        if (!payload?.prize) return -1;
        const winner = normalizeSector(payload.prize);
        prizes = [...prizes.filter((item) => item.prizeId !== winner.prizeId), winner]
            .sort((a, b) => a.sectorOrder - b.sectorOrder || a.prizeId - b.prizeId)
            .slice(0, MAX_SECTORS);
        await loadImage(winner.icon);
        winnerIndex = prizes.findIndex((item) => item.prizeId === winner.prizeId);
        draw();
        return winnerIndex;
    };

    const animateWheelTo = (winnerIndex) => new Promise((resolve) => {
        const slice = currentSlice();
        const start = rotation;
        const startNormalized = normalizeAngle(start);
        const target = normalizeAngle(-winnerIndex * slice);
        const targetDelta = normalizeAngle(target - startNormalized);
        const fullTurns = 4 + Math.floor(Math.random() * 3);
        const finish = start + TAU * fullTurns + targetDelta;
        const started = performance.now();
        const duration = 4300;
        spinning = true;

        const frame = (now) => {
            const progress = Math.min((now - started) / duration, 1);
            rotation = start + (finish - start) * ease(progress);
            draw();

            if (progress < 1) {
                requestAnimationFrame(frame);
                return;
            }

            rotation = normalizeAngle(finish);
            spinning = false;
            draw();
            resolve();
        };

        requestAnimationFrame(frame);
    });

    const formatRewardValue = (value) => {
        const number = Number(value);
        if (!Number.isFinite(number)) return String(value || '');
        return new Intl.NumberFormat('ru-RU', {
            maximumFractionDigits: Number.isInteger(number) ? 0 : 2,
        }).format(number);
    };

    const plural = (value, one, few, many) => {
        const number = Math.abs(Number(value) || 0);
        const mod100 = number % 100;
        const mod10 = number % 10;
        if (mod100 >= 11 && mod100 <= 14) return many;
        if (mod10 === 1) return one;
        if (mod10 >= 2 && mod10 <= 4) return few;
        return many;
    };

    const formatVipUntil = (value) => {
        if (!value) return '';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return '';
        return new Intl.DateTimeFormat('ru-RU', {
            day: 'numeric',
            month: 'long',
            year: date.getFullYear() === new Date().getFullYear() ? undefined : 'numeric',
        }).format(date);
    };

    const rewardActionText = (payload) => {
        const prize = payload?.prize || {};
        const result = payload?.reward_result || {};
        const value = Number(prize.reward_value) || 0;
        const formattedValue = formatRewardValue(prize.reward_value);

        switch (prize.reward_type) {
            case 'virtual_balance':
                return `+${formattedValue} ₽ зачислено на виртуальный баланс`;
            case 'vip_days': {
                const until = formatVipUntil(result.vip_until);
                return until
                    ? `VIP активирован до ${until}`
                    : `VIP активирован на ${formattedValue} ${plural(value, 'день', 'дня', 'дней')}`;
            }
            case 'free_predictions':
                return `Добавлено ${formattedValue} ${plural(value, 'бесплатный прогноз', 'бесплатных прогноза', 'бесплатных прогнозов')}`;
            case 'promo_code':
                return result.promo_code || prize.reward_text
                    ? `Ваш промокод: ${result.promo_code || prize.reward_text}`
                    : 'Промокод сохранён в истории выигрышей';
            case 'rating_boost':
                return `Буст рейтинга увеличен на ${formattedValue}`;
            case 'extra_spin':
                return `+${formattedValue} ${plural(value, 'попытка', 'попытки', 'попыток')}. Доступно: ${payload.available_spins}`;
            case 'nothing':
                return prize.short_text || 'Попробуйте снова в следующий раз';
            default:
                return prize.short_text || 'Награда успешно начислена';
        }
    };

    const animateWinCard = (payload, winner) => new Promise((resolve) => {
        winCard = {
            title: String(payload?.prize?.title || winner?.title || 'Приз'),
            shortText: String(payload?.prize?.short_text || winner?.shortText || ''),
            icon: String(payload?.prize?.icon_url || winner?.icon || ''),
            action: rewardActionText(payload),
        };
        winningPrizeId = Number(payload?.prize_id) || winner?.prizeId || 0;
        winCardProgress = 0;
        winHighlight = 0;

        const started = performance.now();
        const duration = 620;

        const frame = (now) => {
            const progress = Math.min((now - started) / duration, 1);
            winCardProgress = progress;
            winHighlight = Math.min(1, progress * 1.4);
            draw();

            if (progress < 1) {
                requestAnimationFrame(frame);
                return;
            }

            winCardProgress = 1;
            winHighlight = 1;
            draw();
            resolve();
        };

        requestAnimationFrame(frame);
    });

    const showTransientError = (message) => {
        transientError = String(message || 'Не удалось выполнить прокрутку.');
        if (transientErrorTimer) window.clearTimeout(transientErrorTimer);
        transientErrorTimer = window.setTimeout(() => {
            transientError = '';
            draw();
        }, 3500);
        draw();
    };

    const refreshAfterCountdown = async () => {
        if (
            availableSpins > 0
            || requestPending
            || spinning
            || !stateLoaded
            || !enabled
            || performance.now() < countdownRefreshAfterPerfMs
        ) return;

        if (!nextSpinAt || nextSpinRemainingMs() > 0) return;
        countdownRefreshAfterPerfMs = performance.now() + 30000;

        try {
            await fetchState();
            draw();
        } catch (error) {
            showTransientError(error instanceof Error ? error.message : 'Не удалось обновить попытки.');
        }
    };

    const spin = async () => {
        if (!canSpin()) return;

        requestPending = true;
        transientError = '';
        winCard = null;
        winCardProgress = 0;
        winHighlight = 0;
        winningPrizeId = 0;
        draw();

        try {
            const payload = await requestSpin();
            syncServerClock(payload.server_time);
            availableSpins = Math.max(0, Number(payload.available_spins) || 0);
            nextSpinAt = payload.next_spin_at || null;
            countdownRefreshAfterPerfMs = 0;
            publishAttempts();

            const winnerIndex = await ensureWinnerOnWheel(payload);
            if (winnerIndex < 0) {
                throw new Error('Выигранный сектор не найден на колесе.');
            }

            const winner = prizes[winnerIndex];
            const winnerIconPromise = loadImage(payload?.prize?.icon_url || winner.icon);
            requestPending = false;
            await animateWheelTo(winnerIndex);
            await winnerIconPromise;
            await animateWinCard(payload, winner);
        } catch (error) {
            requestPending = false;
            spinning = false;
            if (error?.code === 'no_spins') {
                availableSpins = 0;
                publishAttempts();
            }
            showTransientError(error instanceof Error ? error.message : 'Не удалось выполнить прокрутку.');
        } finally {
            requestPending = false;
            spinning = false;
            draw();
        }
    };

    const tickCountdown = () => {
        if (!stateLoaded) return;
        draw();
        refreshAfterCountdown();
    };

    canvas.addEventListener('click', spin);
    canvas.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        spin();
    });
    window.addEventListener('resize', resize);
    window.setInterval(tickCountdown, 1000);

    prepare().finally(resize);
})();
