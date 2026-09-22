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
        left: 86,
        right: 1064,
        top: 70,
        bottom: 430,
        legendY: 505,
    };
    const state = {
        period: "30",
        hoverIndex: null,
    };

    const toNumber = (value, fallback = 0) => {
        const number = Number(String(value ?? "").replace(",", "."));
        return Number.isFinite(number) ? number : fallback;
    };

    const scaleX = () => canvas.width / logical.width;
    const scaleY = () => canvas.height / logical.height;

    const resize = () => {
        const rect = canvas.getBoundingClientRect();
        const dpr = Math.max(window.devicePixelRatio || 1, 1);
        const width = Math.max(Math.round(rect.width * dpr), 1);
        const height = Math.max(Math.round(rect.height * dpr), 1);
        if (canvas.width !== width || canvas.height !== height) {
            canvas.width = width;
            canvas.height = height;
        }
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

    const drawGrid = (chart) => {
        ctx.save();
        ctx.strokeStyle = "rgba(255,255,255,.12)";
        ctx.lineWidth = 1.5;
        ctx.setLineDash([7, 9]);
        (chart.ticks || []).forEach((tick) => {
            const y = toNumber(tick.y);
            ctx.beginPath();
            ctx.moveTo(logical.left, y);
            ctx.lineTo(logical.right, y);
            ctx.stroke();
            text(tick.label || "", 0, toNumber(tick.label_y), {
                color: "#858589",
                size: 19,
                weight: 600,
            });
        });
        ctx.restore();
    };

    const drawBars = (chart) => {
        const barWidth = Math.max(toNumber(chart.bar_width) * 1.55, 5);
        (chart.points || []).forEach((point) => {
            if (!point.has_bar) return;
            const centerX = toNumber(point.x);
            const x = centerX - barWidth / 2;
            const y = toNumber(point.bar_y);
            const height = Math.max(toNumber(point.bar_height), 2.5);
            ctx.fillStyle = point.bar_fill || "#0b56fa";
            roundedRect(x, y, barWidth, height, 4);
            ctx.fill();
        });
    };

    const drawLine = (chart) => {
        const points = chart.points || [];
        if (!points.length) return;

        ctx.save();
        ctx.strokeStyle = "#fbf110";
        ctx.lineWidth = 6;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.beginPath();
        points.forEach((point, index) => {
            const x = toNumber(point.x);
            const y = toNumber(point.line_y);
            if (index === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        const lastPoint = points[points.length - 1];
        ctx.fillStyle = "#fbf110";
        ctx.beginPath();
        ctx.arc(toNumber(lastPoint.x), toNumber(lastPoint.line_y), 8, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
    };

    const drawLabels = (chart) => {
        (chart.labels || []).forEach((label) => {
            text(label.text || "", toNumber(label.x), 470, {
                color: "#858589",
                size: 18,
                weight: 600,
                align: "center",
            });
        });
    };

    const drawLegend = () => {
        ctx.fillStyle = "#0b56fa";
        roundedRect(88, logical.legendY - 11, 18, 18, 4);
        ctx.fill();
        text("Прибыль, коины", 120, logical.legendY, {
            color: "#929296",
            size: 20,
            weight: 600,
        });

        ctx.strokeStyle = "#fbf110";
        ctx.lineWidth = 6;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.moveTo(324, logical.legendY);
        ctx.lineTo(370, logical.legendY);
        ctx.stroke();
        text("Накопительный итог", 388, logical.legendY, {
            color: "#929296",
            size: 20,
            weight: 600,
        });
    };

    const drawTooltip = (chart) => {
        if (state.hoverIndex === null) return;
        const point = chart.points?.[state.hoverIndex];
        if (!point) return;

        const x = toNumber(point.x);
        const y = toNumber(point.line_y);
        const boxWidth = 250;
        const boxHeight = 112;
        const boxX = x > 770 ? x - boxWidth - 24 : x + 24;
        const boxY = Math.max(20, Math.min(278, y - 86));

        ctx.save();
        ctx.strokeStyle = "rgba(255,255,255,.26)";
        ctx.lineWidth = 1.5;
        ctx.setLineDash([6, 8]);
        ctx.beginPath();
        ctx.moveTo(x, logical.top);
        ctx.lineTo(x, logical.bottom);
        ctx.stroke();

        ctx.setLineDash([]);
        ctx.fillStyle = "#fbf110";
        ctx.beginPath();
        ctx.arc(x, y, 9, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = "#131313";
        roundedRect(boxX, boxY, boxWidth, boxHeight, 14);
        ctx.fill();

        text(point.date || "", boxX + 18, boxY + 25, {
            color: "#929296",
            size: 17,
            weight: 600,
        });
        text(`Прибыль: ${point.amount_display} коинов`, boxX + 18, boxY + 58, {
            color: String(point.amount_display || "").startsWith("-") ? "#ff5c67" : "#54db87",
            size: 18,
            weight: 700,
        });
        text(`Итог: ${point.cumulative_display} коинов`, boxX + 18, boxY + 87, {
            color: "#ffffff",
            size: 17,
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
        resize();
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
            const distance = Math.abs(toNumber(point.x) - x);
            if (distance < closestDistance) {
                closestDistance = distance;
                closestIndex = index;
            }
        });
        return closestDistance <= 36 ? closestIndex : null;
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

    render();
})();
