(() => {
    const hero = document.querySelector("[data-matches-hero-skeleton]");
    if (!hero) return;

    window.CappersSkeleton?.loading(hero);

    const backgroundUrl = hero.dataset.skeletonBackground;
    if (!backgroundUrl) {
        window.CappersSkeleton?.ready(hero);
        return;
    }

    const backgroundImage = new Image();
    const finish = () => window.CappersSkeleton?.ready(hero);

    backgroundImage.addEventListener("load", finish, { once: true });
    backgroundImage.addEventListener("error", finish, { once: true });
    backgroundImage.src = backgroundUrl;

    if (backgroundImage.complete) {
        finish();
    }
})();
