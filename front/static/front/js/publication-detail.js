(() => {
    const root = document.querySelector('[data-publication-detail]');
    if (!root) return;
    const status = root.querySelector('[data-publication-status]');
    const announce = (text) => {
        if (!status) return;
        status.textContent = text;
        status.hidden = !text;
    };
    root.querySelectorAll('[data-publication-reaction]').forEach((form) => {
        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const button = form.querySelector('button[type="submit"]');
            if (button.disabled) return;
            button.disabled = true;
            announce('');
            try {
                const data = new FormData(form);
                data.set('action', form.dataset.publicationReaction);
                const response = await fetch(form.action, {
                    method: 'POST', body: data, credentials: 'same-origin',
                    headers: {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'},
                });
                if (response.redirected) {
                    window.location.assign(response.url);
                    return;
                }
                const result = await response.json();
                if (!response.ok || !result.ok) throw new Error(result.error || 'Не удалось сохранить. Попробуйте ещё раз.');
                button.classList.toggle('is-active', result.active);
                button.setAttribute('aria-pressed', String(result.active));
                root.querySelectorAll('[data-publication-likes]').forEach((counter) => { counter.textContent = result.likes; });
            } catch (error) {
                announce(error.message === 'Failed to fetch' ? 'Нет связи с сервером. Попробуйте ещё раз.' : error.message);
            } finally {
                button.disabled = false;
            }
        });
    });
    root.querySelectorAll('[data-publication-share]').forEach((button) => {
        button.addEventListener('click', async () => {
            const data = {title: root.querySelector('h1').textContent.trim(), url: window.location.origin + window.location.pathname};
            try {
                if (navigator.share) {
                    await navigator.share(data);
                } else if (navigator.clipboard && window.isSecureContext) {
                    await navigator.clipboard.writeText(data.url);
                    announce('Ссылка скопирована.');
                } else {
                    announce(`Ссылка на материал: ${data.url}`);
                }
            } catch (error) {
                if (error.name !== 'AbortError') announce(`Ссылка на материал: ${data.url}`);
            }
        });
    });
    const toc = root.querySelector('[data-publication-toc]');
    if (toc && window.matchMedia('(max-width: 720px)').matches) toc.open = false;
    const progress = root.querySelector('[data-publication-progress]');
    const body = root.querySelector('[data-publication-body]');
    let scheduled = false;
    const updateProgress = () => {
        scheduled = false;
        if (!progress || !body) return;
        const end = body.getBoundingClientRect().bottom + window.scrollY - window.innerHeight;
        const start = root.getBoundingClientRect().top + window.scrollY;
        progress.value = end > start ? Math.max(0, Math.min(100, (window.scrollY - start) * 100 / (end - start))) : 100;
    };
    const scheduleProgress = () => {
        if (scheduled) return;
        scheduled = true;
        window.requestAnimationFrame(updateProgress);
    };
    window.addEventListener('scroll', scheduleProgress, {passive: true});
    window.addEventListener('resize', scheduleProgress, {passive: true});
    root.querySelectorAll('img').forEach((image) => image.addEventListener('load', scheduleProgress, {once: true}));
    updateProgress();
    const commentForm = root.querySelector('[data-publication-comment-form]');
    if (!commentForm) return;
    const parent = commentForm.querySelector('[data-publication-parent]');
    const replyLabel = commentForm.querySelector('[data-publication-reply-label]');
    const text = commentForm.querySelector('textarea');
    root.querySelectorAll('[data-publication-reply]').forEach((button) => {
        button.addEventListener('click', () => {
            parent.value = button.dataset.publicationReply;
            replyLabel.replaceChildren(document.createTextNode(`Ответ для ${button.dataset.commentName}`));
            const cancel = document.createElement('button');
            cancel.type = 'button';
            cancel.textContent = 'Отмена';
            cancel.addEventListener('click', () => {
                parent.value = '';
                replyLabel.hidden = true;
                text.focus();
            });
            replyLabel.append(cancel);
            replyLabel.hidden = false;
            text.focus();
        });
    });
    commentForm.addEventListener('submit', () => {
        const button = commentForm.querySelector('button[type="submit"]');
        button.disabled = true;
        button.textContent = 'Отправка…';
    });
})();
