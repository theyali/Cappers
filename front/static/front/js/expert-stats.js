(() => {
    const root = document.querySelector("[data-profit-chart]");
    const dataNode = document.getElementById("expert-profit-chart-data");
    if (!root || !dataNode) return;

    let chartData = {};
    try {
        chartData = JSON.parse(dataNode.textContent || "{}");
    } catch (error) {
        return;
    }

    const width = 760;
    const height = 260;
    const paddingY = 22;
    const path = root.querySelector("[data-profit-path]");
    const pointsGroup = root.querySelector("[data-profit-points]");
    const zeroLine = root.querySelector(".expert-profit-zero");
    const tooltip = root.querySelector("[data-profit-tooltip]");
    const valueNode = root.querySelector("[data-profit-chart-value]");
    const captionNode = root.querySelector("[data-profit-chart-caption]");
    const startNode = root.querySelector("[data-profit-start]");
    const maxNode = root.querySelector("[data-profit-max]");
    const minNode = root.querySelector("[data-profit-min]");
    const canvas = root.querySelector(".expert-profit-canvas");
    const svg = root.querySelector("svg");
    const buttons = Array.from(root.querySelectorAll("[data-profit-days]"));

    const signed = (value) => {
        const number = Number(value || 0);
        const prefix = number > 0 ? "+" : "";
        return `${prefix}${number.toFixed(2)}`;
    };

    const compact = (value) => {
        const number = Number(value || 0);
        const absolute = Math.abs(number);
        if (absolute >= 1000000) return `${(number / 1000000).toFixed(1)}m`;
        if (absolute >= 1000) return `${(number / 1000).toFixed(1)}k`;
        return number.toFixed(0);
    };

    const pointCoordinates = (items) => {
        const values = items.map((item) => Number(item.value || 0));
        let min = Math.min(0, ...values);
        let max = Math.max(0, ...values);

        if (min === max) {
            min -= 1;
            max += 1;
        } else {
            const padding = Math.max((max - min) * 0.12, 1);
            min -= padding;
            max += padding;
        }

        const usableHeight = height - paddingY * 2;
        const toY = (value) => paddingY + ((max - value) / (max - min)) * usableHeight;
        const toX = (index) => {
            if (items.length <= 1) return width / 2;
            return (index / (items.length - 1)) * width;
        };

        return {
            min,
            max,
            zeroY: toY(0),
            points: items.map((item, index) => ({
                ...item,
                x: toX(index),
                y: toY(Number(item.value || 0)),
            })),
        };
    };

    const hideTooltip = () => {
        if (tooltip) tooltip.hidden = true;
    };

    const render = (days) => {
        const items = Array.isArray(chartData[String(days)]) ? chartData[String(days)] : [];
        const geometry = pointCoordinates(items);
        const chartPoints = geometry.points;
        const last = chartPoints[chartPoints.length - 1];
        const finalValue = last ? Number(last.value || 0) : 0;

        root.classList.toggle("is-positive", finalValue > 0);
        root.classList.toggle("is-negative", finalValue < 0);

        if (valueNode) valueNode.textContent = signed(finalValue);
        if (captionNode) captionNode.textContent = `за последние ${days} дней`;
        if (startNode) startNode.textContent = chartPoints[0]?.label || "—";
        if (maxNode) maxNode.textContent = compact(geometry.max);
        if (minNode) minNode.textContent = compact(geometry.min);

        if (zeroLine) {
            zeroLine.setAttribute("y1", geometry.zeroY.toFixed(2));
            zeroLine.setAttribute("y2", geometry.zeroY.toFixed(2));
        }

        if (path) {
            path.setAttribute(
                "d",
                chartPoints.length
                    ? chartPoints.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(" ")
                    : "",
            );
        }

        if (pointsGroup) {
            pointsGroup.innerHTML = "";
            chartPoints.forEach((point, index) => {
                const previous = chartPoints[index - 1];
                const changed = !previous || Number(previous.value) !== Number(point.value);
                const shouldShow = changed && (days <= 30 || index === chartPoints.length - 1 || index % 3 === 0);
                if (!shouldShow && index !== chartPoints.length - 1) return;

                const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
                circle.setAttribute("class", "expert-profit-point");
                circle.setAttribute("cx", point.x.toFixed(2));
                circle.setAttribute("cy", point.y.toFixed(2));
                circle.setAttribute("r", index === chartPoints.length - 1 ? "5" : "3.5");
                pointsGroup.appendChild(circle);
            });
        }

        root.dataset.activeDays = String(days);
        root._profitPoints = chartPoints;
        buttons.forEach((button) => {
            button.classList.toggle("is-active", Number(button.dataset.profitDays) === Number(days));
        });
        hideTooltip();
    };

    buttons.forEach((button) => {
        button.addEventListener("click", () => render(Number(button.dataset.profitDays || 30)));
    });

    if (canvas && svg && tooltip) {
        canvas.addEventListener("mousemove", (event) => {
            const items = root._profitPoints || [];
            if (!items.length) return hideTooltip();

            const rect = canvas.getBoundingClientRect();
            const localX = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
            const svgX = rect.width ? (localX / rect.width) * width : 0;
            let nearest = items[0];
            let distance = Math.abs(nearest.x - svgX);

            for (const item of items) {
                const nextDistance = Math.abs(item.x - svgX);
                if (nextDistance < distance) {
                    nearest = item;
                    distance = nextDistance;
                }
            }

            const left = rect.width ? (nearest.x / width) * rect.width : 0;
            const top = rect.height ? (nearest.y / height) * rect.height : 0;
            tooltip.innerHTML = `<span>${nearest.label}</span><strong>${signed(nearest.value)}</strong>`;
            tooltip.style.left = `${left}px`;
            tooltip.style.top = `${top}px`;
            tooltip.hidden = false;
        });
        canvas.addEventListener("mouseleave", hideTooltip);
    }

    render(30);
})();
