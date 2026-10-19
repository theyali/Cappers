(() => {
    const root = document.querySelector('[data-copy-discovery]');
    if (!root) return;
    const form = root.querySelector('[data-copy-discovery-form]');
    const results = root.querySelector('[data-copy-discovery-results]');
    const status = root.querySelector('[data-copy-discovery-status]');
    const query = form.elements.q;
    const retry = root.querySelector('[data-copy-discovery-retry]');
    const sortButtons = form.querySelectorAll('[data-copy-sort]');
    const syncSort = () => sortButtons.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.copySort === form.elements.sort.value)));
    let request = null, version = 0, timer = null, composing = false, loaded = false;
    let retryPage = 1, retryAppend = false, pageSize = 6;
    const load = async (page = 1, append = false) => {
        clearTimeout(timer);
        if (request) request.abort();
        const controller = new AbortController(); request = controller;
        const current = ++version;
        if (!append) pageSize = window.matchMedia?.('(max-width: 599px)')?.matches ? 4 : 6;
        const body = new URLSearchParams(new FormData(form)); body.set('page', page); body.set('page_size', pageSize);
        const more = results.querySelector('[data-copy-discovery-more]');
        const moreLabel = more?.textContent;
        if (more) {
            more.disabled = true;
            if (append) more.textContent = 'Загружаем…';
        }
        if (!append) status.textContent = 'Ищем капперов…';
        retry.hidden = true;
        if (!append) {
            results.setAttribute('aria-busy', 'true');
            window.CappersSkeleton?.loading(results);
        }
        const timeout = setTimeout(() => controller.abort('timeout'), 15000);
        try {
            const response = await fetch(root.dataset.url, { method: 'POST', credentials: 'same-origin', signal: controller.signal, body, headers: { Accept: 'application/json' } });
            if (!response.ok) throw new Error('search');
            const payload = await response.json();
            if (current !== version) return;
            if (typeof payload.html !== 'string') throw new Error('payload');
            if (append) {
                const fragment = document.createElement('template'); fragment.innerHTML = payload.html;
                const rows = fragment.content.querySelector('[data-copy-discovery-rows]');
                const counter = fragment.content.querySelector('[data-copy-discovery-count]');
                const pagination = fragment.content.querySelector('[data-copy-discovery-pagination]');
                if (!rows || !counter || !pagination) throw new Error('rows');
                const added = [...rows.children];
                if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
                    added.forEach((row) => {
                        row.classList.add('is-appended');
                        row.addEventListener('animationend', () => row.classList.remove('is-appended'), { once: true });
                    });
                }
                results.querySelector('[data-copy-discovery-rows]').append(...rows.childNodes);
                results.querySelector('[data-copy-discovery-count]').replaceWith(counter);
                results.querySelector('[data-copy-discovery-pagination]').replaceWith(pagination);
            } else results.innerHTML = payload.html;
            loaded = true;
            status.textContent = '';
        } catch (error) {
            if (current === version && (!controller.signal.aborted || controller.signal.reason === 'timeout')) {
                status.textContent = 'Не удалось загрузить капперов. Попробуйте ещё раз.';
                retryPage = page;
                retryAppend = append;
                retry.hidden = false;
            }
        } finally {
            clearTimeout(timeout);
            if (current === version) {
                request = null;
                if (!append) {
                    results.setAttribute('aria-busy', 'false');
                    window.CappersSkeleton?.ready(results);
                }
                if (more?.isConnected) {
                    more.disabled = false;
                    more.textContent = moreLabel;
                }
            }
        }
    };
    const schedule = () => {
        clearTimeout(timer);
        if (request) { request.abort(); request = null; version++; }
        timer = setTimeout(() => load(), query.value ? 300 : 0);
    };
    document.addEventListener('click', (event) => { if (event.target.closest('[data-copy-discovery-open]') && !loaded && !request) load(); });
    form.addEventListener('submit', (event) => { event.preventDefault(); load(); });
    query.addEventListener('compositionstart', () => { composing = true; });
    query.addEventListener('compositionend', () => { composing = false; schedule(); });
    query.addEventListener('input', (event) => { if (!composing && !event.isComposing) schedule(); });
    form.addEventListener('change', (event) => { if (event.target !== query) { syncSort(); load(); } });
    sortButtons.forEach((button) => button.addEventListener('click', () => {
        form.elements.sort.value = button.dataset.copySort;
        syncSort();
        load();
    }));
    retry.addEventListener('click', () => load(retryPage, retryAppend));
    form.querySelector('[data-copy-query-clear]').addEventListener('click', () => { query.value = ''; query.focus(); load(); });
    results.addEventListener('click', (event) => {
        const more = event.target.closest('[data-copy-discovery-more]');
        if (more && !more.disabled) load(Number(more.dataset.nextPage), true);
    });
})();
