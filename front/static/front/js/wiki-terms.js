(($) => {
    if (!$) return;

    const $dictionary = $('[data-wiki-dictionary]');
    if (!$dictionary.length) return;

    const $content = $dictionary.find('[data-wiki-terms-content]');
    const $searchForm = $dictionary.find('[data-wiki-terms-search]');
    const $query = $dictionary.find('[data-wiki-terms-query]');
    const $filters = $dictionary.find('[data-wiki-term-filter]');
    const endpoint = window.location.pathname;
    const contentElement = $content.get(0);

    let selectedSectionId = $filters.filter('.is-active').data('section-id') || '';
    let activeRequest = null;
    let searchTimer = null;

    const setActiveFilter = (sectionId) => {
        selectedSectionId = String(sectionId || '');
        $filters.each(function () {
            const $filter = $(this);
            const isActive = String($filter.data('section-id') || '') === selectedSectionId;
            $filter.toggleClass('is-active', isActive);
            $filter.attr('aria-pressed', isActive ? 'true' : 'false');
        });
    };

    const loadTerms = ({ showAll = false } = {}) => {
        if (activeRequest) activeRequest.abort();

        window.CappersSkeleton?.loading(contentElement);
        $content.attr('aria-busy', 'true');

        activeRequest = $.ajax({
            url: endpoint,
            method: 'GET',
            dataType: 'json',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
            },
            data: {
                fragment: 'terms',
                term_section: selectedSectionId,
                q: $query.val().trim(),
                show: showAll ? 'all' : '',
            },
        })
            .done((response) => {
                if (!response || typeof response.html !== 'string') return;
                $content.html(response.html);
            })
            .fail((xhr, status) => {
                if (status !== 'abort') {
                    console.error('Не удалось загрузить термины Wiki.', xhr);
                }
            })
            .always(() => {
                $content.attr('aria-busy', 'false');
                window.CappersSkeleton?.ready(contentElement);
                activeRequest = null;
            });
    };

    $filters.on('click', function () {
        const sectionId = String($(this).data('section-id') || '');
        if (sectionId === selectedSectionId && !$query.val().trim()) return;
        setActiveFilter(sectionId);
        loadTerms();
    });

    $searchForm.on('submit', (event) => {
        event.preventDefault();
        loadTerms();
    });

    $query.on('input', () => {
        window.clearTimeout(searchTimer);
        searchTimer = window.setTimeout(() => loadTerms(), 280);
    });

    $dictionary.on('click', '[data-wiki-terms-more]', () => {
        loadTerms({ showAll: true });
    });
})(window.jQuery);
