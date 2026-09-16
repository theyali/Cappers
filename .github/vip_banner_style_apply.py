from pathlib import Path
import re

MAIN = Path("front/static/front/css/main.css")
MOBILE = Path("front/static/front/css/mobile.css")
TEMPLATE = Path("templates/front/banners/vip_cappers.html")

main_marker = "/* VIP cappers banner */"
mobile_marker = "/* VIP cappers banner responsive */"

legacy_tokens = (
    ".vip-experts-panel",
    ".vip-experts-list",
    ".vip-expert-card",
    ".vip-expert-record",
    ".vip-expert-roi",
)

expected_template_tokens = (
    "vip-cappers-banner",
    "vip-cappers-banner__panel",
    "vip-cappers-banner__hero",
    "vip-cappers-banner__hero-card",
    "vip-cappers-banner__list",
    "vip-cappers-banner__row",
)

main_css = r'''
/* VIP cappers banner */
.vip-cappers-banner {
    width: 100%;
    min-width: 0;
    color: #fff;
}

.vip-cappers-banner,
.vip-cappers-banner * {
    box-sizing: border-box;
}

.vip-cappers-banner__panel {
    min-width: 0;
    display: grid;
    gap: 14px;
    padding: 16px;
    background: #101113;
    box-shadow: inset 0 0 0 1px rgba(112, 112, 114, .26), 0 14px 34px rgba(0, 0, 0, .2);
}

.vip-cappers-banner__head-link {
    min-width: 0;
    display: grid;
    grid-template-columns: 34px minmax(0, 1fr) 22px;
    align-items: center;
    gap: 10px;
    padding: 3px 2px 0;
    color: inherit;
}

.vip-cappers-banner__head-icon {
    width: 34px;
    aspect-ratio: 1;
    display: grid;
    place-items: center;
    color: var(--yellow);
}

.vip-cappers-banner__head-icon svg,
.vip-cappers-banner__head-arrow svg,
.vip-cappers-banner__info svg,
.vip-cappers-banner__footer-arrow svg {
    width: 100%;
    height: 100%;
    display: block;
}

.vip-cappers-banner__head-copy {
    min-width: 0;
    display: grid;
    gap: 3px;
}

.vip-cappers-banner__title,
.vip-cappers-banner__list-head strong {
    overflow: hidden;
    color: #fff;
    font-size: 17px;
    font-weight: 600;
    line-height: 1.2;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.vip-cappers-banner__subtitle {
    overflow: hidden;
    color: var(--muted);
    font-size: 11px;
    font-weight: 500;
    line-height: 1.3;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.vip-cappers-banner__head-arrow,
.vip-cappers-banner__footer-arrow {
    width: 22px;
    aspect-ratio: 1;
    display: grid;
    place-items: center;
    color: var(--muted);
}

.vip-cappers-banner__hero {
    min-width: 0;
    display: grid;
    gap: 12px;
    padding: 14px;
    background: #151618;
    box-shadow: inset 0 0 0 1px rgba(11, 86, 250, .34);
}

.vip-cappers-banner__hero-card {
    min-width: 0;
    display: grid;
    grid-template-columns: minmax(0, 1fr) clamp(96px, 34%, 136px);
    align-items: center;
    gap: 10px;
    color: inherit;
}

.vip-cappers-banner__hero-main {
    min-width: 0;
    display: grid;
    align-content: center;
    gap: 9px;
}

.vip-cappers-banner__week-badge {
    width: max-content;
    max-width: 100%;
    overflow: hidden;
    padding: 7px 10px;
    color: var(--ink);
    background: var(--yellow);
    font-size: 10px;
    font-weight: 600;
    line-height: 1;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.vip-cappers-banner__hero-name-row,
.vip-cappers-banner__row-name-line {
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 6px;
}

.vip-cappers-banner__hero-name,
.vip-cappers-banner__row-name-line strong {
    min-width: 0;
    overflow: hidden;
    color: #fff;
    font-size: 17px;
    font-weight: 600;
    line-height: 1.18;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.vip-cappers-banner__verified,
.vip-cappers-banner__verified svg {
    width: 18px;
    height: 18px;
    flex: 0 0 18px;
}

.vip-cappers-banner__verified .capper-verified-bg {
    fill: var(--blue);
}

.vip-cappers-banner__verified .capper-verified-check {
    fill: #fff;
}

.vip-cappers-banner__hero-meta {
    overflow: hidden;
    color: var(--muted);
    font-size: 11px;
    font-weight: 500;
    line-height: 1.3;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.vip-cappers-banner__hero-stats {
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 2px;
}

.vip-cappers-banner__hero-stat {
    min-width: 0;
    display: grid;
    gap: 2px;
}

.vip-cappers-banner__hero-stat strong {
    color: #fff;
    font-size: 17px;
    font-weight: 600;
    line-height: 1;
    white-space: nowrap;
}

.vip-cappers-banner__hero-stat span {
    color: var(--muted);
    font-size: 10px;
    font-weight: 500;
    line-height: 1.2;
    white-space: nowrap;
}

.vip-cappers-banner__hero-divider {
    width: 1px;
    align-self: stretch;
    background: rgba(112, 112, 114, .5);
}

.vip-cappers-banner__hero-side {
    min-width: 0;
    display: grid;
    place-items: center;
}

.vip-cappers-banner__hero-avatar {
    width: 100%;
    max-width: 136px;
    aspect-ratio: 1;
    display: grid;
    place-items: center;
    overflow: hidden;
    background: var(--panel);
    box-shadow: 0 0 0 2px var(--blue), 0 0 24px rgba(11, 86, 250, .5);
}

.vip-cappers-banner__hero-avatar img,
.vip-cappers-banner__row-avatar img {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: cover;
}

.vip-cappers-banner__hero-avatar-fallback,
.vip-cappers-banner__row-avatar-fallback {
    display: grid;
    place-items: center;
    width: 100%;
    height: 100%;
    color: #fff;
    background: var(--blue);
    font-size: 14px;
    font-weight: 600;
}

.vip-cappers-banner__hero-actions {
    min-width: 0;
}

.vip-cappers-banner__subscribe {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 11px 14px;
    color: var(--ink);
    background: var(--yellow);
    font-size: 14px;
    font-weight: 600;
    line-height: 1.1;
    text-align: center;
}

.vip-cappers-banner__subscribe:hover,
.vip-cappers-banner__subscribe:focus-visible {
    color: var(--ink);
    background: var(--yellow);
}

.vip-cappers-banner__list-box {
    min-width: 0;
    display: grid;
    gap: 11px;
    padding: 14px;
    background: #151618;
    box-shadow: inset 0 0 0 1px rgba(112, 112, 114, .22);
}

.vip-cappers-banner__list-head {
    min-width: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 0 2px;
}

.vip-cappers-banner__info {
    width: 20px;
    aspect-ratio: 1;
    flex: 0 0 20px;
    display: grid;
    place-items: center;
    color: var(--muted);
}

.vip-cappers-banner__list {
    min-width: 0;
    display: grid;
    gap: 7px;
}

.vip-cappers-banner__row {
    min-width: 0;
    display: grid;
    grid-template-columns: 30px 42px minmax(0, 1fr) auto;
    align-items: center;
    gap: 9px;
    padding: 8px;
    color: inherit;
    background: #111214;
    box-shadow: inset 0 0 0 1px rgba(112, 112, 114, .18);
}

.vip-cappers-banner__row-rank {
    width: 30px;
    aspect-ratio: 1;
    display: grid;
    place-items: center;
    color: #fff;
    background: var(--panel);
    font-size: 13px;
    font-weight: 600;
    line-height: 1;
}

.vip-cappers-banner__row-rank--1 {
    color: var(--ink);
    background: var(--yellow);
}

.vip-cappers-banner__row-rank--2,
.vip-cappers-banner__row-rank--3 {
    background: var(--muted);
}

.vip-cappers-banner__row-avatar {
    width: 42px;
    aspect-ratio: 1;
    display: grid;
    place-items: center;
    overflow: hidden;
    background: var(--panel);
    box-shadow: 0 0 0 1px rgba(11, 86, 250, .72);
}

.vip-cappers-banner__row-copy {
    min-width: 0;
    display: grid;
    gap: 3px;
}

.vip-cappers-banner__row-name-line strong {
    font-size: 13px;
}

.vip-cappers-banner__row-subscribers {
    overflow: hidden;
    color: var(--muted);
    font-size: 10px;
    font-weight: 500;
    line-height: 1.2;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.vip-cappers-banner__row-metric {
    min-width: 48px;
    display: grid;
    justify-items: end;
    gap: 3px;
    text-align: right;
}

.vip-cappers-banner__row-metric strong {
    color: var(--yellow);
    font-size: 15px;
    font-weight: 600;
    line-height: 1;
    white-space: nowrap;
}

.vip-cappers-banner__row-metric span {
    color: var(--muted);
    font-size: 9px;
    font-weight: 500;
    line-height: 1;
    white-space: nowrap;
}

.vip-cappers-banner__footer-link {
    min-width: 0;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 20px;
    align-items: center;
    gap: 10px;
    padding: 12px 13px;
    color: #fff;
    background: var(--panel);
    box-shadow: inset 0 0 0 1px rgba(112, 112, 114, .5);
    font-size: 13px;
    font-weight: 600;
    line-height: 1.1;
    text-align: center;
}

.vip-cappers-banner__footer-link > span:first-child {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.vip-cappers-banner__footer-arrow {
    width: 20px;
}
'''.strip()

