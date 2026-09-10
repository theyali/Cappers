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

    buttons.forEach((button) => {
        button.style.border = "0";
        button.style.appearance = "none";
        button.style.webkitAppearance = "none";
    });
    document.querySelectorAll(".expert-follow-button").forEach((button) => {
        button.style.border = "0";
    });

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

        const lineColor = finalValue > 0 ? "var(--green)" : finalValue < 0 ? "var(--danger)" : "var(--blue)";
        if (path) path.style.stroke = lineColor;
        if (valueNode) {
            valueNode.textContent = signed(finalValue);
            valueNode.style.color = lineColor;
        }
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

(() => {
    const root = document.querySelector("[data-sidebar-profit]");
    const dataNode = document.getElementById("expert-sidebar-profit-data");
    if (!root || !dataNode) return;

    let periods = {};
    try {
        periods = JSON.parse(dataNode.textContent || "{}");
    } catch (error) {
        window.CappersSkeleton?.ready(root);
        return;
    }

    const order = ["all", "90", "30", "7"];
    const control = root.querySelector("[data-sidebar-profit-period-control]");
    const periodLabel = root.querySelector("[data-sidebar-profit-period-label]");
    const valueNode = root.querySelector("[data-sidebar-profit-value]");
    const unitNode = root.querySelector("[data-sidebar-profit-unit]");
    const countNode = root.querySelector("[data-sidebar-profit-count]");
    const roiNode = root.querySelector("[data-sidebar-profit-roi]");
    const avgNode = root.querySelector("[data-sidebar-profit-avg]");
    const bars = Array.from(root.querySelectorAll("[data-sidebar-profit-bar]"));
    const gridLines = Array.from(root.querySelectorAll("[data-sidebar-profit-grid]"));
    const axisLabels = Array.from(root.querySelectorAll("[data-sidebar-profit-axis]"));
    const chartCanvas = root.querySelector("[data-sidebar-profit-chart]");
    const chartFallback = root.querySelector("[data-sidebar-profit-chart-fallback]");

    let activeKey = root.dataset.activePeriod || "all";
    let chart = null;

    const toneColor = (value) => {
        const number = Number(value || 0);
        if (number > 0) return "#5ea731";
        if (number < 0) return "#fd1a01";
        return "#f7f8ff";
    };

    const barColor = (tone) => {
        if (tone === "positive") return "#5ea731";
        if (tone === "negative") return "#fd1a01";
        if (tone === "neutral") return "#fbf110";
        return "#707072";
    };

    const parseCompactNumber = (value) => {
        const text = String(value ?? "0").trim().toLowerCase().replace(",", ".");
        const match = text.match(/^(-?[\d.]+)\s*([km])?$/);
        if (!match) return 0;
        const number = Number(match[1] || 0);
        if (!Number.isFinite(number)) return 0;
        if (match[2] === "k") return number * 1000;
        if (match[2] === "m") return number * 1000000;
        return number;
    };

    const compactNumber = (value) => {
        const number = Number(value || 0);
        const absolute = Math.abs(number);
        if (absolute >= 1000000) return `${(number / 1000000).toFixed(1).replace(".0", "")}m`;
        if (absolute >= 1000) return `${(number / 1000).toFixed(1).replace(".0", "")}k`;
        if (absolute >= 100) return String(Math.round(number));
        return number.toFixed(1).replace(".0", "");
    };

    const chartBounds = (period) => {
        const max = Math.max(parseCompactNumber(period.axis?.[0]), 1);
        const parsedMin = parseCompactNumber(period.axis?.[3]);
        const min = parsedMin < 0 ? parsedMin : -(max / 2);
        return { min, max };
    };

    const chartValues = (period) => {
        const periodBars = Array.isArray(period.bars) ? period.bars : [];
        const chartTop = Number(period.grid?.[0] ?? 0);
        const zeroY = Number(period.grid?.[2] ?? 1);
        const chartBottom = Number(period.grid?.[3] ?? zeroY + 1);
        const positiveHeight = Math.max(zeroY - chartTop, 1);
        const negativeHeight = Math.max(chartBottom - zeroY, 1);
        const bounds = chartBounds(period);

        return periodBars.map((bar) => {
            if (!bar?.visible) return null;
            const height = Math.max(0, Number(bar.height || 0));
            if (bar.tone === "positive") {
                return (height / positiveHeight) * bounds.max;
            }
            if (bar.tone === "negative") {
                return -((height / negativeHeight) * Math.abs(bounds.min));
            }
            return 0;
        });
    };

    const chartConfig = (period) => {
        const values = chartValues(period);
        const bounds = chartBounds(period);
        return {
            type: "bar",
            data: {
                labels: values.map((_, index) => String(index + 1)),
                datasets: [
                    {
                        data: values,
                        backgroundColor: (context) => {
                            const value = Number(context.raw || 0);
                            if (value > 0) return "#5ea731";
                            if (value < 0) return "#fd1a01";
                            return "#fbf110";
                        },
                        borderWidth: 0,
                        borderSkipped: false,
                        borderRadius: 2,
                        categoryPercentage: 0.74,
                        barPercentage: 0.72,
                        maxBarThickness: 10,
                    },
                ],
            },
            options: {
                responsive: false,
                maintainAspectRatio: false,
                animation: {
                    duration: 220,
                },
                interaction: {
                    mode: "nearest",
                    axis: "x",
                    intersect: true,
                },
                layout: {
                    padding: {
                        top: 4,
                        right: 0,
                        bottom: 4,
                        left: 0,
                    },
                },
                plugins: {
                    legend: {
                        display: false,
                    },
                    tooltip: {
                        displayColors: false,
                        backgroundColor: "#131313",
                        titleColor: "#707072",
                        bodyColor: "#f7f8ff",
                        borderWidth: 0,
                        padding: 8,
                        cornerRadius: 8,
                        callbacks: {
                            title: () => "",
                            label: (context) => {
                                const number = Number(context.raw || 0);
                                const prefix = number > 0 ? "+" : "";
                                return `${prefix}${number.toFixed(1)} ед.`;
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        display: false,
                        grid: {
                            display: false,
                        },
                        border: {
                            display: false,
                        },
                    },
                    y: {
                        position: "right",
                        min: bounds.min,
                        max: bounds.max,
                        afterBuildTicks: (scale) => {
                            const max = Number(scale.max || 0);
                            const min = Number(scale.min || 0);
                            scale.ticks = [max, max / 2, 0, min].map((value) => ({ value }));
                        },
                        ticks: {
                            color: "#a2a2a5",
                            padding: 8,
                            font: {
                                family: "Manrope Cappers, sans-serif",
                                size: 12,
                                weight: "600",
                            },
                            callback: (value) => compactNumber(value),
                        },
                        grid: {
                            color: "#303033",
                            lineWidth: 1,
                            drawTicks: false,
                        },
                        border: {
                            display: false,
                        },
                    },
                },
            },
        };
    };

    const updateChart = (period) => {
        if (!chartCanvas || typeof window.Chart !== "function") return;

        if (!chart) {
            chart = new window.Chart(chartCanvas, chartConfig(period));
            if (chartFallback) chartFallback.setAttribute("opacity", "0");
            return;
        }

        const values = chartValues(period);
        const bounds = chartBounds(period);
        chart.data.labels = values.map((_, index) => String(index + 1));
        chart.data.datasets[0].data = values;
        chart.options.scales.y.min = bounds.min;
        chart.options.scales.y.max = bounds.max;
        chart.update();
    };

    const renderPeriod = (key, showSkeleton = false) => {
        const period = periods[key];
        if (!period) return;

        if (showSkeleton) window.CappersSkeleton?.loading(root);

        activeKey = key;
        root.dataset.activePeriod = key;

        if (periodLabel) periodLabel.textContent = period.label || "Все время";
        if (valueNode) {
            valueNode.textContent = period.profit_display || "0.0";
            valueNode.setAttribute("fill", toneColor(period.profit));
        }
        if (unitNode) unitNode.setAttribute("fill", toneColor(period.profit));
        if (countNode) countNode.textContent = String(period.count ?? 0);
        if (roiNode) {
            roiNode.textContent = period.roi_display || "0.0%";
            roiNode.setAttribute("fill", toneColor(period.roi));
        }
        if (avgNode) avgNode.textContent = period.avg_coefficient_display || "0.00";

        gridLines.forEach((line, index) => {
            const y = period.grid?.[index];
            if (y == null) return;
            line.setAttribute("y1", String(y));
            line.setAttribute("y2", String(y));
        });

        axisLabels.forEach((label, index) => {
            label.textContent = period.axis?.[index] ?? "0";
        });

        bars.forEach((node, index) => {
            const bar = period.bars?.[index];
            if (!bar) {
                node.setAttribute("opacity", "0");
                return;
            }
            node.setAttribute("x", String(bar.x));
            node.setAttribute("y", String(bar.y));
            node.setAttribute("height", String(bar.height));
            node.setAttribute("fill", barColor(bar.tone));
            node.setAttribute("opacity", bar.visible ? "1" : "0");
        });

        updateChart(period);
        window.CappersSkeleton?.ready(root);
    };

    const selectNextPeriod = () => {
        const currentIndex = Math.max(0, order.indexOf(activeKey));
        const nextKey = order[(currentIndex + 1) % order.length];
        renderPeriod(nextKey, true);
    };

    if (control) {
        control.addEventListener("click", selectNextPeriod);
        control.addEventListener("keydown", (event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            selectNextPeriod();
        });
    }

    renderPeriod(activeKey);
})();

(() => {
    const page = document.querySelector(".expert-public-page");
    if (!page) return;

    const chartBlocks = Array.from(page.querySelectorAll("[data-prediction-bank-chart]"));
    if (!chartBlocks.length) return;

    const columns = "minmax(260px, 1.55fr) minmax(170px, .9fr) minmax(180px, 1fr) 94px 94px minmax(156px, .85fr) 88px";
    const table = chartBlocks[0].closest(".content-table-scroll");
    const head = table?.querySelector(".prediction-table-head");

    if (head) {
        head.style.gridTemplateColumns = columns;
        const labels = Array.from(head.children);
        const tail = labels[labels.length - 1];
        if (tail && !head.querySelector("[data-bank-chart-head]")) {
            tail.textContent = "График банка";
            tail.dataset.bankChartHead = "";
            head.appendChild(document.createElement("span"));
        }
    }

    chartBlocks.forEach((block) => {
        const row = block.closest(".prediction-table-row");
        if (row) row.style.gridTemplateColumns = columns;
        window.CappersSkeleton?.loading(block);
    });

    const numberValue = (value) => {
        const normalized = String(value ?? "0").trim().replace(/\s+/g, "").replace(",", ".");
        const parsed = Number(normalized);
        return Number.isFinite(parsed) ? parsed : 0;
    };

    const profitFor = (block) => {
        const state = block.dataset.bankState || "pending";
        const stake = numberValue(block.dataset.bankStake);
        const payout = numberValue(block.dataset.bankPayout);
        if (state === "win") return payout - stake;
        if (state === "lose") return -stake;
        return 0;
    };

    const colorFor = (state) => {
        if (state === "win") return "#5ea731";
        if (state === "lose") return "#fd1a01";
        return "#707072";
    };

    const chronological = [...chartBlocks].reverse();
    const bankHistory = [0];
    const pointsByBlock = new Map();

    chronological.forEach((block) => {
        const next = bankHistory[bankHistory.length - 1] + profitFor(block);
        bankHistory.push(Number(next.toFixed(2)));

        let points = bankHistory.slice(Math.max(0, bankHistory.length - 9));
        while (points.length < 9) points.unshift(points[0] ?? 0);

        const state = block.dataset.bankState || "pending";
        if (state === "refund" || state === "pending") {
            const value = points[points.length - 1] ?? 0;
            points = Array(9).fill(value);
        }
        pointsByBlock.set(block, points);
    });

    if (typeof window.Chart !== "function") {
        chartBlocks.forEach((block) => window.CappersSkeleton?.ready(block));
        return;
    }

    chartBlocks.forEach((block) => {
        const canvas = block.querySelector("canvas");
        if (!canvas) {
            window.CappersSkeleton?.ready(block);
            return;
        }

        const state = block.dataset.bankState || "pending";
        const points = pointsByBlock.get(block) || Array(9).fill(0);
        const color = colorFor(state);

        new window.Chart(canvas, {
            type: "line",
            data: {
                labels: points.map((_, index) => String(index + 1)),
                datasets: [
                    {
                        data: points,
                        borderColor: color,
                        borderWidth: 2.4,
                        pointRadius: 0,
                        pointHoverRadius: 0,
                        tension: 0.34,
                        fill: false,
                    },
                ],
            },
            options: {
                responsive: false,
                maintainAspectRatio: false,
                animation: false,
                events: [],
                layout: {
                    padding: 2,
                },
                plugins: {
                    legend: {
                        display: false,
                    },
                    tooltip: {
                        enabled: false,
                    },
                },
                scales: {
                    x: {
                        display: false,
                        grid: {
                            display: false,
                        },
                        border: {
                            display: false,
                        },
                    },
                    y: {
                        display: false,
                        grid: {
                            display: false,
                        },
                        border: {
                            display: false,
                        },
                    },
                },
            },
        });

        window.CappersSkeleton?.ready(block);
    });
})();