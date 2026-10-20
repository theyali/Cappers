(() => {
    const closeMenus = (event) => {
        document.querySelectorAll('.expert-copy-more[open]').forEach((menu) => {
            if (!menu.contains(event.target) || event.target.closest('a, button')) menu.open = false;
        });
    };
    document.addEventListener('click', closeMenus);
    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') return;
        document.querySelectorAll('.expert-copy-more[open]').forEach((menu) => {
            menu.open = false;
            menu.querySelector('summary').focus({ preventScroll: true });
        });
    });

    const $ = window.jQuery;
    if (!$) return;
    $(document).on('submit', '[data-copy-limits-form]', function (event) {
        event.preventDefault();
        const form = this, button = form.querySelector('button[type="submit"]'), status = form.querySelector('[data-copy-limits-feedback]');
        if (button.disabled) return;
        button.disabled = true;
        status.textContent = 'Сохраняем…';
        $.ajax({ url: form.action, type: 'POST', data: $(form).serializeArray(), dataType: 'json', timeout: 15000 })
            .done((payload) => { status.textContent = payload.message; })
            .fail((xhr) => { status.textContent = xhr.responseJSON?.error || 'Не удалось сохранить лимиты. Повторите действие.'; })
            .always(() => { button.disabled = false; });
    });
    const pending = new Set();
    $(document).on('submit', '[data-copy-status-form]', function (event) {
        event.preventDefault();
        const form = this;
        const scope = form.closest('.expert-copy-strip, .copybetting-reader-row');
        const reader = form.dataset.copySurface === 'reader';
        const key = form.action.match(/\/copybetting\/(\d+)\//)?.[1];
        if (!scope || !key || pending.has(key)) return;
        pending.add(key);
        const $buttons = $(scope).find('button:enabled');
        $buttons.prop('disabled', true);
        const feedback = () => reader ? document.querySelector('[data-copy-feedback]') : document.querySelector(`#${scope.id} [data-copy-status-feedback]`);
        const say = (message) => { const node = feedback(); if (node) node.textContent = message; };
        say('Сохраняем…');
        const data = $(form).serializeArray();
        data.push({ name: 'surface', value: reader ? 'reader' : 'public' });
        $.ajax({
            url: form.action, type: 'POST', data, dataType: 'json', timeout: 15000,
            headers: { Accept: 'application/json' },
        }).done((payload) => {
            if (reader) {
                if (typeof payload.reader_html !== 'string' || typeof payload.summary_html !== 'string') { say('Не удалось обновить список. Повторите действие.'); return; }
                const panel = scope.closest('[data-copybetting-panel]');
                $(panel).find('[data-copy-content]').html(payload.reader_html);
                $(panel).find('.copybetting-summary').html(payload.summary_html);
                panel.dispatchEvent(new CustomEvent('copybetting:updated', { bubbles: true }));
            } else {
                if (['desktop_html', 'mobile_html', 'desktop_button_html', 'mobile_button_html'].some((field) => typeof payload[field] !== 'string')) { say('Не удалось обновить состояние. Повторите действие.'); return; }
                ['desktop', 'mobile'].forEach((variant) => {
                    $(`.expert-copy-strip.is-${variant}`).replaceWith(payload[`${variant}_html`]);
                    $(`[data-copy-hero-button="${variant}"]`).replaceWith(payload[`${variant}_button_html`]);
                });
            }
            say(payload.message || 'Настройки сохранены.');
            const updatedScope = reader ? document.querySelector(`[data-copy-reader-id="${scope.dataset.copyReaderId}"]`) : document.getElementById(scope.id);
            updatedScope?.querySelector('.expert-copy-controls button, .expert-copy-cta, .copybetting-reader-actions button, .copybetting-reader-actions summary')?.focus({ preventScroll: true });
        }).fail((xhr) => {
            say(xhr.responseJSON?.error || 'Не удалось сохранить настройки. Повторите действие.');
        }).always(() => {
            pending.delete(key);
            $buttons.prop('disabled', false);
        });
    });
})();
