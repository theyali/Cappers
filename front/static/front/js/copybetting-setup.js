(() => {
    const root = document.querySelector('[data-copy-setup]');
    if (!root) return;
    const form = root.querySelector('[data-copy-setup-form]');
    const calculation = root.querySelector('[data-copy-calculation]');
    const history = root.querySelector('[data-copy-history-preview]');
    const status = root.querySelector('[data-copy-preview-status]');
    const submit = root.querySelector('[data-copy-setup-submit]');
    const sports = [...form.querySelectorAll('[name="allowed_sports"]')];
    let request = null, version = 0, timer = null;
    const updateControls = () => {
        root.querySelectorAll('[data-copy-percent]').forEach((button) => {
            const active = Number(form.elements.stake_percent.value) === Number(button.dataset.copyPercent);
            button.classList.toggle('is-active', active); button.setAttribute('aria-pressed', String(active));
        });
        const all = !sports.some((input) => input.checked);
        const button = root.querySelector('[data-copy-all-sports]');
        button.classList.toggle('is-active', all); button.setAttribute('aria-pressed', String(all));
    };
    const preview = async () => {
        if (request) request.abort();
        const controller = new AbortController(); request = controller;
        const current = ++version;
        status.textContent = 'Обновляем пример…';
        submit.disabled = true;
        const timeout = setTimeout(() => controller.abort('timeout'), 15000);
        try {
            const response = await fetch(root.dataset.previewUrl, { method: 'POST', credentials: 'same-origin', signal: controller.signal, body: new FormData(form), headers: { Accept: 'application/json' } });
            if (!response.ok) throw new Error('preview');
            const payload = await response.json();
            if (current !== version) return;
            if (typeof payload.html !== 'string' || typeof payload.calculation !== 'string') throw new Error('payload');
            calculation.innerHTML = payload.calculation; history.innerHTML = payload.html;
            status.textContent = (payload.errors || []).join(' ');
            submit.disabled = payload.valid === false;
        } catch (error) {
            if (current === version && (!controller.signal.aborted || controller.signal.reason === 'timeout')) {
                submit.disabled = false;
                status.textContent = 'Не удалось обновить пример. Измените параметр для повтора. Сохранение проверит актуальные настройки.';
            }
        } finally { clearTimeout(timeout); if (current === version) request = null; }
    };
    const schedule = () => {
        clearTimeout(timer);
        if (request) { request.abort(); request = null; version++; }
        updateControls();
        submit.disabled = true;
        timer = setTimeout(preview, 250);
    };
    form.addEventListener('input', (event) => { if (!event.isComposing) schedule(); });
    form.addEventListener('change', schedule);
    form.addEventListener('compositionend', schedule);
    root.querySelectorAll('[data-copy-percent]').forEach((button) => button.addEventListener('click', () => {
        form.elements.stake_percent.value = button.dataset.copyPercent; schedule();
    }));
    root.querySelector('[data-copy-all-sports]').addEventListener('click', () => { sports.forEach((input) => { input.checked = false; }); schedule(); });
    form.addEventListener('submit', () => { clearTimeout(timer); request?.abort(); });
    updateControls();
})();
