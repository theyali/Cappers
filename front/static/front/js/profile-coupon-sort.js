(() => {
    const feeds = document.querySelectorAll('[data-profile-coupon-feed]');
    if (!feeds.length) return;

    const loadJQuery = () => {
        if (window.jQuery) return Promise.resolve(window.jQuery);
        return new Promise((resolve, reject) => {
            let script = document.querySelector('script[data-profile-jquery]');
            if (!script) {
                script = document.createElement('script');
                script.src = 'https://code.jquery.com/jquery-3.7.1.min.js';
                script.dataset.profileJquery = 'true';
                document.head.appendChild(script);
            }
            script.addEventListener('load', () => window.jQuery ? resolve(window.jQuery) : reject(), { once: true });
            script.addEventListener('error', reject, { once: true });
        });
    };

    loadJQuery().then(($) => feeds.forEach((feed) => {
        const panel = feed.closest('#profile-tab-predictions') || feed;
        const desktop = feed.querySelector('[data-coupon-feed-desktop]');
        const mobile = feed.querySelector('[data-coupon-feed-mobile]');
        const more = feed.querySelector('[data-coupon-feed-more]');
        const sentinel = feed.querySelector('[data-coupon-feed-sentinel]');
        const status = feed.querySelector('[data-coupon-feed-status]');
        const empty = feed.querySelector('[data-coupon-feed-empty]');
        const sortButtons = panel.querySelectorAll('[data-profile-coupon-sort]');
        const filterButtons = feed.querySelectorAll('[data-profile-coupon-filter]');
        const purchaseButtons = feed.closest('.profile-purchases-page')?.querySelectorAll('[data-profile-purchase-status]') || [];
        let purchaseStatus = feed.dataset.purchaseStatus || 'paid';
        let sort = feed.dataset.sort || 'date';
        let direction = feed.dataset.direction || 'desc';
        let filter = feed.dataset.filter || 'all';
        let request = null;
        let version = 0;
        let loading = false;
        let autoPaused = false;
        let retryReplace = false;

        const updateControls = () => {
            purchaseButtons.forEach((button) => {
                const active = button.dataset.profilePurchaseStatus === purchaseStatus;
                button.classList.toggle('is-active', active);
                if (active) button.setAttribute('aria-current', 'page');
                else button.removeAttribute('aria-current');
            });
            sortButtons.forEach((button) => {
                const active = button.dataset.profileCouponSort === sort;
                button.classList.toggle('is-active', active);
                button.setAttribute('aria-pressed', String(active));
                const arrow = button.querySelector('[data-sort-arrow]');
                if (arrow) arrow.textContent = active ? (direction === 'asc' ? '↑' : '↓') : '';
            });
            filterButtons.forEach((button) => {
                const active = button.dataset.profileCouponFilter === filter;
                button.classList.toggle('is-active', active);
                button.setAttribute('aria-pressed', String(active));
            });
        };
        const persist = (push = false) => {
            const url = new URL(window.location.href);
            if (purchaseButtons.length) {
                url.searchParams.set('status', purchaseStatus);
                url.searchParams.delete('page');
                url.searchParams.delete('offset');
            }
            [['coupon_sort', sort, 'date'], ['coupon_direction', direction, 'desc'], ['coupon_filter', filter, 'all']].forEach(([key, value, fallback]) => {
                if (value === fallback) url.searchParams.delete(key);
                else url.searchParams.set(key, value);
            });
            window.history[push ? 'pushState' : 'replaceState'](null, '', url);
        };
        const visible = () => {
            const rect = sentinel.getBoundingClientRect();
            return sentinel.getClientRects().length > 0 && rect.top < window.innerHeight + 160 && rect.bottom > 0;
        };
        const loadMoreIfVisible = () => {
            if (!loading && !autoPaused && !more.hidden && visible()) load(true);
        };
        const load = (append = false) => {
            if (append && loading) return;
            if (append && retryReplace) append = false;
            const current = ++version;
            if (request) request.abort();
            loading = true;
            autoPaused = false;
            feed.setAttribute('aria-busy', 'true');
            more.disabled = true;
            status.textContent = 'Загружаем прогнозы…';
            request = $.ajax({
                url: feed.dataset.url,
                method: 'GET',
                dataType: 'json',
                timeout: 15000,
                data: { sort, direction, state: filter, offset: append ? Number(more.dataset.nextOffset || 0) : 0,
                    ...(purchaseButtons.length ? { status: purchaseStatus } : {}) },
            }).done((payload) => {
                if (current !== version) return;
                if (!payload.ok || typeof payload.desktop_html !== 'string' || typeof payload.html !== 'string') {
                    failed();
                    return;
                }
                if (append) {
                    $(desktop).append(payload.desktop_html);
                    $(mobile).append(payload.html);
                } else {
                    $(desktop).html(payload.desktop_html);
                    $(mobile).html(payload.html);
                }
                more.dataset.nextOffset = String(payload.next_offset);
                more.hidden = !payload.has_more;
                more.textContent = 'Показать ещё';
                empty.hidden = payload.total !== 0;
                panel.querySelectorAll('.profile-coupon-count').forEach((count) => { count.textContent = payload.total; });
                if (payload.title) feed.querySelector('[data-coupon-feed-title]').textContent = payload.title;
                feed.dataset.purchaseStatus = purchaseStatus;
                retryReplace = false;
                status.textContent = `Показано ${payload.next_offset} из ${payload.total}`;
            }).fail((_xhr, reason) => {
                if (current === version && reason !== 'abort') failed();
            }).always(() => {
                if (current !== version) return;
                request = null;
                loading = false;
                more.disabled = false;
                feed.setAttribute('aria-busy', 'false');
                window.requestAnimationFrame(loadMoreIfVisible);
            });
            function failed() {
                autoPaused = true;
                retryReplace = !append;
                more.hidden = false;
                more.textContent = 'Повторить загрузку';
                status.textContent = append
                    ? 'Не удалось загрузить ещё прогнозы. Нажмите «Повторить загрузку».'
                    : 'Не удалось обновить список. Показаны прежние прогнозы. Нажмите «Повторить загрузку».';
            }
        };
        sortButtons.forEach((button) => button.addEventListener('click', () => {
            const key = button.dataset.profileCouponSort;
            direction = sort === key && direction === 'desc' ? 'asc' : 'desc';
            sort = key;
            updateControls(); persist(); load();
        }));
        filterButtons.forEach((button) => button.addEventListener('click', () => {
            filter = button.dataset.profileCouponFilter;
            updateControls(); persist(); load();
        }));
        $(purchaseButtons).on('click', (event) => {
            if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || (event.button && event.button !== 0)) return;
            event.preventDefault();
            const next = event.currentTarget.dataset.profilePurchaseStatus;
            if (next === purchaseStatus) return;
            purchaseStatus = next;
            filter = 'all';
            updateControls(); persist(true); load();
        });
        more.addEventListener('click', () => load(true));
        if ('IntersectionObserver' in window) {
            new IntersectionObserver(loadMoreIfVisible, { rootMargin: '160px' }).observe(sentinel);
        }
        // Also handles a short first page, panel activation and a column's own scroll.
        document.addEventListener('scroll', loadMoreIfVisible, { passive: true, capture: true });
        window.addEventListener('resize', loadMoreIfVisible, { passive: true });
        window.addEventListener('popstate', () => {
            const params = new URL(window.location.href).searchParams;
            sort = params.get('coupon_sort') || 'date';
            direction = params.get('coupon_direction') || 'desc';
            filter = params.get('coupon_filter') || 'all';
            purchaseStatus = params.get('status') === 'refunded' ? 'refunded' : 'paid';
            updateControls(); load();
        });
        updateControls();
    })).catch(() => {
        feeds.forEach((feed) => {
            feed.querySelector('[data-coupon-feed-status]').textContent = 'Не удалось загрузить управление списком. Обновите страницу.';
        });
    });
})();
