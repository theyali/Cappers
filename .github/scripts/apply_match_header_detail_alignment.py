from pathlib import Path

path = Path("front/static/front/css/main.css")
css = path.read_text(encoding="utf-8")
marker = "/* Final match header bookmaker and detail scoreboard alignment */"

if marker not in css:
    css += r'''

/* Final match header bookmaker and detail scoreboard alignment */
.match-card-sport-label {
    width: 100%;
    min-width: 0;
    min-height: 32px;
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    align-items: center;
    gap: 8px;
    color: var(--muted);
    font-size: 11px;
    line-height: 1;
}

.match-card-sport-copy {
    min-width: 0;
    display: inline-flex;
    align-items: center;
    justify-self: start;
    gap: 5px;
}

.match-card-sport-label .matches-sport-icon {
    width: 20px;
    height: 20px;
    flex: 0 0 20px;
}

.match-card-sport-icon-inner {
    width: 20px;
    height: 20px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transform: scale(.72);
    transform-origin: center;
}

.match-card-sport-name {
    min-width: 0;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
}

.match-card-sport-bookmaker {
    grid-column: 2;
    display: flex;
    align-items: center;
    justify-content: center;
    justify-self: center;
    min-width: 32px;
    min-height: 32px;
}

.match-card-sport-bookmaker .bookmaker-ref.is-compact {
    display: inline-grid;
    place-items: center;
}

.match-card-sport-bookmaker .bookmaker-ref.is-compact .bookmaker-ref-logo {
    width: 32px;
    height: 32px;
    min-height: 32px;
    padding: 3px;
    border-radius: 8px;
}

.match-card-sport-bookmaker .bookmaker-ref.is-compact img {
    width: 26px;
    height: 26px;
    object-fit: contain;
}

.match-card-sport-label > .match-status {
    grid-column: 3;
    justify-self: end;
    margin: 0 !important;
}

.match-card-odds-row > .match-card-bookmaker-row {
    display: none !important;
}

.match-detail-scoreboard > .match-detail-bookmaker-strip {
    grid-column: 1 / -1;
    width: 100%;
    min-width: 0;
}

@media (min-width: 1121px) {
    .match-detail-scoreboard > .match-detail-bookmaker-strip {
        grid-column: 1 / -1;
        width: 100%;
        min-width: 0;
        align-self: center;
        grid-template-columns: 88px auto 88px;
        justify-content: center;
        gap: 14px;
        margin: 0;
    }

    .match-detail-scoreboard > .match-detail-team:nth-child(3) {
        grid-template-columns: 64px minmax(0, 1fr);
        grid-template-areas:
            "logo name"
            "logo sub";
        justify-items: start;
        text-align: left;
    }

    .match-detail-scoreboard > .match-detail-team:nth-child(3) .match-detail-logo {
        grid-area: logo;
    }

    .match-detail-scoreboard > .match-detail-team:nth-child(3) strong {
        grid-area: name;
    }

    .match-detail-scoreboard > .match-detail-team:nth-child(3) small {
        grid-area: sub;
    }
}

@media (max-width: 760px) {
    .match-card-sport-label {
        gap: 6px;
    }

    .match-card-sport-bookmaker {
        min-width: 30px;
        min-height: 30px;
    }

    .match-card-sport-bookmaker .bookmaker-ref.is-compact .bookmaker-ref-logo {
        width: 30px;
        height: 30px;
        min-height: 30px;
    }

    .match-card-sport-bookmaker .bookmaker-ref.is-compact img {
        width: 24px;
        height: 24px;
    }
}
'''
    path.write_text(css, encoding="utf-8")
