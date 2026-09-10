(() => {
    const blockSelector = "[data-prediction-bank-chart]";

    const toneFor = (block) => {
        const state = block?.dataset.bankState || "pending";
        if (state === "win") {
            return {
                line: "#5ea731",
                fill: "rgba(94, 167, 49, 0.18)",
                glow: "rgba(94, 167, 49, 0.72)",
            };
        }
        if (state === "lose") {
            return {
                line: "#fd1a01",
                fill: "rgba(253, 26, 1, 0.15)",
                glow: "rgba(253, 26, 1, 0.70)",
            };
        }
        return {
            line: "#707072",
            fill: "rgba(112, 112, 114, 0)",
            glow: "rgba(112, 112, 114, 0.25)",
        };
    };

    const isBankChart = (chart) => Boolean(chart?.canvas?.closest(blockSelector));

    const applySparklineLook = (chart) => {
        if (!isBankChart(chart)) return;

        const block = chart.canvas.closest(blockSelector);
        const tone = toneFor(block);
        const dataset = chart.data?.datasets?.[0];
        if (!dataset) return;

        dataset.borderColor = tone.line;
        dataset.backgroundColor = tone.fill;
        dataset.borderWidth = 2.8;
        dataset.borderCapStyle = "round";
        dataset.borderJoinStyle = "round";
        dataset.pointRadius = 0;
        dataset.pointHoverRadius = 0;
        dataset.pointHitRadius = 0;
        dataset.tension = 0.42;
        dataset.fill = block.dataset.bankState === "win" || block.dataset.bankState === "lose" ? "start" : false;

        chart.options.animation = false;
        chart.options.events = [];
        chart.options.layout = {
            padding: {
                top: 5,
                right: 4,
                bottom: 3,
                left: 4,
            },
        };

        if (chart.options.scales?.y) {
            chart.options.scales.y.grace = "18%";
        }
    };

    const glowPlugin = {
        id: "cappersBankSparklineGlow",
        beforeInit(chart) {
            applySparklineLook(chart);
        },
        beforeDatasetDraw(chart) {
            if (!isBankChart(chart)) return;
            const tone = toneFor(chart.canvas.closest(blockSelector));
            chart.ctx.save();
            chart.ctx.shadowColor = tone.glow;
            chart.ctx.shadowBlur = 9;
            chart.ctx.shadowOffsetX = 0;
            chart.ctx.shadowOffsetY = 1;
        },
        afterDatasetDraw(chart) {
            if (!isBankChart(chart)) return;
            chart.ctx.restore();
        },
    };

    const enhanceExisting = () => {
        document.querySelectorAll(`${blockSelector} canvas`).forEach((canvas) => {
            const chart = window.Chart?.getChart?.(canvas);
            if (!chart) return;
            applySparklineLook(chart);
            chart.update("none");
        });
    };

    const register = () => {
        if (typeof window.Chart !== "function") return false;
        window.Chart.register(glowPlugin);
        enhanceExisting();
        return true;
    };

    if (!register()) {
        window.addEventListener("load", register, { once: true });
    }
})();
