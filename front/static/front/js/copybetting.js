(() => {
    const panel = document.querySelector('[data-copybetting-panel]');
    if (!panel) return;
    const content = panel.querySelector('[data-copy-content]');
    const feedback = panel.querySelector('[data-copy-feedback]');
    let pending = null;
    let version = 0;
    let debounce = null;
    let composing = false;
    let currentHref = window.location.href;
    let currentMenu = null;
    let currentTrigger = null;
    let menuHome = null;
    const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const closeMenu = (restoreFocus = false, immediate = false) => {
        if (!currentMenu) return;
        const menu = currentMenu, trigger = currentTrigger, home = menuHome;
        currentMenu = null; currentTrigger = null; menuHome = null;
        menu.classList.remove('is-open');
        menu.inert = true;
        trigger?.setAttribute('aria-expanded', 'false');
        if (restoreFocus && trigger?.isConnected) trigger.focus({ preventScroll: true });
        const finish = () => { menu.hidden = true; if (home?.isConnected) home.appendChild(menu); else menu.remove(); };
        if (immediate || reducedMotion()) finish();
        else window.setTimeout(finish, 180);
    };
    const openMenu = (trigger) => {
        if (trigger === currentTrigger) { closeMenu(true); return; }
        closeMenu(false, true);
        const menu = trigger.parentElement.querySelector('[data-copy-menu]');
        if (!menu) return;
        currentMenu = menu; currentTrigger = trigger; menuHome = menu.parentElement;
        document.body.appendChild(menu);
        menu.hidden = false;
        menu.inert = false;
        const rect = trigger.getBoundingClientRect();
        const gap = 12;
        const available = Math.max(120, window.innerHeight - 2 * gap);
        menu.style.maxHeight = `${available}px`;
        const size = menu.getBoundingClientRect();
        menu.style.left = `${Math.max(gap, Math.min(rect.right - size.width, window.innerWidth - size.width - gap))}px`;
        menu.style.top = `${Math.max(gap, Math.min(rect.bottom + 6, window.innerHeight - size.height - gap))}px`;
        trigger.setAttribute('aria-expanded', 'true');
        requestAnimationFrame(() => { if (currentMenu === menu) menu.classList.add('is-open'); });
        menu.querySelector('a, button:not(:disabled)')?.focus({ preventScroll: true });
    };
    const load = async (href, append = false, push = true) => {
        window.clearTimeout(debounce);
        if (pending) pending.abort();
        const controller = new AbortController(); pending = controller;
        const requestVersion = ++version;
        const url = new URL(href, window.location.origin);
        if (url.origin !== window.location.origin) return;
        const requestUrl = new URL(panel.dataset.url, window.location.origin);
        requestUrl.search = url.search;
        closeMenu(false, true);
        const active = document.activeElement;
        const focusWasInContent = content.contains(active);
        const focusName = focusWasInContent ? active.getAttribute('name') : null;
        const selection = active?.selectionStart;
        const focusTag = active?.tagName;
        const focusValue = active?.value;
        content.setAttribute('aria-busy', 'true');
        window.CappersSkeleton?.loading(content);
        feedback.textContent = 'Загружаем данные…';
        const more = content.querySelector('[data-copy-more]');
        if (more) more.setAttribute('aria-disabled', 'true');
        try {
            const response = await fetch(requestUrl, { credentials: 'same-origin', signal: controller.signal, headers: { Accept: 'application/json' } });
            if (!response.ok) throw new Error('load');
            const payload = await response.json();
            if (requestVersion !== version) return;
            if (typeof payload.html !== 'string') throw new Error('payload');
            if (append) {
                const fragment = document.createElement('template'); fragment.innerHTML = payload.html;
                const rows = fragment.content.querySelector('[data-copy-rows]');
                const pagination = fragment.content.querySelector('[data-copy-pagination]');
                if (!rows || !pagination) throw new Error('rows');
                const target = content.querySelector('[data-copy-rows]');
                target.append(...rows.childNodes);
                content.querySelector('[data-copy-pagination]')?.replaceWith(pagination);
                // Extra pages are transient; URL keeps the initial page of this mobile list.
            } else {
                content.innerHTML = payload.html;
                if (push && panel.dataset.copyRole !== 'reader') window.history.pushState({ copybetting: true }, '', url);
            }
            if (typeof payload.summary_html === 'string') {
                const summary = panel.querySelector('.copybetting-summary');
                if (summary) summary.innerHTML = payload.summary_html;
            }
            currentHref = url.href;
            if (focusName && !append) {
                const candidates = [...content.querySelectorAll(`[name="${focusName}"]`)];
                const target = candidates.find((item) => item.tagName === focusTag && item.type !== 'hidden' && (focusTag !== 'BUTTON' || item.value === focusValue));
                target?.focus({ preventScroll: true });
                if (typeof selection === 'number' && target?.type === 'search') target.setSelectionRange(selection, selection);
            }
            if (!focusName && focusWasInContent && !active.isConnected) {
                const target = append ? content.querySelector('[data-copy-more]') : content.querySelector('.copybetting-tabs a[aria-current]');
                target?.focus({ preventScroll: true });
            }
            feedback.textContent = '';
        } catch (error) {
            if (error.name !== 'AbortError' && requestVersion === version) {
                feedback.textContent = 'Не удалось обновить данные. Прежний список сохранён. Повторите действие.';
            }
        } finally {
            if (requestVersion === version) {
                pending = null;
                content.setAttribute('aria-busy', 'false');
                window.CappersSkeleton?.ready(content);
                if (more?.isConnected) more.removeAttribute('aria-disabled');
            }
        }
    };
    const formUrl = (form, submitter) => {
        const values = new URLSearchParams(new FormData(form));
        if (submitter?.name) values.set(submitter.name, submitter.value);
        return `${form.action}?${values}`;
    };
    document.addEventListener('submit', (event) => {
        const form = event.target.closest('[data-copy-filters]');
        if (!form) return;
        event.preventDefault();
        load(formUrl(form, event.submitter));
    });
    document.addEventListener('change', (event) => {
        if (event.target.matches('[data-copy-filters] select')) load(formUrl(event.target.form));
    });
    const search = (input) => {
        window.clearTimeout(debounce);
        if (pending) {
            pending.abort(); pending = null; version++;
            content.setAttribute('aria-busy', 'false');
            window.CappersSkeleton?.ready(content);
        }
        debounce = window.setTimeout(() => load(formUrl(input.form)), input.value ? 300 : 0);
    };
    document.addEventListener('compositionstart', (event) => { if (event.target.matches('[data-copy-filters] input[type="search"]')) composing = true; });
    document.addEventListener('compositionend', (event) => {
        if (event.target.matches('[data-copy-filters] input[type="search"]')) { composing = false; search(event.target); }
    });
    document.addEventListener('input', (event) => {
        if (event.target.matches('[data-copy-filters] input[type="search"]') && !composing && !event.isComposing) search(event.target);
    });
    document.addEventListener('click', async (event) => {
        const trigger = event.target.closest('[data-copy-menu-trigger]');
        if (trigger) { openMenu(trigger); return; }
        const audienceAction = event.target.closest('[data-copy-audience-action]');
        if (audienceAction && !audienceAction.disabled) {
            if (audienceAction.dataset.copyBlockAction === 'block' && !window.confirm(`Запретить @${audienceAction.dataset.username} копировать ваши прогнозы? Новые ставки перестанут копироваться. Уже принятые ставки будут рассчитаны.`)) return;
            audienceAction.disabled = true;
            try {
                const token = panel.querySelector('[name="csrfmiddlewaretoken"]')?.value || document.querySelector('[name="csrfmiddlewaretoken"]')?.value;
                const response = await fetch(audienceAction.dataset.url, { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': token, Accept: 'application/json' } });
                if (!response.ok) throw new Error('action');
                closeMenu(false, true);
                await load(currentHref, false, false);
            } catch (_) { feedback.textContent = 'Не удалось сохранить изменение. Повторите действие.'; }
            finally { audienceAction.disabled = false; }
            return;
        }
        const showHidden = event.target.closest('[data-copy-show-hidden]');
        if (showHidden) {
            const url = new URL(currentHref, window.location.origin);
            url.searchParams.set('copy_show_hidden', showHidden.dataset.show);
            load(url.href, false, false);
            return;
        }
        const navigation = event.target.closest('[data-copy-nav], [data-copy-more]');
        if (navigation && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && event.button === 0) {
            event.preventDefault();
            if (navigation.getAttribute('aria-disabled') === 'true') return;
            load(navigation.href, navigation.hasAttribute('data-copy-more'));
            return;
        }
        const share = event.target.closest('[data-copy-share]');
        if (share) {
            const url = new URL(panel.dataset.sharePath, window.location.origin).href;
            try {
                if (navigator.share) await navigator.share({ title: 'Мой профиль на КапперХаб', url });
                else { await navigator.clipboard.writeText(url); feedback.textContent = 'Ссылка на профиль скопирована.'; }
            } catch (error) { if (error.name !== 'AbortError') feedback.textContent = `Ссылка на профиль: ${url}`; }
        }
        if (currentMenu && !currentMenu.contains(event.target)) closeMenu();
    });
    document.addEventListener('pointerdown', (event) => {
        if (currentMenu && !currentMenu.contains(event.target) && !currentTrigger?.contains(event.target)) closeMenu();
    });
    document.addEventListener('keydown', (event) => {
        if (!currentMenu) return;
        if (event.key === 'Escape') { event.preventDefault(); closeMenu(true); return; }
        const items = [...currentMenu.querySelectorAll('a[href], button:not(:disabled)')];
        const index = items.indexOf(document.activeElement);
        if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
            event.preventDefault();
            const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
            items[next]?.focus();
        }
        if (event.key === 'Tab') { event.preventDefault(); closeMenu(true); }
    });
    window.addEventListener('resize', () => closeMenu());
    document.addEventListener('scroll', (event) => { if (currentMenu && !currentMenu.contains(event.target)) closeMenu(); }, true);
    document.addEventListener('copybetting:updated', (event) => {
        if (event.target !== panel) return;
        closeMenu(false, true);
        window.clearTimeout(debounce);
        if (pending) { pending.abort(); pending = null; }
        version++;
        content.setAttribute('aria-busy', 'false');
        window.CappersSkeleton?.ready(content);
    });
    window.addEventListener('popstate', () => {
        if (new URLSearchParams(location.search).get('tab') === 'copybetting') load(location.href, false, false);
    });
    window.addEventListener('profile:tab-activated', (event) => {
        if (event.detail?.tab === 'copybetting') return;
        closeMenu(false, true);
        window.clearTimeout(debounce);
        if (pending) { pending.abort(); pending = null; version++; }
        window.CappersSkeleton?.ready(content);
        feedback.textContent = '';
    });
})();
