(() => {
    const script = document.currentScript || document.querySelector('script[data-state-url][data-user-id]');
    if (!script) return;
    const seed = document.getElementById('coupon-draft-data');
    const editor = document.querySelector('[data-shared-coupon-page]');
    if (!seed && !editor) return;
    const signalKey = `cappers:coupon-draft-changed:${script.dataset.userId}`;
    let state = null;
    let epoch = 0;
    try { state = JSON.parse(seed?.textContent || 'null'); } catch (_error) { /* Read the server below. */ }
    // Migrate old browser snapshots. A published/cleared server draft must stay empty.
    try {
        const csrf = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/)?.[1];
        [script.dataset.userId, csrf].filter(Boolean).forEach((key) => localStorage.removeItem(`cappers:coupon-draft:${key}`));
    } catch (_error) { /* Browser storage is optional. */ }
    const signal = () => {
        try { localStorage.setItem(signalKey, `${Date.now()}:${Math.random()}`); } catch (_error) { /* Focus refresh is the fallback. */ }
    };
    const emit = (payload) => window.dispatchEvent(new CustomEvent('coupon:draft-changed', { detail: payload }));
    const accept = (draft, { notify = false, broadcast = true } = {}) => {
        ++epoch;
        state = draft;
        if (notify) emit({ draft });
        if (broadcast) signal();
    };
    const refresh = async () => {
        const current = ++epoch;
        const url = new URL(script.dataset.stateUrl, window.location.origin);
        if (editor) url.searchParams.set('editor', '1');
        try {
            const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } });
            if (!response.ok) return;
            const payload = await response.json();
            if (current !== epoch || !payload.ok) return;
            state = payload.draft;
            emit(payload);
        } catch (_error) { /* Failed reads never replace the last confirmed draft. */ }
    };
    window.CappersCouponDraft = {
        get: () => state,
        accept,
        refresh,
        changed: () => { ++epoch; signal(); return refresh(); },
    };
    window.addEventListener('storage', (event) => { if (event.key === signalKey) refresh(); });
    window.addEventListener('pageshow', refresh);
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
    signal();
})();
