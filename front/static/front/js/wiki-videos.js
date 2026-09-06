(() => {
    const cards = Array.from(document.querySelectorAll('[data-wiki-video-card]'));
    const modal = document.querySelector('[data-wiki-video-modal]');
    const player = modal?.querySelector('[data-wiki-video-player]');
    const title = modal?.querySelector('[data-wiki-video-player-title]');
    const closeButton = modal?.querySelector('[data-wiki-video-close]');

    const formatDuration = (seconds) => {
        if (!Number.isFinite(seconds) || seconds <= 0) return '';
        const total = Math.round(seconds);
        const hours = Math.floor(total / 3600);
        const minutes = Math.floor((total % 3600) / 60);
        const secs = total % 60;

        if (hours > 0) {
            return `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
        }
        return `${minutes}:${String(secs).padStart(2, '0')}`;
    };

    const loadDuration = (card) => {
        const badge = card.querySelector('[data-wiki-video-duration]');
        const url = card.dataset.videoUrl;
        if (!badge || !url || badge.textContent.trim()) return;

        const probe = document.createElement('video');
        probe.preload = 'metadata';
        probe.muted = true;

        const cleanup = () => {
            probe.removeAttribute('src');
            probe.load();
        };

        probe.addEventListener('loadedmetadata', () => {
            const value = formatDuration(probe.duration);
            if (value) {
                badge.textContent = value;
                badge.hidden = false;
            }
            cleanup();
        }, { once: true });

        probe.addEventListener('error', cleanup, { once: true });
        probe.src = url;
    };

    if ('IntersectionObserver' in window) {
        const durationObserver = new IntersectionObserver((entries, observer) => {
            entries.forEach((entry) => {
                if (!entry.isIntersecting) return;
                loadDuration(entry.target);
                observer.unobserve(entry.target);
            });
        }, { rootMargin: '240px 0px' });

        cards.forEach((card) => durationObserver.observe(card));
    } else {
        cards.forEach(loadDuration);
    }

    if (!modal || !player) return;

    const close = () => {
        player.pause();
        player.removeAttribute('src');
        player.load();
        modal.classList.remove('is-open');
        modal.hidden = true;
        modal.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('wiki-video-player-open');
    };

    const open = (card) => {
        const url = card.dataset.videoUrl;
        if (!url) return;

        if (title) title.textContent = card.dataset.videoTitle || 'Видео';
        modal.hidden = false;
        modal.setAttribute('aria-hidden', 'false');
        modal.classList.add('is-open');
        document.body.classList.add('wiki-video-player-open');

        player.src = url;
        player.load();
        player.play().catch(() => {});
    };

    cards.forEach((card) => {
        card.addEventListener('click', () => open(card));
        card.addEventListener('keydown', (event) => {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            open(card);
        });
    });

    closeButton?.addEventListener('click', close);
    modal.addEventListener('click', (event) => {
        if (event.target === modal) close();
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !modal.hidden) close();
    });
})();
