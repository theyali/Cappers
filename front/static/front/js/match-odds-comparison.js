(() => {
    const panel = document.querySelector('[data-match-comparison]');
    if (!panel) return;
    const tab = document.querySelector('[data-comparison-tab]');
    let sidebar = document.querySelector('[data-comparison-sidebar]');
    const findAll = selector => [panel, sidebar].filter(Boolean).flatMap(root => Array.from(root.querySelectorAll(selector)));
    let archived = panel.dataset.comparisonArchived === 'true';
    const retry = panel.querySelector('[data-comparison-retry]');
    let active = panel.querySelector('[data-comparison-filter]')?.dataset.comparisonFilter || '';
    const limits = new Map();
    let timer, expiryTimer, controller;
    let version = '', failures = 0, sequence = 0;
    let stopped = false;

    const syncControls = () => {
        const buttons = Array.from(panel.querySelectorAll('[data-comparison-filter]'));
        if (!buttons.some(button => button.dataset.comparisonFilter === active)) {
            active = buttons[0]?.dataset.comparisonFilter || '';
        }
        buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.comparisonFilter === active)));
        panel.querySelectorAll('[data-comparison-section]').forEach(section => {
            const key = section.dataset.comparisonSection;
            section.hidden = key !== active;
            const rows = Array.from(section.querySelectorAll('[data-comparison-row]'));
            const limit = limits.get(key) || 20;
            rows.forEach((row, index) => { row.hidden = index >= limit; });
            const more = section.querySelector('[data-comparison-more]');
            if (more) more.hidden = rows.length <= limit;
        });
        sidebar?.querySelectorAll('[data-comparison-sidebar-section]').forEach(section => {
            const key = section.dataset.comparisonSidebarSection;
            section.hidden = key !== active;
        });
        findAll('[data-comparison-updated]').forEach(time => {
            const date = new Date(time.dateTime);
            if (!Number.isNaN(date.getTime())) {
                time.textContent = new Intl.DateTimeFormat('ru-RU', {
                    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
                }).format(date);
                time.title = date.toLocaleString('ru-RU');
            }
        });
    };

    const removeBest = message => {
        if (archived) return;
        panel.querySelectorAll('.is-best').forEach(cell => {
            cell.classList.remove('is-best');
            cell.removeAttribute('title');
        });
        panel.querySelectorAll('[data-comparison-best-marker]').forEach(marker => marker.remove());
        findAll('[data-comparison-best-summary]').forEach(cell => {
            cell.replaceChildren();
            const note = document.createElement('p');
            note.className = 'match-comparison-empty';
            note.textContent = 'Актуальность линии не подтверждена. Лучшие предложения появятся после обновления.';
            cell.append(note);
        });
        const status = panel.querySelector('[data-comparison-status]');
        if (status) status.textContent = message;
        version = ''; // A successful response must restore even an unchanged snapshot.
    };

    const setExpiry = value => {
        window.clearTimeout(expiryTimer);
        const remaining = Date.parse(value) - Date.now();
        if (!Number.isFinite(remaining)) return;
        if (remaining <= 0) {
            removeBest('Линия устарела · лучшие коэффициенты не отмечены');
        } else {
            expiryTimer = window.setTimeout(() => removeBest('Линия устарела · лучшие коэффициенты не отмечены'), Math.min(remaining + 50, 2147483647));
        }
    };

    const schedule = delay => {
        window.clearTimeout(timer);
        if (!stopped && !document.hidden && navigator.onLine) timer = window.setTimeout(refresh, delay);
    };

    async function refresh() {
        window.clearTimeout(timer);
        if (stopped || document.hidden || !navigator.onLine) return;
        controller?.abort();
        const request = new AbortController();
        controller = request;
        const current = ++sequence;
        let timedOut = false;
        const timeout = window.setTimeout(() => { timedOut = true; request.abort(); }, 10000);
        panel.setAttribute('aria-busy', 'true');
        retry.disabled = true;
        try {
            const response = await fetch(panel.dataset.url, {
                headers: { Accept: 'application/json' }, cache: 'no-store', signal: request.signal,
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (!data.ok || typeof data.html !== 'string') throw new Error('Invalid comparison response');
            if (current !== sequence || request.signal.aborted) return;
            failures = 0;
            retry.hidden = true;
            panel.hidden = !data.visible;
            if (tab) tab.hidden = !data.visible;
            archived = Boolean(data.archived);
            if (version !== data.version) {
                const focusedFilter = document.activeElement?.dataset.comparisonFilter;
                const focusedScroller = document.activeElement?.classList.contains('match-comparison-scroll');
                const focusedSidebar = sidebar?.contains(document.activeElement);
                const focusedBookmaker = focusedSidebar ? document.activeElement?.closest('[data-comparison-offer]')?.dataset.comparisonBookmaker : null;
                const scroll = panel.querySelector(`[data-comparison-section="${active}"] .match-comparison-scroll`)?.scrollLeft || 0;
                const parsed = new DOMParser().parseFromString(data.html, 'text/html');
                const content = parsed.querySelector('[data-comparison-content]');
                if (!content) throw new Error('Missing comparison content');
                const sidebarContent = new DOMParser().parseFromString(data.sidebar_html || '', 'text/html').querySelector('[data-comparison-sidebar]');
                if (sidebar && !sidebarContent) throw new Error('Missing comparison sidebar');
                panel.querySelector('[data-comparison-content]').replaceWith(document.importNode(content, true));
                if (sidebar && sidebarContent) {
                    const nextSidebar = document.importNode(sidebarContent, true);
                    sidebar.replaceWith(nextSidebar);
                    sidebar = nextSidebar;
                }
                syncControls();
                checkLogos();
                const scroller = panel.querySelector(`[data-comparison-section="${active}"] .match-comparison-scroll`);
                if (scroller) scroller.scrollLeft = scroll;
                if (focusedFilter) panel.querySelector(`[data-comparison-filter="${active}"]`)?.focus({ preventScroll: true });
                else if (focusedScroller) scroller?.focus({ preventScroll: true });
                else if (focusedSidebar) {
                    const nextOffer = Array.from(sidebar.querySelectorAll('[data-comparison-offer]')).find(offer =>
                        offer.dataset.comparisonOffer === active && offer.dataset.comparisonBookmaker === focusedBookmaker);
                    (nextOffer || sidebar.querySelector('.match-comparison-all'))?.focus({ preventScroll: true });
                }
                version = data.version;
            }
            panel.dataset.expiresAt = data.expires_at || '';
            setExpiry(panel.dataset.expiresAt);
            // An archive needs no live polling, but a missing prematch slice may
            // still be loading in Celery. Wait for that first REST result.
            const awaitingArchive = Boolean(data.archive_needs_refresh);
            stopped = !data.supported || (archived && !awaitingArchive && !data.refresh_queued && data.status !== 'missing');
            schedule(awaitingArchive || data.refresh_queued || data.status === 'missing' ? 5000 : 60000);
        } catch (error) {
            if (current !== sequence || (error.name === 'AbortError' && !timedOut)) return;
            failures += 1;
            removeBest(navigator.onLine ? 'Не удалось обновить · показана сохранённая линия' : 'Нет соединения · показана сохранённая линия');
            retry.hidden = false;
            if (failures < 4) schedule(Math.min(5000 * 2 ** (failures - 1), 60000));
        } finally {
            window.clearTimeout(timeout);
            if (current === sequence) {
                panel.removeAttribute('aria-busy');
                retry.disabled = false;
            }
        }
    }

    const checkLogos = () => findAll('[data-comparison-logo]').forEach(img => {
        if (img.complete && !img.naturalWidth) img.parentElement.classList.remove('has-image');
    });
    document.addEventListener('error', event => {
        if (event.target.matches?.('[data-comparison-logo]')) event.target.parentElement.classList.remove('has-image');
    }, true);
    panel.addEventListener('click', event => {
        const filter = event.target.closest('[data-comparison-filter]');
        if (filter) { active = filter.dataset.comparisonFilter; syncControls(); }
        const more = event.target.closest('[data-comparison-more]');
        if (more) {
            const key = more.closest('[data-comparison-section]').dataset.comparisonSection;
            limits.set(key, (limits.get(key) || 20) + 20);
            syncControls();
            if (more.hidden) more.closest('[data-comparison-section]').querySelector('.match-comparison-scroll')?.focus({ preventScroll: true });
        }
    });
    document.addEventListener('click', event => {
        const offer = event.target.closest('[data-comparison-offer]');
        if (!offer || !sidebar?.contains(offer)) return;
        const key = offer.dataset.comparisonOffer;
        const index = Number(offer.dataset.comparisonRowIndex);
        active = key;
        limits.set(key, Math.max(limits.get(key) || 20, Math.ceil((index + 1) / 20) * 20));
        syncControls();
        const section = panel.querySelector(`[data-comparison-section="${key}"]`);
        const row = section?.querySelectorAll('[data-comparison-row]')[index];
        if (!row) return;
        event.preventDefault();
        row.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' });
        section.querySelector('.match-comparison-scroll')?.focus({ preventScroll: true });
    });
    retry.addEventListener('click', () => { failures = 0; refresh(); });
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) { window.clearTimeout(timer); controller?.abort(); }
        else { setExpiry(panel.dataset.expiresAt); refresh(); }
    });
    window.addEventListener('offline', () => {
        window.clearTimeout(timer); controller?.abort();
        removeBest('Нет соединения · показана сохранённая линия'); retry.hidden = false;
    });
    window.addEventListener('online', () => { failures = 0; refresh(); });
    window.addEventListener('pagehide', () => {
        window.clearTimeout(timer); window.clearTimeout(expiryTimer); controller?.abort();
    });
    window.addEventListener('pageshow', event => { if (event.persisted) { setExpiry(panel.dataset.expiresAt); refresh(); } });
    syncControls();
    checkLogos();
    setExpiry(panel.dataset.expiresAt);
    refresh();
})();
