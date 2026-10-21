"""Vector parts of the cards, taken from the og-cards mockup: sport panels, artwork and icons."""

from django.conf import settings

# Sport key (front.sport_tabs.SPORT_TILE_KEYS) -> panel colour, panel pattern.
SPORTS = {
    "f": ("#127A40", "diag"),
    "t": ("#4338CA", "dots"),
    "b": ("#6A2BE0", "grid"),
    "h": ("#0E5FA8", "bands"),
    "e": ("#9F1239", "diag"),
    "v": ("#B45309", "dots"),
    "x": ("#2A2D36", "diag"),
}

ART = {
    "f": (
        '<defs><clipPath id="a"><circle cx="100" cy="100" r="90"/></clipPath></defs>'
        '<circle cx="100" cy="100" r="90" fill="#ffffff"/>'
        '<g clip-path="url(#a)" fill="#141519"><polygon points="100,72 126.6,91.3 116.5,122.7 83.5,122.7 73.4,91.3"/>'
        '<polygon points="100,2 126,20 116,46 84,46 74,20"/><polygon points="182,72 205,90 196,118 168,112 162,86"/>'
        '<polygon points="18,72 38,86 32,112 4,118 -5,90"/><polygon points="150,170 174,160 186,184 166,206 140,196"/>'
        '<polygon points="50,170 60,196 34,206 14,184 26,160"/></g>'
        '<path d="M100 72V46M126.6 91.3L162 86M116.5 122.7L150 170M83.5 122.7L50 170M73.4 91.3L38 86" '
        'stroke="#141519" stroke-width="3" fill="none"/>'
        '<circle cx="100" cy="100" r="89" fill="none" stroke="#141519" stroke-width="3"/>'
    ),
    "t": (
        '<defs><clipPath id="a"><circle cx="100" cy="100" r="90"/></clipPath></defs>'
        '<circle cx="100" cy="100" r="90" fill="#D9F24B"/>'
        '<circle cx="128" cy="126" r="90" fill="#B8D52E" clip-path="url(#a)"/>'
        '<circle cx="92" cy="92" r="80" fill="#D9F24B" clip-path="url(#a)"/>'
        '<path d="M28 38C82 70 82 130 28 162M172 38C118 70 118 130 172 162" fill="none" stroke="#ffffff" '
        'stroke-width="8" stroke-linecap="round"/>'
    ),
    "b": (
        '<circle cx="100" cy="100" r="90" fill="#F0862A"/>'
        '<path d="M100 10v180M10 100h180M38 35c30 30 30 100 0 130M162 35c-30 30-30 100 0 130" fill="none" '
        'stroke="#2A1607" stroke-width="5"/>'
    ),
    "h": (
        '<path d="M150 18L96 138Q90 152 76 152L24 152" fill="none" stroke="#EEF3F9" stroke-width="14" '
        'stroke-linecap="round" stroke-linejoin="round"/><path d="M34 152H62" stroke="#14161B" stroke-width="14"/>'
        '<ellipse cx="112" cy="180" rx="44" ry="14" fill="#05070B"/><rect x="68" y="160" width="88" height="20" '
        'fill="#05070B"/><ellipse cx="112" cy="160" rx="44" ry="14" fill="#2D3140"/>'
    ),
    "e": (
        '<path d="M62 64h76a42 42 0 0 1 41 34l9 46a25 25 0 0 1-46 17l-12-19H70l-12 19a25 25 0 0 1-46-17l9-46a42 42 '
        '0 0 1 41-34z" fill="#E6E9F2"/><path d="M52 96v28M38 110h28" stroke="#141519" stroke-width="12" '
        'stroke-linecap="round"/><circle cx="138" cy="100" r="9" fill="#141519"/>'
        '<circle cx="160" cy="122" r="9" fill="#141519"/>'
    ),
    "v": (
        '<circle cx="100" cy="100" r="90" fill="#fff"/><path d="M100 10c-30 46-34 113 16 179M190 92c-54-10-113 '
        '16-145 83M40 154c14-52 59-96 129-104" fill="none" stroke="#1E3A8A" stroke-width="9" stroke-linecap="round"/>'
    ),
}