mobile_css = r'''
/* VIP cappers banner responsive */
@media (max-width: 1120px) {
    .vip-cappers-banner__panel {
        gap: 12px;
        padding: 14px;
    }

    .vip-cappers-banner__hero {
        padding: 13px;
    }

    .vip-cappers-banner__hero-card {
        grid-template-columns: minmax(0, 1fr) clamp(92px, 31vw, 128px);
    }

    .vip-cappers-banner__list-box {
        padding: 13px;
    }
}

@media (max-width: 560px) {
    .vip-cappers-banner__panel {
        gap: 10px;
        padding: 12px;
    }

    .vip-cappers-banner__head-link {
        grid-template-columns: 30px minmax(0, 1fr) 19px;
        gap: 8px;
    }

    .vip-cappers-banner__head-icon {
        width: 30px;
    }

    .vip-cappers-banner__title,
    .vip-cappers-banner__list-head strong {
        font-size: 16px;
    }

    .vip-cappers-banner__hero {
        gap: 10px;
        padding: 12px;
    }

    .vip-cappers-banner__hero-card {
        grid-template-columns: minmax(0, 1fr) clamp(84px, 29vw, 112px);
        gap: 8px;
    }

    .vip-cappers-banner__hero-main {
        gap: 7px;
    }

    .vip-cappers-banner__week-badge {
        padding: 6px 8px;
        font-size: 9px;
    }

    .vip-cappers-banner__hero-name {
        font-size: 15px;
    }

    .vip-cappers-banner__hero-stats {
        gap: 9px;
    }

    .vip-cappers-banner__hero-stat strong {
        font-size: 15px;
    }

    .vip-cappers-banner__hero-stat span,
    .vip-cappers-banner__hero-meta {
        font-size: 9px;
    }

    .vip-cappers-banner__subscribe {
        padding: 10px 12px;
        font-size: 13px;
    }

    .vip-cappers-banner__list-box {
        gap: 9px;
        padding: 11px;
    }

    .vip-cappers-banner__row {
        grid-template-columns: 28px 38px minmax(0, 1fr) auto;
        gap: 7px;
        padding: 7px;
    }

    .vip-cappers-banner__row-rank {
        width: 28px;
        font-size: 12px;
    }

    .vip-cappers-banner__row-avatar {
        width: 38px;
    }

    .vip-cappers-banner__row-name-line {
        gap: 4px;
    }

    .vip-cappers-banner__row-name-line strong {
        font-size: 12px;
    }

    .vip-cappers-banner__row-subscribers {
        font-size: 9px;
    }

    .vip-cappers-banner__row-metric {
        min-width: 42px;
    }

    .vip-cappers-banner__row-metric strong {
        font-size: 13px;
    }

    .vip-cappers-banner__row-metric span {
        font-size: 8px;
    }

    .vip-cappers-banner__verified,
    .vip-cappers-banner__verified svg {
        width: 16px;
        height: 16px;
        flex-basis: 16px;
    }
}

@media (max-width: 390px) {
    .vip-cappers-banner__panel {
        padding: 10px;
    }

    .vip-cappers-banner__subtitle {
        font-size: 10px;
    }

    .vip-cappers-banner__hero-card {
        grid-template-columns: minmax(0, 1fr) 82px;
    }

    .vip-cappers-banner__hero-stats {
        gap: 7px;
    }

    .vip-cappers-banner__row {
        grid-template-columns: 26px 34px minmax(0, 1fr) auto;
        gap: 6px;
        padding: 6px;
    }

    .vip-cappers-banner__row-rank {
        width: 26px;
        font-size: 11px;
    }

    .vip-cappers-banner__row-avatar {
        width: 34px;
    }

    .vip-cappers-banner__row-metric {
        min-width: 38px;
    }

    .vip-cappers-banner__row-metric strong {
        font-size: 12px;
    }

    .vip-cappers-banner__row-metric span {
        display: none;
    }
}
'''.strip()


