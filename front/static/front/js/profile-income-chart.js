(() => {
    const block = document.querySelector("[data-income-chart]");
    const dataNode = document.getElementById("profile-income-chart-data");
    if (!block || !dataNode) return;

    let charts;
    try {
        charts = JSON.parse(dataNode.textContent || "{}");
    } catch (error) {
        console.error("Не удалось прочитать данные графика дохода.", error);
        return;
    }

    const canvas = block.querySelector("[data-income-chart-canvas]");
    const totalValue = block.querySelector("[data-income-total-value]");
    const totalCaption = block.querySelector("[data-income-total-caption]");
    const periodControls = Array.from(block.querySelectorAll("[data-income-period]"));
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const logical = {
        width: 1120,
        height: 560,
        left: 78,
        right: 1042,
        top: 74,
        bottom: 392,
        labelY: 436,
        legendY: 496,
    };
    const state = {
        period: "30",
        hoverIndex: null,
        pendingRender: false,
    };

    const toNumber = (value, fallback = 0) => {
        const number = Number(String(value ?? "").replace(",", "."));
        return Number.isFinite(number) ? number : fallback;
    };

    const scaleX = () => canvas.width / logical.width;
    const scaleY = () => canvas.height / logical.height;

    const resize = () => {
        const rect = canvas.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) {
            state.pendingRender = true;
            return false;
        }

        const dpr = Math.max(window.devicePixelRatio || 1, 1);
        const width = Math.max(Math.round(rect.width * dpr), 1);
        const height = Math.max(Math.round(rect.height * dpr), 1);
        if (canvas.width !== width || canvas.height !== height) {
            canvas.width = width;
            canvas.height = height;
        }
        state.pendingRender = false;
        return true;
    };

    const text = (value, x, y, options = {}) => {
        ctx.save();
        ctx.fillStyle = options.color || "#f7f8ff";
        ctx.font = `${options.weight || 600} ${options.size || 24}px Manrope Cappers, Inter, sans-serif`;
        ctx.textAlign = options.align || "left";
        ctx.textBaseline = options.baseline || "middle";
        ctx.fillText(value, x, y);
        ctx.restore();
    };

    const roundedRect = (x, y, width, height, radius) => {
        const r = Math.min(radius, width / 2, height / 2);
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.arcTo(x + width, y, x + width, y + height, r);
        ctx.arcTo(x + width, y + height, x, y + height, r);
        ctx.arcTo(x, y + height, x, y, r);
        ctx.arcTo(x, y, x + width, y, r);
        ctx.closePath();
    };

    const clear = () => {
        ctx.setTransform(scaleX(), 0, 0, scaleY(), 0, 0);
        ctx.clearRect(0, 0, logical.width, logical.height);
    };

    const chartSourceBounds = (chart) => {
        const ticks = chart.ticks || [];
        const tickPositions = ticks
            .map((tick) => toNumber(tick.y, Number.NaN))
            .filter(Number.isFinite);
        const sourceTop = Math.min(...tickPositions, 50);
        const sourceBottom = Math.max(...tickPositions, 200);
        return {
            left: toNumber(chart.plot_left, 42),
            right: toNumber(chart.plot_right, 530),
            top: sourceTop,
            bottom: sourceBottom,
        };
    };

    const mapX = (chart, x) => {
        const bounds = chartSourceBounds(chart);
        const span = Math.max(bounds.right - bounds.left, 1);
        return logical.left + ((toNumber(x) - bounds.left) / span) * (logical.right - logical.left);
    };

    const mapY = (chart, y) => {
        const bounds = chartSourceBounds(chart);
        const span = Math.max(bounds.bottom - bounds.top, 1);
        return logical.top + ((toNumber(y) - bounds.top) / span) * (logical.bottom - logical.top);
    };

    const drawGrid = (chart) => {
        ctx.save();
        (chart.ticks || []).forEach((tick) => {
            const y = mapY(chart, tick.y);
            const isZero = tick.label === "0";
            ctx.strokeStyle = isZero ? "rgba(255,255,255,.28)" : "rgba(255,255,255,.08)";
            ctx.lineWidth = isZero ? 1.8 : 1;
            ctx.setLineDash(isZero ? [] : [4, 12]);
            ctx.beginPath();
            ctx.moveTo(logical.left, y);
            ctx.lineTo(logical.right, y);
            ctx.stroke();
            text(tick.label || "", 0, y, {
                color: isZero ? "#c6c7cc" : "#777980",
                size: 16,
                weight: 600,
            });
        });
        ctx.restore();
    };

    const drawBars = (chart) => {
        const pointCount = Math.max((chart.points || []).length, 1);
        const barWidth = Math.max(Math.min(((logical.right - logical.left) / pointCount) * 0.34, 8), 3);
        (chart.points || []).forEach((point) => {
            if (!point.has_bar) return;
            const centerX = mapX(chart, point.x);
            const x = centerX - barWidth / 2;
            const y1 = mapY(chart, point.bar_y);
            const y2 = mapY(chart, toNumber(point.bar_y) + toNumber(point.bar_height));
            const y = Math.min(y1, y2);
            const height = Math.max(Math.abs(y2 - y1), 3);
            const isNegative = String(point.amount_display || "").startsWith("-");
            ctx.fillStyle = isNegative ? "#ff5c67" : "#54db87";
            roundedRect(x, y, barWidth, height, barWidth / 2);
            ctx.fill();
        });
    };

    const drawLine = (chart) => {
        const points = chart.points || [];
        if (!points.length) return;

        ctx.save();
        ctx.strokeStyle = "#f4ee47";
        ctx.lineWidth = 3.5;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.beginPath();
        points.forEach((point, index) => {
            const x = mapX(chart, point.x);
            const y = mapY(chart, point.line_y);
            if (index === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        const lastPoint = points[points.length - 1];
        ctx.fillStyle = "#171718";
        ctx.strokeStyle = "#f4ee47";
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(mapX(chart, lastPoint.x), mapY(chart, lastPoint.line_y), 7, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.restore();
    };

    const drawLabels = (chart) => {
        (chart.labels || []).forEach((label) => {
            text(label.text || "", mapX(chart, label.x), logical.labelY, {
                color: "#8d8f96",
                size: 15,
                weight: 600,
                align: "center",
            });
        });
    };

    const drawLegend = () => {
        ctx.fillStyle = "#54db87";
        roundedRect(88, logical.legendY - 8, 16, 16, 8);
        ctx.fill();
        ctx.fillStyle = "#ff5c67";
        roundedRect(110, logical.legendY - 8, 16, 16, 8);
        ctx.fill();
        text("Дневной результат", 140, logical.legendY, {
            color: "#9b9da4",
            size: 17,
            weight: 600,
        });

        ctx.strokeStyle = "#f4ee47";
        ctx.lineWidth = 3.5;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.moveTo(382, logical.legendY);
        ctx.lineTo(430, logical.legendY);
        ctx.stroke();
        text("Накопительный итог", 448, logical.legendY, {
            color: "#9b9da4",
            size: 17,
            weight: 600,
        });
    };

    const drawTooltip = (chart) => {
        if (state.hoverIndex === null) return;
        const point = chart.points?.[state.hoverIndex];
        if (!point) return;

        const x = mapX(chart, point.x);
        const y = mapY(chart, point.line_y);
        const boxWidth = 270;
        const boxHeight = 106;
        const boxX = x > 770 ? x - boxWidth - 24 : x + 24;
        const boxY = Math.max(24, Math.min(300, y - 78));

        ctx.save();
        ctx.strokeStyle = "rgba(255,255,255,.18)";
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 8]);
        ctx.beginPath();
        ctx.moveTo(x, logical.top);
        ctx.lineTo(x, logical.bottom);
        ctx.stroke();

        ctx.setLineDash([]);
        ctx.fillStyle = "#f4ee47";
        ctx.beginPath();
        ctx.arc(x, y, 6, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = "#1f1f21";
        roundedRect(boxX, boxY, boxWidth, boxHeight, 12);
        ctx.fill();
        ctx.strokeStyle = "rgba(255,255,255,.08)";
        ctx.lineWidth = 1;
        ctx.stroke();

        text(point.date || "", boxX + 18, boxY + 25, {
            color: "#9b9da4",
            size: 15,
            weight: 600,
        });
        text(`Прибыль: ${point.amount_display} коинов`, boxX + 18, boxY + 58, {
            color: String(point.amount_display || "").startsWith("-") ? "#ff5c67" : "#54db87",
            size: 16,
            weight: 700,
        });
        text(`Итог: ${point.cumulative_display} коинов`, boxX + 18, boxY + 87, {
            color: "#ffffff",
            size: 16,
            weight: 600,
        });
        ctx.restore();
    };

    const updateSummary = (chart) => {
        if (totalValue) {
            totalValue.textContent = `${chart.total_sign || ""}${chart.total_display} коинов`;
            totalValue.style.color = chart.total_color || "#ffffff";
        }
        if (totalCaption) totalCaption.textContent = chart.period_caption || "";
        canvas.setAttribute("aria-label", `График прибыли в коинах ${chart.period_caption || ""}`.trim());
    };

    const updateControls = () => {
        periodControls.forEach((control) => {
            const isActive = control.dataset.incomePeriod === state.period;
            control.classList.toggle("is-active", isActive);
            control.setAttribute("aria-pressed", isActive ? "true" : "false");
        });
    };

    const render = () => {
        if (!resize()) return;
        const chart = charts[state.period] || charts["30"];
        if (!chart) return;

        clear();
        drawGrid(chart);
        drawBars(chart);
        drawLine(chart);
        drawLabels(chart);
        drawLegend();
        drawTooltip(chart);
        updateSummary(chart);
        updateControls();
        window.CappersSkeleton?.ready(block);
    };

    const hoverIndexFromEvent = (event) => {
        const chart = charts[state.period] || charts["30"];
        const points = chart?.points || [];
        if (!points.length) return null;

        const rect = canvas.getBoundingClientRect();
        const x = (event.clientX - rect.left) / rect.width * logical.width;
        let closestIndex = 0;
        let closestDistance = Infinity;
        points.forEach((point, index) => {
            const distance = Math.abs(mapX(chart, point.x) - x);
            if (distance < closestDistance) {
                closestDistance = distance;
                closestIndex = index;
            }
        });
        return closestDistance <= 24 ? closestIndex : null;
    };

    periodControls.forEach((control) => {
        control.addEventListener("click", () => {
            state.period = control.dataset.incomePeriod || "30";
            state.hoverIndex = null;
            render();
        });
    });

    canvas.addEventListener("pointermove", (event) => {
        const nextIndex = hoverIndexFromEvent(event);
        if (nextIndex === state.hoverIndex) return;
        state.hoverIndex = nextIndex;
        render();
    });
    canvas.addEventListener("pointerleave", () => {
        if (state.hoverIndex === null) return;
        state.hoverIndex = null;
        render();
    });
    window.addEventListener("resize", render);
    window.addEventListener("profile:tab-activated", (event) => {
        if (event.detail?.tab !== "profile" && !state.pendingRender) return;
        requestAnimationFrame(render);
    });

    if ("ResizeObserver" in window) {
        const observer = new ResizeObserver(() => render());
        observer.observe(canvas);
    }

    render();
})();
