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

    const svg = block.querySelector("[data-income-chart-svg]");
    const grid = svg?.querySelector("[data-income-grid]");
    const bars = svg?.querySelector("[data-income-bars]");
    const line = svg?.querySelector("[data-income-line]");
    const labels = svg?.querySelector("[data-income-labels]");
    const hitZones = svg?.querySelector("[data-income-hit-zones]");
    const tooltip = svg?.querySelector("[data-income-tooltip]");
    const tooltipGuide = tooltip?.querySelector("[data-income-tooltip-guide]");
    const tooltipMarker = tooltip?.querySelector("[data-income-tooltip-marker]");
    const tooltipBox = tooltip?.querySelector("[data-income-tooltip-box]");
    const tooltipDate = tooltip?.querySelector("[data-income-tooltip-date]");
    const tooltipProfit = tooltip?.querySelector("[data-income-tooltip-profit]");
    const tooltipTotal = tooltip?.querySelector("[data-income-tooltip-total]");
    const totalValue = svg?.querySelector("[data-income-total-value]");
    const totalCaption = svg?.querySelector("[data-income-total-caption]");
    const periodControls = Array.from(block.querySelectorAll("[data-income-period]"));

    if (!svg || !grid || !bars || !line || !labels || !hitZones || !tooltip) return;

    const SVG_NS = "http://www.w3.org/2000/svg";
    const createSvg = (tag, attributes = {}, text = "") => {
        const node = document.createElementNS(SVG_NS, tag);
        Object.entries(attributes).forEach(([name, value]) => node.setAttribute(name, String(value)));
        if (text !== "") node.textContent = text;
        return node;
    };

    const hideTooltip = () => {
        tooltip.setAttribute("visibility", "hidden");
    };

    const showTooltip = (point) => {
        const x = Number(point.x);
        const y = Number(point.line_y);
        if (!Number.isFinite(x) || !Number.isFinite(y)) return;

        const boxWidth = 148;
        const boxX = x > 382 ? x - boxWidth - 12 : x + 12;
        const boxY = Math.max(8, Math.min(132, y - 68));

        tooltipGuide?.setAttribute("x1", point.x);
        tooltipGuide?.setAttribute("x2", point.x);
        tooltipMarker?.setAttribute("cx", point.x);
        tooltipMarker?.setAttribute("cy", point.line_y);
        tooltipBox?.setAttribute("transform", `translate(${boxX} ${boxY})`);

        if (tooltipDate) tooltipDate.textContent = point.date;
        if (tooltipProfit) {
            tooltipProfit.textContent = `Прибыль: ${point.amount_display} коинов`;
            tooltipProfit.setAttribute(
                "fill",
                String(point.amount_display).startsWith("-") ? "#ff5c67" : "#54db87",
            );
        }
        if (tooltipTotal) tooltipTotal.textContent = `Итог: ${point.cumulative_display} коинов`;
        tooltip.setAttribute("visibility", "visible");
    };

    const renderChart = (period) => {
        const chart = charts[period];
        if (!chart) return;

        hideTooltip();
        grid.replaceChildren();
        bars.replaceChildren();
        line.replaceChildren();
        labels.replaceChildren();
        hitZones.replaceChildren();

        (chart.ticks || []).forEach((tick) => {
            grid.append(
                createSvg("line", {
                    x1: 42,
                    y1: tick.y,
                    x2: 530,
                    y2: tick.y,
                    stroke: "rgba(255,255,255,.10)",
                    "stroke-width": 1,
                    "stroke-dasharray": "3 5",
                }),
                createSvg(
                    "text",
                    {
                        x: 0,
                        y: tick.label_y,
                        fill: "#707072",
                        "font-size": 9,
                        "font-weight": 600,
                    },
                    tick.label,
                ),
            );
        });

        (chart.points || []).forEach((point) => {
            if (point.has_bar) {
                bars.appendChild(
                    createSvg("rect", {
                        x: point.bar_x,
                        y: point.bar_y,
                        width: chart.bar_width,
                        height: point.bar_height,
                        rx: 1.5,
                        fill: point.bar_fill,
                    }),
                );
            }
        });

        if (chart.line_path) {
            line.appendChild(
                createSvg("path", {
                    d: chart.line_path,
                    fill: "none",
                    stroke: "#fbf110",
                    "stroke-width": 2.5,
                    "stroke-linecap": "round",
                    "stroke-linejoin": "round",
                }),
            );
            const lastPoint = chart.points?.[chart.points.length - 1];
            if (lastPoint) {
                line.appendChild(
                    createSvg("circle", {
                        cx: lastPoint.x,
                        cy: lastPoint.line_y,
                        r: 4,
                        fill: "#fbf110",
                    }),
                );
            }
        }

        (chart.labels || []).forEach((label) => {
            labels.appendChild(
                createSvg(
                    "text",
                    {
                        x: label.x,
                        y: 219,
                        "text-anchor": "middle",
                        fill: "#707072",
                        "font-size": 8,
                        "font-weight": 600,
                    },
                    label.text,
                ),
            );
        });

        const points = chart.points || [];
        const hitWidth = Math.max(6, Math.min(34, 488 / Math.max(points.length - 1, 1)));
        points.forEach((point) => {
            const zone = createSvg("rect", {
                x: Number(point.x) - (hitWidth / 2),
                y: 44,
                width: hitWidth,
                height: 160,
                fill: "transparent",
                "pointer-events": "all",
            });
            zone.addEventListener("pointerenter", () => showTooltip(point));
            zone.addEventListener("pointermove", () => showTooltip(point));
            hitZones.appendChild(zone);
        });

        if (totalValue) {
            totalValue.textContent = `${chart.total_sign || ""}${chart.total_display} коинов`;
            totalValue.setAttribute("fill", chart.total_color || "#ffffff");
        }
        if (totalCaption) totalCaption.textContent = chart.period_caption || "";

        svg.setAttribute("aria-label", `График прибыли в коинах ${chart.period_caption || ""}`.trim());

        periodControls.forEach((control) => {
            const isActive = control.dataset.incomePeriod === period;
            control.setAttribute("aria-pressed", isActive ? "true" : "false");
            control.querySelector("rect")?.setAttribute("fill", isActive ? "#0b56fa" : "#29292c");
            control.querySelector("text")?.setAttribute("fill", isActive ? "#ffffff" : "#9a9a9d");
        });

        window.CappersSkeleton?.ready(block);
    };

    periodControls.forEach((control) => {
        const activate = () => renderChart(control.dataset.incomePeriod || "30");
        control.addEventListener("click", activate);
        control.addEventListener("keydown", (event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            activate();
        });
    });

    svg.addEventListener("pointerleave", hideTooltip);
    renderChart("30");
})();
