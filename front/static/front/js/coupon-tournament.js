(() => {
    "use strict";

    // The tournament chosen in the coupon: hides sports and matches it does not accept, locks odds
    // below its minimum and marks coupon positions that break its rules. Shared by the coupon panel
    // and the rich prediction editor.
    const select = document.querySelector("[data-coupon-tournament]");
    const dataNode = document.getElementById("coupon-tournament-rules");
    const rules = new Map();
    try {
        JSON.parse(dataNode?.textContent || "[]").forEach((rule) => rules.set(String(rule.id), rule));
    } catch (_error) {
        rules.clear();
    }
    const FADE_MS = 240;

    const current = () => (select ? rules.get(select.value) || null : null);

    const toNumber = (value) => {
        const parsed = Number.parseFloat(String(value ?? "").replace(",", "."));
        return Number.isFinite(parsed) ? parsed : null;
    };
    const formatOdd = (value) => Number(value).toFixed(2);

    const sportAllowed = (rule, sport) => !rule || !rule.sports.length || !sport || rule.sports.includes(sport);
    const matchUsed = (rule, matchId) => Boolean(rule && rule.used_match_ids.map(String).includes(String(matchId)));
    // Matches starting after the tournament ends cannot enter it.
    const startsInTime = (rule, startsAt) => {
        if (!rule || !rule.ends_at || !startsAt) return true;
        const starts = Date.parse(startsAt);
        return Number.isNaN(starts) || starts <= Date.parse(rule.ends_at);
    };

    // Why a coupon position cannot go into the tournament; empty when it can.
    const problems = ({ sport, coefficient, matchId, startsAt }, rule = current()) => {
        if (!rule) return [];
        const found = [];
        if (!sportAllowed(rule, sport)) found.push(`Турнир принимает только: ${rule.sport_names.join(", ")}`);
        const odd = toNumber(coefficient);
        if (rule.min_coefficient > 0 && odd !== null && odd < rule.min_coefficient) {
            found.push(`Кф ниже минимального для турнира — ${formatOdd(rule.min_coefficient)}`);
        }
        if (matchUsed(rule, matchId)) found.push("На этот матч уже есть ваш прогноз в турнире");
        if (!startsInTime(rule, startsAt)) found.push("Матч начинается после окончания турнира");
        return found;
    };

    // Hidden nodes fade out and leave the layout; shown ones come back the same way.
    const setVisible = (node, visible) => {
        const hidden = node.hasAttribute("data-tournament-hidden");
        if (visible === !hidden) return;
        window.clearTimeout(node._tournamentFade);
        if (visible) {
            node.removeAttribute("data-tournament-hidden");
            node.hidden = false;
            requestAnimationFrame(() => node.classList.remove("is-tournament-leaving"));
            return;
        }
        node.setAttribute("data-tournament-hidden", "");
        node.classList.add("is-tournament-leaving");
        node._tournamentFade = window.setTimeout(() => { node.hidden = true; }, FADE_MS);
    };

    const LOCK_ICON = '<svg viewBox="0 0 24 24" fill="none"><path d="M7 10V8a5 5 0 0 1 10 0v2M6 10h12a2 2 0 0 1 2 2v7H4v-7a2 2 0 0 1 2-2Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';

    const lockOdd = (button, reason) => {
        const locked = Boolean(reason);
        button.classList.toggle("is-tournament-locked", locked);
        button.setAttribute("aria-disabled", String(locked));
        let icon = button.querySelector("[data-tournament-lock]");
        if (locked && !icon) {
            icon = document.createElement("i");
            icon.className = "match-odd-lock";
            icon.setAttribute("aria-hidden", "true");
            icon.setAttribute("data-tournament-lock", "");
            icon.innerHTML = LOCK_ICON;
            button.prepend(icon);
        }
        if (!locked) icon?.remove();
        if (locked) button.title = reason;
        else if (icon) button.removeAttribute("title");
    };

    // Matches the tournament does not accept stay in the list, dimmed, with their odds locked;
    // odds below the tournament minimum are locked too. The coupon refuses such positions anyway.
    const applyToPage = (scope = document) => {
        const rule = current();
        const cards = [...scope.querySelectorAll("[data-match-sport]")];
        if (scope instanceof Element && scope.matches("[data-match-sport]")) cards.push(scope);
        cards.forEach((node) => {
            const matchId = node.dataset.matchId || node.dataset.matchShellId;
            const reason = !rule ? ""
                : !sportAllowed(rule, node.dataset.matchSport) ? `Турнир принимает только: ${rule.sport_names.join(", ")}`
                : matchUsed(rule, matchId) ? "На этот матч уже есть ваш прогноз в турнире"
                : !startsInTime(rule, node.dataset.matchStartsAt) ? "Матч начинается после окончания турнира"
                : "";
            node.classList.toggle("is-tournament-unavailable", Boolean(reason));
            node.dataset.tournamentReason = reason;
        });
        scope.querySelectorAll("[data-bet-option][data-coefficient]").forEach((button) => {
            const matchReason = button.closest("[data-match-sport]")?.dataset.tournamentReason || "";
            const odd = toNumber(button.dataset.coefficient);
            const low = Boolean(rule && rule.min_coefficient > 0 && odd !== null && odd < rule.min_coefficient);
            lockOdd(button, matchReason || (low ? `Минимальный кф турнира — ${formatOdd(rule.min_coefficient)}` : ""));
        });
    };

    // Coupon panel items and rich editor items carry their match, sport and coefficient.
    const markItems = () => {
        const rule = current();
        let invalid = 0;
        document.querySelectorAll("[data-coupon-match-id]").forEach((node) => {
            const found = problems({
                sport: node.dataset.sport || node.dataset.matchSport,
                coefficient: node.dataset.coefficient,
                matchId: node.dataset.couponMatchId,
                startsAt: node.dataset.startsAt,
            }, rule);
            node.classList.toggle("is-tournament-invalid", found.length > 0);
            let note = node.querySelector("[data-tournament-item-warning]");
            if (found.length && !note) {
                note = document.createElement("small");
                note.className = "coupon-item-tournament-warning";
                note.setAttribute("data-tournament-item-warning", "");
                (node.querySelector(".coupon-item-body, .rich-prediction-coupon-copy") || node).append(note);
            }
            if (note) {
                note.textContent = found.join(" · ");
                note.hidden = !found.length;
            }
            invalid += found.length ? 1 : 0;
        });
        return invalid;
    };

    const describe = (rule) => {
        if (!rule) return "";
        const parts = [rule.sports.length ? `Спорт: ${rule.sport_names.join(", ")}` : "Любой спорт"];
        if (rule.min_coefficient > 1) parts.push(`кф от ${formatOdd(rule.min_coefficient)}`);
        if (rule.min_confidence > 0) parts.push(`уверенность от ${rule.min_confidence}%`);
        if (rule.coupon_type === "single") parts.push("только одиночные");
        if (rule.coupon_type === "express") parts.push("только экспрессы");
        parts.push(rule.requires_text ? "название и описание обязательны" : "публикация прямо из купона");
        return parts.join(" · ");
    };

    const apply = () => {
        const rule = current();
        document.documentElement.classList.toggle("has-coupon-tournament", Boolean(rule));
        const rulesNode = document.querySelector("[data-coupon-tournament-rules]");
        if (rulesNode) {
            rulesNode.textContent = describe(rule);
            rulesNode.hidden = !rule;
        }
        applyToPage();
        // Tournament predictions are always free, so the editor drops its access choice.
        const accessCard = document.querySelector("[data-rich-access-card]");
        if (accessCard) {
            setVisible(accessCard, !rule);
            const free = accessCard.querySelector('[name="is_paid"][value=""]');
            if (rule && free && !free.checked) {
                free.checked = true;
                free.dispatchEvent(new Event("change", { bubbles: true }));
            }
        }
        const invalid = markItems();
        const editorWarning = document.querySelector("[data-tournament-editor-warning]");
        if (editorWarning) editorWarning.hidden = !invalid;
        window.dispatchEvent(new CustomEvent("coupon:tournament-changed", { detail: { rule, invalid } }));
    };

    window.CappersCouponTournament = { current, problems, markItems, apply, select };
    if (!select) return;

    select.addEventListener("change", apply);

    // Odds below the tournament minimum stay visible but cannot be picked.
    document.addEventListener("click", (event) => {
        const button = event.target instanceof Element ? event.target.closest(".is-tournament-locked[data-bet-option]") : null;
        if (!button) return;
        event.preventDefault();
        event.stopImmediatePropagation();
    }, true);
    // The editor redraws its positions when the shared draft changes.
    window.addEventListener("coupon:draft-changed", () => window.setTimeout(apply, 0));
    document.addEventListener("matches:appended", (event) => {
        const nodes = event.detail?.nodes || [];
        if (nodes.length) nodes.forEach((node) => applyToPage(node));
        else applyToPage();
    });

    // A link from a tournament page picks it; otherwise the choice comes from the saved coupon draft.
    const fromUrl = new URLSearchParams(window.location.search).get("tournament");
    if (rules.has(fromUrl || "") && select.value !== fromUrl) select.value = fromUrl;
    apply();
})();
