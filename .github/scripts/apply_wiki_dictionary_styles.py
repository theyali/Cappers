from pathlib import Path

MAIN_MARKER = "/* Wiki dictionary reference layout */"
MOBILE_MARKER = "/* Wiki dictionary reference responsive */"

MAIN_CSS = r'''
/* Wiki dictionary reference layout */
.wiki-dictionary {
    scroll-margin-top: 96px;
    display: grid;
    gap: 22px;
    padding: 34px 6px 12px;
}

.wiki-dictionary-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 32px;
}

.wiki-dictionary-title {
    min-width: 0;
}

.wiki-dictionary-kicker {
    margin: 0 0 8px;
    color: var(--yellow);
    font-size: 11px;
    font-weight: 800;
    letter-spacing: .15em;
    text-transform: uppercase;
}

.wiki-dictionary-title h2 {
    margin: 0;
    color: var(--text);
    font-size: 42px;
    line-height: 1;
}

.wiki-dictionary-title > p:last-child {
    max-width: 920px;
    margin: 12px 0 0;
    color: rgba(255, 255, 255, .66);
    font-size: 16px;
    line-height: 1.55;
}

.wiki-dictionary-note {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: 13px;
    padding-top: 8px;
    color: rgba(255, 255, 255, .62);
    font-size: 12px;
    line-height: 1.35;
    text-align: right;
}

.wiki-dictionary-note i {
    width: 2px;
    height: 28px;
    display: block;
    background: var(--yellow);
    transform: skew(-18deg);
}

.wiki-dictionary-search {
    min-height: 58px;
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 0 22px;
    border: 0;
    border-radius: 12px;
    background: #202023;
}

.wiki-dictionary-search-icon {
    width: 22px;
    height: 22px;
    flex: 0 0 auto;
    color: #fff;
}

.wiki-dictionary-search-icon svg {
    width: 100%;
    height: 100%;
    display: block;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.8;
    stroke-linecap: round;
    stroke-linejoin: round;
}

.wiki-dictionary-search input[type='search'] {
    width: 100%;
    min-width: 0;
    min-height: 58px;
    padding: 0;
    border: 0;
    outline: 0;
    color: var(--text);
    background: transparent;
    font-size: 14px;
}

.wiki-dictionary-search input[type='search']::placeholder {
    color: rgba(255, 255, 255, .48);
}

.wiki-dictionary-search input[type='search']::-webkit-search-cancel-button {
    filter: invert(1);
    opacity: .65;
}

.wiki-dictionary-layout {
    display: grid;
    grid-template-columns: 275px minmax(0, 1fr);
    gap: 20px;
    align-items: start;
}

.wiki-dictionary-sidebar {
    display: grid;
    gap: 4px;
    padding: 12px;
    border-radius: 14px;
    background: #19191b;
}

.wiki-dictionary-filter {
    min-width: 0;
    min-height: 48px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 7px 8px 7px 10px;
    border-radius: 10px;
    color: rgba(255, 255, 255, .74);
    background: transparent;
    transition: background .16s ease, color .16s ease;
}

.wiki-dictionary-filter:hover {
    color: #fff;
    background: #252528;
}

.wiki-dictionary-filter.is-active {
    color: #fff;
    background: var(--blue);
}

.wiki-dictionary-filter-main {
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 11px;
}

.wiki-dictionary-filter-main > span:last-child {
    min-width: 0;
    overflow: hidden;
    font-size: 13px;
    font-weight: 700;
    line-height: 1.2;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.wiki-dictionary-filter-icon {
    width: 32px;
    height: 32px;
    flex: 0 0 auto;
    display: grid;
    place-items: center;
    border-radius: 9px;
    color: var(--wiki-term-accent-fg);
    background: var(--wiki-term-accent-bg);
}

.wiki-dictionary-filter-icon svg {
    width: 19px;
    height: 19px;
    display: block;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.8;
    stroke-linecap: round;
    stroke-linejoin: round;
}

.wiki-dictionary-filter.is-active .wiki-dictionary-filter-icon {
    color: #fff;
    background: rgba(255, 255, 255, .12);
}

.wiki-dictionary-filter-count {
    min-width: 30px;
    height: 30px;
    flex: 0 0 auto;
    display: inline-grid;
    place-items: center;
    padding: 0 7px;
    border-radius: 9px;
    color: rgba(255, 255, 255, .88);
    background: #2d2d31;
    font-size: 11px;
    font-weight: 800;
}

.wiki-dictionary-filter.is-active .wiki-dictionary-filter-count {
    color: #fff;
    background: rgba(19, 19, 19, .18);
}

.wiki-dictionary-content {
    min-width: 0;
    display: grid;
    gap: 18px;
}

.wiki-term-grid {
    min-width: 0;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 16px;
}

.wiki-term-card {
    min-width: 0;
    min-height: 152px;
    display: grid;
    grid-template-columns: 58px minmax(0, 1fr);
    align-items: start;
    gap: 16px;
    padding: 20px;
    border-radius: 12px;
    background: #202022;
}

.wiki-term-card-icon {
    width: 58px;
    height: 58px;
    display: grid;
    place-items: center;
    border-radius: 13px;
    color: var(--wiki-term-accent-fg);
    background: var(--wiki-term-accent-bg);
}

.wiki-term-card-icon svg {
    width: 31px;
    height: 31px;
    display: block;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.8;
    stroke-linecap: round;
    stroke-linejoin: round;
}

.wiki-term-card-copy {
    min-width: 0;
    display: grid;
    gap: 9px;
}

.wiki-term-card-head {
    min-width: 0;
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
}

.wiki-term-card-head h3 {
    min-width: 0;
    margin: 4px 0 0;
    color: #fff;
    font-family: var(--font-body);
    font-size: 17px;
    font-weight: 800;
    line-height: 1.25;
    letter-spacing: -.02em;
}

.wiki-term-card-arrow {
    width: 30px;
    height: 30px;
    flex: 0 0 auto;
    display: grid;
    place-items: center;
    border-radius: 50%;
    color: #fff;
    background: #303034;
}

.wiki-term-card-arrow svg {
    width: 15px;
    height: 15px;
    display: block;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
}

.wiki-term-card-copy > p {
    margin: 0;
    color: rgba(255, 255, 255, .58);
    font-size: 13px;
    line-height: 1.5;
}

.wiki-term-accent-blue {
    --wiki-term-accent-bg: var(--blue);
    --wiki-term-accent-fg: #fff;
}

.wiki-term-accent-yellow {
    --wiki-term-accent-bg: #3c3a12;
    --wiki-term-accent-fg: var(--yellow);
}

.wiki-term-accent-slate {
    --wiki-term-accent-bg: #44474f;
    --wiki-term-accent-fg: #edf1ff;
}

.wiki-term-accent-light {
    --wiki-term-accent-bg: #d7dde8;
    --wiki-term-accent-fg: #25282d;
}

.wiki-dictionary-more {
    min-height: 54px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 9px;
    padding: 0 18px;
    border-radius: 11px;
    color: #fff;
    background: #242427;
    font-size: 12px;
    font-weight: 800;
    transition: background .16s ease;
}

.wiki-dictionary-more:hover {
    background: #2d2d31;
}

.wiki-dictionary-more svg {
    width: 17px;
    height: 17px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
}

.wiki-dictionary-empty {
    min-height: 320px;
}
'''.strip()