GLYPH = {
    "f": (
        '<circle cx="12" cy="12" r="9"/><path d="M12 7.6l3.8 2.8-1.45 4.5h-4.7L8.2 10.4z"/>'
        '<path d="M12 3v4.6M3.6 13.1l4.6-2.7M20.4 13.1l-4.6-2.7M8 20.4l2.35-5.5M16 20.4l-2.35-5.5"/>'
    ),
    "t": '<circle cx="12" cy="12" r="9"/><path d="M5.1 5.5c4.4 3 4.4 10 0 13M18.9 5.5c-4.4 3-4.4 10 0 13"/>',
    "b": (
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M12 3v18M3 12h18M5.7 5.7c3.1 3 3.1 9.6 0 12.6M18.3 5.7c-3.1 3-3.1 9.6 0 12.6"/>'
    ),
    "h": '<ellipse cx="12" cy="9" rx="8" ry="3"/><path d="M4 9v6a8 3 0 0 0 16 0V9"/>',
    "e": (
        '<path d="M7.7 8.2h8.6a4.3 4.3 0 0 1 4.2 3.5l.6 3.5a2.6 2.6 0 0 1-4.8 1.8l-1-1.5H8.7l-1 1.5a2.6 2.6 0 0 '
        '1-4.8-1.8l.6-3.5a4.3 4.3 0 0 1 4.2-3.5z"/><path d="M7 11.3v2.6M5.7 12.6h2.6M16.2 11.8h.01M18.4 13.8h.01"/>'
    ),
    "v": (
        '<circle cx="12" cy="12" r="9"/><path d="M12 3c-3 4.6-3.4 11.3 1.6 17.9M20.8 10.2c-5.4-1-11.3 1.6-14.5 '
        '8.3M4 16.2c1.4-5.2 5.9-9.6 12.9-10.4"/>'
    ),
    "x": '<circle cx="12" cy="12" r="9"/>',
}

VERIFIED = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12 1.8l2.5 1.9 3.1-.2.9 3 2.5 '
    '1.9-1.2 2.9 1.2 2.9-2.5 1.9-.9 3-3.1-.2L12 22.8l-2.5-1.9-3.1.2-.9-3L3 14.2l1.2-2.9L3 8.4l2.5-1.9.9-3 3.1.2z" '
    'fill="#2F6BFF"/><path d="M8.4 12.2l2.4 2.4 4.8-5.1" fill="none" stroke="#ffffff" stroke-width="2.2" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
LOCK = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#F6EC4E" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round"><rect x="4.5" y="10.5" width="15" height="10" rx="3"/>'
    '<path d="M8 10.5V7.8a4 4 0 0 1 8 0v2.7"/></svg>'
)
FLAME = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#F2A33C"><path d="M12 2.5s5.5 4.6 5.5 '
    '9.2A5.5 5.5 0 0 1 6.5 12c0-1.8 1-3.6 1-3.6s.7 2.3 2.3 2.3c0-3.4 2.2-8.2 2.2-8.2z"/></svg>'
)


def glyph_svg(key: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#ffffff" '
        f'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">{GLYPH.get(key, GLYPH["x"])}</svg>'
    )


def art_svg(key: str) -> str:
    art = ART.get(key)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">{art}</svg>' if art else ""


def panel_svg(key: str, width: int, height: int = 630) -> str:
    """Sport colour with its pattern, sized for the right panel of a card."""
    color, pattern = SPORTS.get(key, SPORTS["x"])
    shapes = []
    if pattern == "diag":
        shapes = [
            f'<path d="M{-704 + step * 74} 640L{120 + step * 74} -10" stroke="#ffffff" stroke-opacity="0.08" '
            'stroke-width="26"/>'
            for step in range(17)
        ]
    elif pattern == "grid":
        shapes = [
            f'<path d="M{x} 0V{height}" stroke="#ffffff" stroke-opacity="0.09" stroke-width="2"/>'
            for x in range(22, width, 44)
        ] + [
            f'<path d="M0 {y}H{width}" stroke="#ffffff" stroke-opacity="0.09" stroke-width="2"/>'
            for y in range(22, height, 44)
        ]
    elif pattern == "bands":
        shapes = [
            f'<rect x="0" y="{y}" width="{width}" height="26" fill="#ffffff" fill-opacity="0.07"/>'
            for y in range(-10, height, 56)
        ]
    elif pattern == "dots":
        shapes = [
            '<defs><pattern id="d" width="34" height="34" patternUnits="userSpaceOnUse">'
            '<circle cx="8" cy="8" r="4.4" fill="#ffffff" fill-opacity="0.14"/></pattern></defs>'
            f'<rect width="{width}" height="{height}" fill="url(#d)"/>'
        ]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" fill="{color}"/>{"".join(shapes)}</svg>'
    )


def coin_svg() -> bytes:
    """The site's coin icon, drawn next to stakes and winnings."""
    path = settings.BASE_DIR / "templates" / "front" / "svgs" / "coin.svg"
    return path.read_bytes()
