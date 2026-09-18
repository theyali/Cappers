(() => {
    const page = document.querySelector('[data-referrals-page]');
    if (!page) return;

    const copyButton = page.querySelector('[data-referral-copy]');
    const referralLink = page.querySelector('[data-referral-link]');
    if (!copyButton || !referralLink) return;

    const copyReferralLink = async () => {
        const value = referralLink.value;
        if (!value) throw new Error('Реферальная ссылка не найдена.');

        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(value);
            return;
        }

        referralLink.focus();
        referralLink.select();
        referralLink.setSelectionRange(0, value.length);
        if (!document.execCommand('copy')) {
            throw new Error('Не удалось скопировать ссылку.');
        }
    };

    copyButton.addEventListener('click', async () => {
        const defaultLabel = copyButton.textContent;
        copyButton.disabled = true;

        try {
            await copyReferralLink();
            copyButton.textContent = 'Скопировано';
            copyButton.classList.add('is-copied');
        } catch (_) {
            copyButton.textContent = 'Не удалось';
            copyButton.classList.remove('is-copied');
        }

        window.setTimeout(() => {
            copyButton.textContent = defaultLabel;
            copyButton.disabled = false;
            copyButton.classList.remove('is-copied');
        }, 1600);
    });
})();