MOBILE_CSS = r'''
/* Wiki dictionary reference responsive */
@media (max-width: 1320px) {
    .wiki-term-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 980px) {
    .wiki-dictionary-layout {
        grid-template-columns: 1fr;
    }

    .wiki-dictionary-sidebar {
        display: flex;
        gap: 7px;
        overflow-x: auto;
        padding: 8px;
        scrollbar-width: none;
    }

    .wiki-dictionary-sidebar::-webkit-scrollbar {
        display: none;
    }

    .wiki-dictionary-filter {
        min-width: max-content;
        flex: 0 0 auto;
    }
}

@media (max-width: 760px) {
    .wiki-dictionary {
        gap: 14px;
        padding: 22px 0 4px;
    }

    .wiki-dictionary-head {
        display: block;
    }

    .wiki-dictionary-title h2 {
        font-size: 34px;
    }

    .wiki-dictionary-title > p:last-child {
        margin-top: 9px;
        font-size: 13px;
    }

    .wiki-dictionary-note {
        display: none;
    }

    .wiki-dictionary-search {
        min-height: 52px;
        gap: 11px;
        padding: 0 14px;
        border-radius: 11px;
    }

    .wiki-dictionary-search-icon {
        width: 19px;
        height: 19px;
    }

    .wiki-dictionary-search input[type='search'] {
        min-height: 52px;
        font-size: 13px;
    }

    .wiki-dictionary-layout {
        gap: 12px;
    }

    .wiki-dictionary-sidebar {
        margin-right: -12px;
        margin-left: -12px;
        padding-right: 12px;
        padding-left: 12px;
        border-radius: 0;
        background: transparent;
    }

    .wiki-dictionary-filter {
        min-height: 44px;
        padding: 6px 8px;
        border-radius: 10px;
        background: var(--panel);
    }

    .wiki-dictionary-filter-icon {
        width: 30px;
        height: 30px;
    }

    .wiki-dictionary-filter-count {
        height: 28px;
        min-width: 28px;
    }

    .wiki-term-grid {
        grid-template-columns: 1fr;
        gap: 10px;
    }

    .wiki-term-card {
        min-height: 132px;
        grid-template-columns: 50px minmax(0, 1fr);
        gap: 13px;
        padding: 15px;
        border-radius: 12px;
    }

    .wiki-term-card-icon {
        width: 50px;
        height: 50px;
        border-radius: 12px;
    }

    .wiki-term-card-icon svg {
        width: 27px;
        height: 27px;
    }

    .wiki-term-card-head h3 {
        margin-top: 2px;
        font-size: 16px;
    }

    .wiki-term-card-copy > p {
        font-size: 12px;
        line-height: 1.48;
    }

    .wiki-term-card-arrow {
        width: 28px;
        height: 28px;
    }

    .wiki-dictionary-more {
        min-height: 50px;
        border-radius: 11px;
    }
}
'''.strip()

main = Path('front/static/front/css/main.css')
mobile = Path('front/static/front/css/mobile.css')

main_text = main.read_text()
if MAIN_MARKER not in main_text:
    main.write_text(main_text.rstrip() + '\n\n' + MAIN_CSS + '\n')

mobile_text = mobile.read_text()
if MOBILE_MARKER not in mobile_text:
    mobile.write_text(mobile_text.rstrip() + '\n\n' + MOBILE_CSS + '\n')

Path('.github/workflows/wiki-term-dictionary-css.yml').unlink(missing_ok=True)
Path('.github/scripts/apply_wiki_dictionary_styles.py').unlink(missing_ok=True)
