(() => {
    // The bonus wheel in a bottom sheet, opened by the wheel in the bottom menu on phones and in
    // the Telegram Mini App. It uses the same state and spin API as the wheel on the bonuses page.
    const sheet = document.querySelector("[data-roulette-sheet]");
    if (!sheet) return;

    const panel = sheet.querySelector(".roulette-sheet-panel");
    const disc = sheet.querySelector("[data-roulette-sheet-disc]");
    const frame = sheet.querySelector("[data-roulette-sheet-frame]");
    const titleNode = sheet.querySelector("[data-roulette-sheet-title]");
    const textNode = sheet.querySelector("[data-roulette-sheet-text]");
    const noteNode = sheet.querySelector("[data-roulette-sheet-note]");
    const prizeImage = sheet.querySelector("[data-roulette-sheet-prize]");
    const codeButton = sheet.querySelector("[data-roulette-sheet-code]");
    const spinButton = sheet.querySelector("[data-roulette-sheet-spin]");
    const bonusesLink = sheet.querySelector("[data-roulette-sheet-bonuses]");
    const confettiCanvas = sheet.querySelector("[data-roulette-sheet-confetti]");

    const SVG_NS = "http://www.w3.org/2000/svg";
    const RADIUS = 292;
    const SPIN_MS = 5200;
    const MAX_SECTORS = 10;
    const TITLE = "Колесо бонусов";
    const INTRO = "Крути колесо и забирай призы каждый день.";
    // Errors after which the same request will fail again, so a new operation id is needed.
    const FINAL_ERRORS = new Set([
        "authentication_required",
        "invalid_json",
        "missing_operation_id",
        "invalid_operation_id",
        "operation_id_conflict",
        "no_spins",
        "no_available_prizes",
        "roulette_disabled",
        "invalid_prize_weights",
        "reward_configuration_error",
    ]);

    let prizes = [];
    let enabled = false;
    let availableSpins = 0;
    let nextSpinAt = null;
    let serverOffsetMs = 0;
    let rotation = 0;
    let phase = "closed";
    let pendingOperationId = "";
    let countdownTimer = 0;
    let closeTimer = 0;
    let spunHere = false;
    let lastFocus = null;
    // Bumped on close, so a request or animation still running knows the sheet is gone.
    let session = 0;

    const plural = (value, one, few, many) => {
        const number = Math.abs(Number(value) || 0);
        const mod100 = number % 100;
        const mod10 = number % 10;
        if (mod100 >= 11 && mod100 <= 14) return many;
        if (mod10 === 1) return one;
        if (mod10 >= 2 && mod10 <= 4) return few;
        return many;
    };

    const formatNumber = (value) => {
        const number = Number(value);
        if (!Number.isFinite(number)) return String(value || "");
        return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: Number.isInteger(number) ? 0 : 2 }).format(number);
    };

    const haptic = (kind, style) => {
        const feedback = window.Telegram?.WebApp?.HapticFeedback;
        if (!feedback) return;
        try {
            if (kind === "impact") feedback.impactOccurred(style);
            else if (kind === "notify") feedback.notificationOccurred(style);
            else feedback.selectionChanged();
        } catch (error) {
            // Older Telegram apps have no haptics.
        }
    };

    const sound = (() => {
        let context = null;
        const buffers = {};

        // Browsers allow sound only after a tap, so this runs on the taps that open and spin.
        const unlock = () => {
            const AudioContextClass = window.AudioContext || window.webkitAudioContext;
            if (!AudioContextClass) return;
            if (!context) {
                context = new AudioContextClass();
                [["tick", sheet.dataset.tickSound], ["win", sheet.dataset.winSound]].forEach(([name, url]) => {
                    fetch(url)
                        .then((response) => (response.ok ? response.arrayBuffer() : Promise.reject(new Error(url))))
                        .then((data) => new Promise((resolve, reject) => context.decodeAudioData(data, resolve, reject)))
                        .then((buffer) => { buffers[name] = buffer; })
                        .catch(() => {});
                });
            }
            if (context.state === "suspended") context.resume().catch(() => {});
        };

        const play = (name, volume = 1) => {
            if (!context || context.state !== "running" || !buffers[name]) return;
            const source = context.createBufferSource();
            const gain = context.createGain();
            gain.gain.value = volume;
            source.buffer = buffers[name];
            source.connect(gain);
            gain.connect(context.destination);
            source.start();
        };

        return { unlock, play };
    })();

    const confetti = (() => {
        const ctx = confettiCanvas.getContext("2d");
        const colors = ["#fbf110", "#ffffff", "#ffb800", "#131313", "#8fb6ff"];
        let pieces = [];
        let frameId = 0;
        let last = 0;
        let size = { width: 0, height: 0 };

        const fit = () => {
            const rect = confettiCanvas.getBoundingClientRect();
            const ratio = Math.min(window.devicePixelRatio || 1, 2);
            confettiCanvas.width = Math.round(rect.width * ratio);
            confettiCanvas.height = Math.round(rect.height * ratio);
            ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
            size = { width: rect.width, height: rect.height };
        };

        const step = (now) => {
            const dt = Math.min((now - last) / 1000, 0.05);
            last = now;
            ctx.clearRect(0, 0, size.width, size.height);
            pieces = pieces.filter((piece) => piece.life > 0 && piece.y < size.height + 40);
            pieces.forEach((piece) => {
                piece.vx *= 1 - 1.4 * dt;
                piece.vy = Math.min(piece.vy + 900 * dt, 300);
                piece.x += (piece.vx + Math.sin(piece.tilt) * 30) * dt;
                piece.y += piece.vy * dt;
                piece.tilt += piece.tiltSpeed * dt;
                piece.life -= dt;

                ctx.save();
                ctx.globalAlpha = Math.min(1, piece.life * 2);
                ctx.translate(piece.x, piece.y);
                ctx.rotate(piece.tilt);
                ctx.scale(1, Math.cos(piece.tilt * 1.7));
                ctx.fillStyle = piece.color;
                if (piece.round) {
                    ctx.beginPath();
                    ctx.arc(0, 0, piece.size / 2.4, 0, Math.PI * 2);
                    ctx.fill();
                } else {
                    ctx.fillRect(-piece.size / 2, -piece.size / 4, piece.size, piece.size / 2);
                }
                ctx.restore();
            });
            frameId = pieces.length ? requestAnimationFrame(step) : 0;
        };

        const burst = () => {
            fit();
            const originX = size.width / 2;
            const originY = size.height * 0.24;
            for (let index = 0; index < 170; index += 1) {
                const angle = -Math.PI / 2 + (Math.random() - 0.5) * Math.PI * 1.3;
                const speed = 420 + Math.random() * 560;
                pieces.push({
                    x: originX + (Math.random() - 0.5) * 60,
                    y: originY,
                    vx: Math.cos(angle) * speed,
                    vy: Math.sin(angle) * speed,
                    size: 7 + Math.random() * 7,
                    tilt: Math.random() * Math.PI * 2,
                    tiltSpeed: (Math.random() - 0.5) * 12,
                    color: colors[index % colors.length],
                    round: Math.random() < 0.25,
                    life: 2.4 + Math.random() * 1.4,
                });
            }
            if (!frameId) {
                last = performance.now();
                frameId = requestAnimationFrame(step);
            }
        };

        const stop = () => {
            pieces = [];
            if (frameId) cancelAnimationFrame(frameId);
            frameId = 0;
            ctx.clearRect(0, 0, size.width, size.height);
        };

        return { burst, stop };
    })();

    const svg = (name, attributes, parent) => {
        const node = document.createElementNS(SVG_NS, name);
        Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
        parent.appendChild(node);
        return node;
    };

    // Angles go clockwise from the pointer at the top.
    const point = (degrees, radius) => {
        const radians = (degrees * Math.PI) / 180;
        return [(radius * Math.sin(radians)).toFixed(2), (-radius * Math.cos(radians)).toFixed(2)];
    };

    const wedge = (from, to) => {
        const [x1, y1] = point(from, RADIUS);
        const [x2, y2] = point(to, RADIUS);
        return `M0 0L${x1} ${y1}A${RADIUS} ${RADIUS} 0 ${to - from > 180 ? 1 : 0} 1 ${x2} ${y2}Z`;
    };

    // Warm tones like the reference wheel: dark at the centre, light at the rim.
    const TONES = {
        gold: ["#f2a900", "#ffc531", "#ffe07a"],
        orange: ["#f07800", "#ff9a1f", "#ffbf5c"],
        deep: ["#e04f00", "#ff6f1a", "#ff9a55"],
        pink: ["#d92a4a", "#ff4d6d", "#ff8299"],
    };
    const TONE_ORDER = ["gold", "orange", "deep", "pink"];

    const sectorTone = (index) => {
        // When the count leaves the last sector next to one of its colour, it takes orange instead.
        if (index === prizes.length - 1 && index % TONE_ORDER.length === 0 && index > 0) return "orange";
        return TONE_ORDER[index % TONE_ORDER.length];
    };

    const titleLines = (title, maxChars, maxLines) => {
        const lines = [];
        String(title).split(/\s+/).filter(Boolean).forEach((word) => {
            const lastLine = lines[lines.length - 1];
            if (lastLine && `${lastLine} ${word}`.length <= maxChars) lines[lines.length - 1] = `${lastLine} ${word}`;
            else lines.push(word);
        });
        const shown = lines.slice(0, maxLines);
        if (lines.length > maxLines) shown[maxLines - 1] = `${shown[maxLines - 1]}…`;
        return shown.map((line) => (line.length > maxChars + 1 ? `${line.slice(0, maxChars)}…` : line));
    };

    const setRotation = (degrees) => {
        rotation = degrees;
        disc.style.transform = `rotate(${degrees}deg)`;
    };

    const addGradients = () => {
        const defs = svg("defs", {}, disc);
        const frameDefs = svg("defs", {}, frame);
        Object.entries(TONES).forEach(([name, [dark, base, light]]) => {
            const gradient = svg("radialGradient", { id: `roulette-tone-${name}`, gradientUnits: "userSpaceOnUse", cx: 0, cy: 0, r: RADIUS }, defs);
            [[0, dark], [0.62, base], [1, light]].forEach(([offset, color]) => {
                svg("stop", { offset, "stop-color": color }, gradient);
            });
        });
        const rim = svg("linearGradient", { id: "roulette-rim", x1: 0, y1: 0, x2: 0, y2: 1 }, frameDefs);
        [[0, "#ffa040"], [0.5, "#ff6b1a"], [1, "#e8480c"]].forEach(([offset, color]) => {
            svg("stop", { offset, "stop-color": color }, rim);
        });
    };

    const addLabel = (prize, middle, slice) => {
        const count = prizes.length;
        const fontSize = count <= 4 ? 34 : count <= 6 ? 30 : count <= 8 ? 27 : 23;
        // How many letters fit across the sector where the text starts.
        const width = count < 2 ? RADIUS * 1.6 : 2 * (RADIUS - 80) * Math.sin((Math.min(slice, 150) * Math.PI) / 360);
        const maxChars = Math.max(4, Math.floor((width * 0.9) / (fontSize * 0.62)));
        const label = svg("g", { transform: `rotate(${middle})` }, disc);
        if (prize.icon) {
            const size = count <= 8 ? 46 : 38;
            svg("image", { href: prize.icon, x: -size / 2, y: -RADIUS + 18, width: size, height: size }, label);
        }
        const text = svg("text", { class: "roulette-sheet-label", "font-size": fontSize, y: -RADIUS + (prize.icon ? 96 : 60) }, label);
        titleLines(prize.title, maxChars, count <= 4 ? 3 : 2).forEach((line, lineIndex) => {
            svg("tspan", { x: 0, dy: lineIndex ? Math.round(fontSize * 1.08) : 0 }, text).textContent = line;
        });
    };

    const buildWheel = () => {
        disc.replaceChildren();
        frame.replaceChildren();
        addGradients();

        const count = prizes.length;
        const slice = 360 / Math.max(count, 1);
        if (count < 2) {
            svg("circle", { r: RADIUS, fill: "url(#roulette-tone-gold)" }, disc);
        } else {
            prizes.forEach((prize, index) => {
                const middle = index * slice;
                svg("path", { d: wedge(middle - slice / 2, middle + slice / 2), fill: `url(#roulette-tone-${sectorTone(index)})` }, disc);
            });
            prizes.forEach((prize, index) => {
                const [x, y] = point(index * slice + slice / 2, RADIUS);
                svg("line", { x1: 0, y1: 0, x2: x, y2: y, class: "roulette-sheet-separator" }, disc);
            });
        }
        svg("circle", { r: 120, class: "roulette-sheet-band" }, disc);
        prizes.forEach((prize, index) => addLabel(prize, index * slice, slice));

        svg("circle", { r: RADIUS, class: "roulette-sheet-rim-inner" }, frame);
        svg("circle", { r: RADIUS + 12, class: "roulette-sheet-rim", stroke: "url(#roulette-rim)" }, frame);
        svg("circle", { r: RADIUS + 26, class: "roulette-sheet-rim-edge" }, frame);
        if (count > 1) svg("path", { d: wedge(-slice / 2, slice / 2), class: "roulette-sheet-highlight" }, frame);
        setRotation(rotation);
    };

    const normalizePrize = (item) => ({
        prizeId: Number(item?.prize_id) || 0,
        sectorOrder: Number(item?.sector_index) || 0,
        title: String(item?.title || "").trim() || "Приз",
        icon: String(item?.icon_url || "").trim(),
    });

    const syncClock = (serverTime) => {
        const serverMs = Date.parse(serverTime || "");
        if (Number.isFinite(serverMs)) serverOffsetMs = serverMs - Date.now();
    };

    const setSpins = (value) => {
        availableSpins = Math.max(0, Number(value) || 0);
        window.dispatchEvent(new CustomEvent("cappers:roulette-attempts", { detail: { availableSpins } }));
    };

    const updateWalletBalance = (value) => {
        const balance = Number(value);
        if (value === undefined || value === null || !Number.isFinite(balance)) return;
        const display = Math.trunc(balance).toLocaleString("ru-RU");
        document.querySelectorAll("[data-wallet-balance]").forEach((node) => {
            node.dataset.walletBalanceVisible = display;
            if (node.textContent.trim() === node.dataset.walletBalanceMasked) return;
            node.textContent = display;
        });
    };

    const canSpin = () => enabled && prizes.length > 0 && availableSpins > 0;

    const spinsNote = () => `Доступно ${availableSpins} ${plural(availableSpins, "попытка", "попытки", "попыток")}`;

    const waitNote = () => {
        const remaining = Date.parse(nextSpinAt || "") - (Date.now() + serverOffsetMs);
        if (!Number.isFinite(remaining)) return "Попытки на сегодня закончились";
        if (remaining <= 0) return "Новая попытка уже доступна";
        const seconds = Math.ceil(remaining / 1000);
        const clock = [Math.floor(seconds / 3600), Math.floor((seconds % 3600) / 60), seconds % 60]
            .map((part) => String(part).padStart(2, "0"))
            .join(":");
        return `Новая попытка через ${clock}`;
    };

    const stopCountdown = () => {
        window.clearInterval(countdownTimer);
        countdownTimer = 0;
    };

    const renderNote = () => {
        if (!enabled || !prizes.length) {
            noteNode.textContent = "";
            return;
        }
        noteNode.textContent = availableSpins > 0 ? spinsNote() : waitNote();
    };

    const startCountdown = () => {
        stopCountdown();
        renderNote();
        if (availableSpins > 0 || !nextSpinAt) return;
        countdownTimer = window.setInterval(() => {
            renderNote();
            if (Date.parse(nextSpinAt) - (Date.now() + serverOffsetMs) <= 0) {
                stopCountdown();
                loadState();
            }
        }, 1000);
    };

    // The prize picture shows only after a win: the prize's own icon, or a gift.
    const setCopy = ({ title = TITLE, text = "", code = "", icon = "" }) => {
        titleNode.textContent = title;
        textNode.textContent = text;
        prizeImage.hidden = !icon;
        if (icon && prizeImage.getAttribute("src") !== icon) prizeImage.setAttribute("src", icon);
        codeButton.hidden = !code;
        codeButton.textContent = code;
        codeButton.dataset.code = code;
    };

    // The centre spins the wheel; "Мои бонусы" shows after a spin or when no spins are left.
    const renderControls = () => {
        const ready = phase === "idle" || phase === "won";
        spinButton.disabled = !(ready && canSpin());
        bonusesLink.hidden = !(phase === "won" || (phase === "idle" && !canSpin()));
    };

    const showIdle = (text) => {
        phase = "idle";
        sheet.classList.remove("is-won");
        let message = text || (canSpin() ? INTRO : "Попытки на сегодня закончились.");
        if (!enabled || !prizes.length) message = "Колесо сейчас недоступно. Загляните позже.";
        setCopy({ text: message });
        renderControls();
        startCountdown();
    };

    async function loadState() {
        const current = session;
        try {
            const response = await fetch(sheet.dataset.stateUrl, {
                credentials: "same-origin",
                headers: { Accept: "application/json" },
            });
            const payload = await response.json().catch(() => null);
            if (!response.ok || !payload?.ok) throw new Error(payload?.error || "Не удалось загрузить колесо.");
            if (current !== session) return;

            syncClock(payload.server_time);
            enabled = Boolean(payload.enabled);
            prizes = (payload.sectors || []).slice(0, MAX_SECTORS).map(normalizePrize);
            nextSpinAt = payload.next_spin_at || null;
            setSpins(payload.available_spins);
            updateWalletBalance(payload.coin_balance);
            buildWheel();
            showIdle();
        } catch (error) {
            if (current !== session) return;
            phase = "idle";
            setCopy({ text: error.message || "Не удалось загрузить колесо." });
            noteNode.textContent = "";
            renderControls();
        }
    }

    const makeOperationId = () => {
        if (window.crypto?.randomUUID) return window.crypto.randomUUID();
        const bytes = new Uint8Array(16);
        window.crypto?.getRandomValues?.(bytes);
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
        return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    };

    const requestSpin = async () => {
        // A repeated request after a network error reuses the id, so one tap never spins twice.
        pendingOperationId = pendingOperationId || makeOperationId();
        const response = await fetch(sheet.dataset.spinUrl, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                Accept: "application/json",
                "Content-Type": "application/json",
                "X-CSRFToken": sheet.dataset.csrf,
            },
            body: JSON.stringify({ operation_id: pendingOperationId }),
        });
        const payload = await response.json().catch(() => null);
        if (!response.ok || !payload?.ok) {
            const error = new Error(payload?.error || "Не удалось прокрутить колесо.");
            error.code = payload?.code || "";
            if (FINAL_ERRORS.has(error.code)) pendingOperationId = "";
            throw error;
        }
        pendingOperationId = "";
        return payload;
    };

    // The prize may be missing from the wheel if the prizes changed since it was loaded.
    const winnerIndex = (payload) => {
        const prizeId = Number(payload.prize_id) || Number(payload.prize?.prize_id) || 0;
        let index = prizes.findIndex((prize) => prize.prizeId === prizeId);
        if (index < 0 && payload.prize) {
            const winner = normalizePrize(payload.prize);
            prizes = [...prizes, winner]
                .sort((a, b) => a.sectorOrder - b.sectorOrder || a.prizeId - b.prizeId)
                .slice(-MAX_SECTORS);
            buildWheel();
            index = prizes.findIndex((prize) => prize.prizeId === winner.prizeId);
        }
        return index;
    };

    const spinTo = (index, current) => new Promise((resolve) => {
        const slice = 360 / prizes.length;
        const start = rotation;
        const target = ((-index * slice) % 360 + 360) % 360;
        const delta = ((target - (start % 360)) % 360 + 360) % 360;
        const finish = start + 360 * (5 + Math.floor(Math.random() * 3)) + delta;
        const began = performance.now();
        let boundary = Math.floor((start + slice / 2) / slice);
        let lastTick = 0;

        const frame = (now) => {
            if (current !== session) {
                resolve();
                return;
            }
            const progress = Math.min((now - began) / SPIN_MS, 1);
            setRotation(start + (finish - start) * (1 - Math.pow(1 - progress, 4)));

            // A click every time a peg passes the pointer.
            const passed = Math.floor((rotation + slice / 2) / slice);
            if (passed !== boundary) {
                boundary = passed;
                if (now - lastTick > 45) {
                    lastTick = now;
                    sound.play("tick", 0.7);
                    haptic("selection");
                }
            }

            if (progress < 1) {
                requestAnimationFrame(frame);
                return;
            }
            setRotation(finish % 360);
            resolve();
        };
        requestAnimationFrame(frame);
    });

    const rewardText = (payload) => {
        const prize = payload.prize || {};
        const result = payload.reward_result || {};
        const value = Number(prize.reward_value) || 0;
        const amount = formatNumber(prize.reward_value);
        switch (prize.reward_type) {
            case "coins":
                return `+${amount} ${plural(value, "коин", "коина", "коинов")} уже на балансе.`;
            case "vip_days": {
                const until = Date.parse(result.vip_until || "");
                return Number.isFinite(until)
                    ? `VIP активирован до ${new Date(until).toLocaleDateString("ru-RU", { day: "numeric", month: "long" })}.`
                    : `VIP на ${amount} ${plural(value, "день", "дня", "дней")} активирован.`;
            }
            case "free_predictions":
                return `Добавлено ${amount} ${plural(value, "бесплатный прогноз", "бесплатных прогноза", "бесплатных прогнозов")}.`;
            case "promo_code":
                return "Промокод сохранён в бонусах. Нажми на него, чтобы скопировать.";
            case "rating_boost":
                return `Рейтинг вырос на ${amount}.`;
            case "extra_spin":
                return `+${amount} ${plural(value, "попытка", "попытки", "попыток")} к колесу.`;
            case "nothing":
                return prize.short_text || "Попробуй ещё раз — удача рядом.";
            default:
                return prize.short_text || "Награда уже начислена.";
        }
    };

    const showWin = (payload) => {
        const prize = payload.prize || {};
        const nothing = prize.reward_type === "nothing";
        phase = "won";
        setCopy({
            title: nothing ? "В этот раз мимо" : `Твой приз: ${prize.title || "подарок"}!`,
            text: rewardText(payload),
            icon: prize.icon_url || (nothing ? "" : sheet.dataset.giftIcon),
            code: prize.reward_type === "promo_code" ? payload.reward_result?.promo_code || prize.reward_text || "" : "",
        });
        // Restart the prize animation for every win.
        sheet.classList.remove("is-won");
        void panel.offsetWidth;
        sheet.classList.add("is-won");
        renderControls();
        startCountdown();
        if (nothing) {
            haptic("notify", "warning");
            return;
        }
        sound.play("win");
        confetti.burst();
        haptic("notify", "success");
    };

    const spin = async () => {
        if ((phase !== "idle" && phase !== "won") || !canSpin()) return;
        const current = session;
        spinButton.classList.add("is-pressed");
        window.setTimeout(() => spinButton.classList.remove("is-pressed"), 170);
        sound.unlock();
        confetti.stop();
        stopCountdown();
        phase = "spinning";
        sheet.classList.remove("is-won");
        setCopy({ text: "Крутим колесо…" });
        renderControls();
        haptic("impact", "medium");

        let payload;
        try {
            payload = await requestSpin();
        } catch (error) {
            if (current !== session) return;
            if (error.code === "no_spins") setSpins(0);
            showIdle(error.message);
            return;
        }
        spunHere = true;
        if (current !== session) return;

        syncClock(payload.server_time);
        nextSpinAt = payload.next_spin_at || null;
        setSpins(payload.available_spins);
        updateWalletBalance(payload.coin_balance ?? payload.reward_result?.coin_balance);
        const index = winnerIndex(payload);
        if (index >= 0) await spinTo(index, current);
        if (current !== session) return;
        showWin(payload);
    };

    const copyCode = async () => {
        const code = codeButton.dataset.code;
        if (!code) return;
        try {
            await navigator.clipboard.writeText(code);
            codeButton.textContent = "Скопировано";
            haptic("notify", "success");
            window.setTimeout(() => { codeButton.textContent = code; }, 1500);
        } catch (error) {
            window.getSelection()?.selectAllChildren(codeButton);
        }
    };

    const open = () => {
        if (!sheet.hidden && sheet.classList.contains("is-open")) return;
        window.clearTimeout(closeTimer);
        lastFocus = document.activeElement;
        sheet.hidden = false;
        document.documentElement.classList.add("is-roulette-sheet-open");
        void panel.offsetWidth;
        sheet.classList.add("is-open");
        sound.unlock();
        sheet.querySelector(".roulette-sheet-close").focus({ preventScroll: true });

        phase = "loading";
        sheet.classList.remove("is-won");
        setCopy({ text: "Загружаем призы…" });
        noteNode.textContent = "";
        renderControls();
        if (!disc.childElementCount) buildWheel();
        loadState();
    };

    const close = () => {
        if (sheet.hidden || !sheet.classList.contains("is-open")) return;
        session += 1;
        phase = "closed";
        stopCountdown();
        confetti.stop();
        sheet.classList.remove("is-open");
        document.documentElement.classList.remove("is-roulette-sheet-open");
        closeTimer = window.setTimeout(() => {
            sheet.hidden = true;
            sheet.classList.remove("is-won");
        }, 420);
        lastFocus?.focus?.({ preventScroll: true });
        // The bonuses page shows wins and tasks of its own: reload it to show this spin.
        if (spunHere && document.querySelector("[data-roulette-root]")) window.location.reload();
    };

    // Capture phase: runs before the page transition handler, which then leaves the link alone.
    document.addEventListener("click", (event) => {
        const trigger = event.target.closest("[data-roulette-sheet-open]");
        if (!trigger || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        open();
    }, true);

    sheet.querySelectorAll("[data-roulette-sheet-close]").forEach((node) => node.addEventListener("click", close));
    spinButton.addEventListener("click", spin);
    codeButton.addEventListener("click", copyCode);
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") close();
    });
})();
