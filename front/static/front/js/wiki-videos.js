(() => {
    const page = document.querySelector('[data-wiki-page]');
    if (!page) return;

    const cards = Array.from(page.querySelectorAll('[data-wiki-video-card]'));
    const nextCards = Array.from(page.querySelectorAll('[data-wiki-video-next]'));
    const watchView = page.querySelector('[data-wiki-watch-view]');
    const playerShell = page.querySelector('[data-wiki-watch-player-shell]');
    const poster = page.querySelector('[data-wiki-watch-poster]');
    const player = page.querySelector('[data-wiki-watch-player]');
    const playButton = page.querySelector('[data-wiki-watch-play]');
    const playerToggle = page.querySelector('[data-wiki-player-toggle]');
    const playerMute = page.querySelector('[data-wiki-player-mute]');
    const playerFullscreen = page.querySelector('[data-wiki-player-fullscreen]');
    const playerSeek = page.querySelector('[data-wiki-player-seek]');
    const playerVolume = page.querySelector('[data-wiki-player-volume]');
    const playerCurrent = page.querySelector('[data-wiki-player-current]');
    const playerDuration = page.querySelector('[data-wiki-player-duration]');
    const playerRemaining = page.querySelector('[data-wiki-player-remaining]');
    const title = page.querySelector('[data-wiki-watch-title]');
    const viewsNode = page.querySelector('[data-wiki-watch-views]');
    const addedNode = page.querySelector('[data-wiki-watch-added]');
    const tagsNode = page.querySelector('[data-wiki-watch-tags]');
    const descriptionNode = page.querySelector('[data-wiki-watch-description]');
    const descriptionToggle = page.querySelector('[data-wiki-description-toggle]');
    const progressBar = page.querySelector('[data-wiki-watch-progress-bar]');
    const backButtons = page.querySelectorAll('[data-wiki-back-to-feed]');
    const shareButton = page.querySelector('[data-wiki-share]');
    const mobileSearchButton = page.querySelector('[data-wiki-mobile-search]');
    const searchForm = page.querySelector('[data-wiki-search]');

    let activeCard = null;
    let progressTimer = null;
    let lastProgressSent = 0;
    const viewedVideos = new Set();

    const shareVideo = (card) => {
        const url = new URL(window.location.href);
        if (card?.dataset.videoId) url.searchParams.set('v', card.dataset.videoId);
        if (navigator.share && card) {
            navigator.share({ title: card.dataset.videoTitle || document.title, url: url.toString() }).catch(() => {});
            return;
        }
        navigator.clipboard?.writeText(url.toString()).catch(() => {});
    };

    const csrfToken = () => {
        const cookie = document.cookie.split('; ').find((item) => item.startsWith('csrftoken='));
        return cookie ? decodeURIComponent(cookie.slice('csrftoken='.length)) : '';
    };

    const compactViews = (value) => {
        const count = Number(value || 0);
        if (count >= 1000000) return `${String((count / 1000000).toFixed(1)).replace('.', ',').replace(/,0$/, '')} млн.`;
        if (count >= 1000) return `${String((count / 1000).toFixed(1)).replace('.', ',').replace(/,0$/, '')} тыс.`;
        return String(count);
    };

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

    const formatPlayerTime = (seconds) => formatDuration(seconds) || '0:00';

    const parseTimeToSeconds = (value) => {
        const parts = String(value || '')
            .trim()
            .split(':')
            .map((part) => Number(part));
        if (!parts.length || parts.some((part) => !Number.isFinite(part))) return 0;
        if (parts.length === 3) return (parts[0] * 3600) + (parts[1] * 60) + parts[2];
        if (parts.length === 2) return (parts[0] * 60) + parts[1];
        return parts[0];
    };

    const updatePlayerState = () => {
        if (!player) return;
        const browserDuration = Number.isFinite(player.duration) ? player.duration : 0;
        const fallbackDuration = parseTimeToSeconds(activeCard?.dataset.videoDuration);
        const duration = browserDuration || fallbackDuration;
        const current = Number.isFinite(player.currentTime) ? player.currentTime : 0;
        const percent = duration > 0 ? Math.max(0, Math.min(100, (current / duration) * 100)) : 0;

        if (progressBar) progressBar.style.width = `${percent}%`;
        if (playerSeek) {
            playerSeek.value = duration > 0 ? String(Math.round((current / duration) * 1000)) : '0';
            playerSeek.style.setProperty('--wiki-seek-progress', `${percent}%`);
        }
        if (playerCurrent) playerCurrent.textContent = formatPlayerTime(current);
        if (playerDuration) playerDuration.textContent = formatPlayerTime(duration);
        if (playerRemaining) playerRemaining.textContent = `осталось ${formatPlayerTime(Math.max(0, duration - current))}`;

        const isPlaying = !player.paused && !player.ended;
        const isMuted = player.muted || player.volume === 0;
        playerShell?.classList.toggle('is-playing', isPlaying);
        playerShell?.classList.toggle('is-muted', isMuted);
        playerToggle?.setAttribute('aria-label', isPlaying ? 'Пауза' : 'Воспроизвести');
        playerMute?.setAttribute('aria-label', isMuted ? 'Включить звук' : 'Выключить звук');
        if (playerVolume) playerVolume.value = isMuted ? '0' : String(player.volume);
    };

    const togglePlayback = () => {
        if (!player) return;
        if (player.paused || player.ended) {
            player.play().catch(() => {});
        } else {
            player.pause();
        }
    };

    const setWatchMode = (enabled) => {
        page.dataset.viewMode = enabled ? 'watch' : 'feed';
        if (watchView) {
            watchView.hidden = !enabled;
        }
        if (!enabled && player) {
            saveProgress();
            player.pause();
            player.removeAttribute('src');
            player.load();
            playerShell?.classList.remove('is-playing', 'is-started', 'is-muted');
            if (poster) {
                poster.hidden = true;
                poster.removeAttribute('src');
            }
            updatePlayerState();
        }
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    const updateProgress = () => {
        updatePlayerState();
    };

    const saveProgress = () => {
        if (!activeCard || !player || !activeCard.dataset.videoProgressUrl) return;
        if (!Number.isFinite(player.duration) || player.duration <= 0) return;

        const position = Math.floor(player.currentTime || 0);
        const duration = Math.floor(player.duration || 0);
        if (!duration || Math.abs(position - lastProgressSent) < 4) return;
        lastProgressSent = position;

        const token = csrfToken();
        if (!token) return;

        const body = new FormData();
        body.append('position_seconds', String(position));
        body.append('duration_seconds', String(duration));

        fetch(activeCard.dataset.videoProgressUrl, {
            method: 'POST',
            headers: { 'X-CSRFToken': token, 'X-Requested-With': 'XMLHttpRequest' },
            body,
            credentials: 'same-origin',
        })
            .then((response) => response.ok ? response.json() : null)
            .then((data) => {
                if (!data || !activeCard) return;
                activeCard.dataset.videoProgressPosition = String(data.position_seconds || 0);
                activeCard.dataset.videoProgressDuration = String(data.duration_seconds || 0);
                const bar = activeCard.querySelector('.wiki-video-progress i');
                if (bar) bar.style.width = `${data.percent || 0}%`;
            })
            .catch(() => {});
    };

    const incrementView = (card) => {
        const videoId = card.dataset.videoId;
        if (!videoId || viewedVideos.has(videoId) || !card.dataset.videoViewUrl) return;
        viewedVideos.add(videoId);

        const token = csrfToken();
        fetch(card.dataset.videoViewUrl, {
            method: 'POST',
            headers: token ? { 'X-CSRFToken': token, 'X-Requested-With': 'XMLHttpRequest' } : { 'X-Requested-With': 'XMLHttpRequest' },
            credentials: 'same-origin',
        })
            .then((response) => response.ok ? response.json() : null)
            .then((data) => {
        if (!data || !data.views_count) return;
                card.dataset.videoViews = String(data.views_count);
                card.dataset.videoViewsLabel = compactViews(data.views_count);
                if (card === activeCard && viewsNode) {
                    viewsNode.textContent = card.dataset.videoViewsLabel;
                }
            })
            .catch(() => {});
    };

    const openCard = (card) => {
        if (!card || !player) return;
        saveProgress();
        activeCard = card;
        lastProgressSent = Number(card.dataset.videoProgressPosition || 0);

        if (title) title.textContent = card.dataset.videoTitle || 'Видео';
        if (viewsNode) viewsNode.textContent = card.dataset.videoViewsLabel || card.dataset.videoViews || '0';
        if (addedNode) addedNode.textContent = card.dataset.videoAdded || '';
        if (playerCurrent) playerCurrent.textContent = '0:00';
        if (playerDuration) playerDuration.textContent = card.dataset.videoDuration || '0:00';
        if (playerRemaining) playerRemaining.textContent = `осталось ${card.dataset.videoDuration || '0:00'}`;
        if (descriptionNode) descriptionNode.innerHTML = card.querySelector('.wiki-video-description')?.innerHTML || '';
        if (tagsNode) tagsNode.innerHTML = card.querySelector('.wiki-video-tags')?.innerHTML || '';
        refreshDescriptionClamp();

        page.querySelectorAll('.wiki-next-card').forEach((item) => {
            item.classList.toggle('is-active', item.dataset.videoId === card.dataset.videoId);
        });

        player.pause();
        player.src = card.dataset.videoUrl || '';
        if (poster) {
            if (card.dataset.videoPreview) {
                poster.src = card.dataset.videoPreview;
                poster.hidden = false;
            } else {
                poster.hidden = true;
                poster.removeAttribute('src');
            }
        }
        player.load();
        playerShell?.classList.remove('is-playing', 'is-started');
        if (progressBar) progressBar.style.width = '0%';
        updatePlayerState();

        setWatchMode(true);
        incrementView(card);
    };

    cards.forEach((card) => {
        card.querySelector('.wiki-video-open')?.addEventListener('click', () => openCard(card));
        card.querySelector('[data-wiki-card-share]')?.addEventListener('click', () => shareVideo(card));
    });

    nextCards.forEach((item) => {
        item.querySelector('button')?.addEventListener('click', () => {
            const card = cards.find((candidate) => candidate.dataset.videoId === item.dataset.videoId);
            openCard(card);
        });
    });

    backButtons.forEach((button) => button.addEventListener('click', () => setWatchMode(false)));

    player?.addEventListener('loadedmetadata', () => {
        const savedPosition = Number(activeCard?.dataset.videoProgressPosition || 0);
        if (savedPosition > 0 && savedPosition < player.duration - 2) {
            player.currentTime = savedPosition;
        }
        const badge = activeCard?.querySelector('[data-wiki-video-duration]');
        if (badge && !badge.textContent.trim()) {
            badge.textContent = formatDuration(player.duration);
            badge.hidden = false;
        }
        updatePlayerState();
    });

    player?.addEventListener('play', () => {
        playerShell?.classList.add('is-started', 'is-playing');
        updatePlayerState();
    });
    player?.addEventListener('pause', () => {
        playerShell?.classList.remove('is-playing');
        updatePlayerState();
        saveProgress();
    });
    player?.addEventListener('timeupdate', () => {
        updateProgress();
        window.clearTimeout(progressTimer);
        progressTimer = window.setTimeout(saveProgress, 800);
    });
    player?.addEventListener('volumechange', updatePlayerState);
    player?.addEventListener('durationchange', updatePlayerState);
    player?.addEventListener('error', () => {
        playerShell?.classList.remove('is-playing', 'is-started');
        updatePlayerState();
    });
    player?.addEventListener('ended', () => {
        updatePlayerState();
        saveProgress();
    });

    playButton?.addEventListener('click', togglePlayback);
    playerToggle?.addEventListener('click', togglePlayback);
    playerShell?.addEventListener('click', (event) => {
        if (event.target.closest('button, input, a')) return;
        togglePlayback();
    });
    playerSeek?.addEventListener('input', () => {
        if (!player || !Number.isFinite(player.duration) || player.duration <= 0) return;
        player.currentTime = (Number(playerSeek.value || 0) / 1000) * player.duration;
        updatePlayerState();
    });
    playerSeek?.addEventListener('change', saveProgress);
    playerVolume?.addEventListener('input', () => {
        if (!player) return;
        const volume = Math.max(0, Math.min(1, Number(playerVolume.value || 0)));
        player.volume = volume;
        player.muted = volume === 0;
        updatePlayerState();
    });
    playerMute?.addEventListener('click', () => {
        if (!player) return;
        if (player.muted || player.volume === 0) {
            player.muted = false;
            player.volume = Number(playerVolume?.value || 1) || 1;
        } else {
            player.muted = true;
        }
        updatePlayerState();
    });
    playerFullscreen?.addEventListener('click', () => {
        if (!playerShell) return;
        if (document.fullscreenElement) {
            document.exitFullscreen?.();
            return;
        }
        playerShell.requestFullscreen?.();
    });
    document.addEventListener('fullscreenchange', () => {
        playerShell?.classList.toggle('is-fullscreen', document.fullscreenElement === playerShell);
    });

    shareButton?.addEventListener('click', () => {
        shareVideo(activeCard);
    });

    const refreshDescriptionClamp = () => {
        if (!descriptionNode || !descriptionToggle) return;
        descriptionNode.classList.remove('is-expanded');
        descriptionToggle.textContent = 'Показать еще';
        descriptionToggle.hidden = true;

        window.requestAnimationFrame(() => {
            const hasText = Boolean(descriptionNode.textContent.trim());
            const isOverflowing = descriptionNode.scrollHeight > descriptionNode.clientHeight + 2;
            descriptionToggle.hidden = !hasText || !isOverflowing;
        });
    };

    descriptionToggle?.addEventListener('click', () => {
        if (!descriptionNode || !descriptionToggle) return;
        const expanded = descriptionNode.classList.toggle('is-expanded');
        descriptionToggle.textContent = expanded ? 'Свернуть' : 'Показать еще';
    });

    mobileSearchButton?.addEventListener('click', () => {
        page.classList.toggle('is-search-open');
        if (page.classList.contains('is-search-open')) {
            searchForm?.querySelector('input')?.focus();
        }
    });

    const params = new URLSearchParams(window.location.search);
    const requestedVideo = params.get('v');
    if (requestedVideo) {
        const card = cards.find((candidate) => candidate.dataset.videoId === requestedVideo);
        if (card) openCard(card);
    }

    window.addEventListener('beforeunload', saveProgress);
})();