def validate_block(block: str, label: str) -> None:
    if "gradient" in block.lower():
        raise SystemExit(f"{label}: gradients are not allowed")
    if re.search(r"(^|\s)border(?:-[a-z]+)?\s*:", block):
        raise SystemExit(f"{label}: border declarations are not allowed")

    for value in re.findall(r"font-size\s*:\s*([0-9.]+)px", block):
        if float(value) > 17:
            raise SystemExit(f"{label}: font-size {value}px exceeds 17px")
    for value in re.findall(r"font-weight\s*:\s*([0-9]+)", block):
        if int(value) > 600:
            raise SystemExit(f"{label}: font-weight {value} exceeds 600")


template = TEMPLATE.read_text()
for token in expected_template_tokens:
    if token not in template:
        raise SystemExit(f"Expected template class is missing: {token}")

main_text = MAIN.read_text()
mobile_text = MOBILE.read_text()
for token in legacy_tokens:
    if token in main_text or token in mobile_text:
        raise SystemExit(f"Legacy VIP selector still exists: {token}")

if main_marker in main_text or mobile_marker in mobile_text:
    raise SystemExit("VIP cappers banner style marker already exists")

validate_block(main_css, "main.css VIP block")
validate_block(mobile_css, "mobile.css VIP block")

MAIN.write_text(main_text.rstrip() + "\n\n\n" + main_css + "\n")
MOBILE.write_text(mobile_text.rstrip() + "\n\n\n" + mobile_css + "\n")
