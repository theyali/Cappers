"""Card layouts from the og-cards mockup: a content column on the left, the sport panel on the right.

The column is laid out like the mockup's flex column: blocks with top margins, and spacers that
take the free height (none when the content is taller than the card, as in the browser).
"""

from functools import lru_cache

from django.conf import settings
from PIL import Image

from cabinet.vip import plural_ru

from . import art
from .canvas import HEIGHT, WIDTH, Canvas, Text, svg_image

BG = "#0E0F12"
PLATE = "#121318"
WHITE = "#FFFFFF"
GREY = "#A3A6B0"
DIM = "#6B6E78"
YELLOW = "#F6EC4E"
GREEN = "#5BE38A"
RED = "#FF4D55"
BLUE = "#2F5BFF"
LINE = "#24262E"
GOLD_PLATE = "#1C1B14"
SKELETON = "#272A33"

PAD_X = 48
PAD_Y = 44
# Panel width and artwork size per card kind, as in the mockup.
PANELS = {
    "single": (400, 330),
    "coupon": (360, 300),
    "profile": (340, 290),
    "newbie": (320, 290),
}
RESULTS = {
    "win": ("ЗАШЛО", "#10231A", "#5BE38A44", GREEN, "ВЫИГРЫШ", GREEN),
    "lose": ("НЕ ЗАШЁЛ", "#2A1517", "#FF4D5544", RED, "ПРОИГРЫШ", RED),
    "refund": ("ВОЗВРАТ", PLATE, None, "#9AA0AC", "ВОЗВРАТ", WHITE),
}


def manrope(value, size, weight, color, **kwargs) -> Text:
    return Text(value, "manrope", size, weight, color, **kwargs)


def unbounded(value, size, color, *, weight=800, **kwargs) -> Text:
    return Text(value, "unbounded", size, weight, color, **kwargs)


def label(value) -> Text:
    return manrope(value, 24, 800, DIM, tracking=0.8)


@lru_cache(maxsize=1)
def logo() -> Image.Image:
    source = Image.open(settings.BASE_DIR / "front" / "static" / "front" / "img" / "logo.png").convert("RGBA")
    return source.crop(source.getchannel("A").getbbox())


@lru_cache(maxsize=4)
def coin(size: int) -> Image.Image:
    return svg_image(art.coin_svg(), size, size)


class Flow:
    """Blocks stacked down the content column."""

    def __init__(self, top: float = PAD_Y, bottom: float = HEIGHT - PAD_Y):
        self.top = top
        self.bottom = bottom
        self.items: list = []

    def add(self, height: float, draw, margin: float = 0):
        self.items.append((margin, height, draw))

    def spacer(self):
        self.items.append(None)

    def render(self):
        used = sum(margin + height for item in self.items if item for margin, height, _draw in [item])
        spacers = self.items.count(None)
        free = max(0.0, self.bottom - self.top - used) / spacers if spacers else 0.0
        y = self.top
        for item in self.items:
            if item is None:
                y += free
                continue
            margin, height, draw = item
            y += margin
            draw(y)
            y += height


class Card:
    def __init__(self, kind: str, sport: str):
        self.canvas = Canvas(BG)
        self.panel_width, self.art_size = PANELS[kind]
        self.sport = sport
        self.left = PAD_X
        self.right = WIDTH - self.panel_width - PAD_X
        self.width = self.right - self.left
        self.flow = Flow()

    # Panel ----------------------------------------------------------------
    def draw_panel(self):
        x = WIDTH - self.panel_width
        self.canvas.svg(art.panel_svg(self.sport, self.panel_width), x, 0, self.panel_width, HEIGHT)
        artwork = art.art_svg(self.sport)
        if artwork:
            size = self.art_size
            self.canvas.svg(artwork, WIDTH + 40 - size, HEIGHT + 46 - size, size, size)

    # Shared blocks ----------------------------------------------------------
    def pill(self, text: Text, x_right: float, top: float, height: float, background: str, pad: float = 20):
        width = text.width + pad * 2
        x = x_right - width
        self.canvas.rect(x, top, width, height, 14, background)
        self.canvas.text(text, x + pad, top + (height - text.height) / 2)
        return width

    def header(self, title: str, *, gold: bool = False):
        def draw(y):
            mark = logo()
            mark_width = 56 * mark.width / mark.height
            self.canvas.paste(mark.resize((round(mark_width * 2), 112), Image.LANCZOS), self.left, y)
            brand = unbounded("КапперХаб", 30, WHITE, tracking=-0.5)
            self.canvas.text(brand, self.left + mark_width + 16, y + (56 - brand.height) / 2)
            pill_text = manrope(title, 22, 800, YELLOW if gold else GREY)
            self.pill(pill_text, self.right, y + 5, 46, GOLD_PLATE if gold else PLATE)

        self.flow.add(56, draw)

    def footer(self, host: str, action: str, margin: float):
        def draw(y):
            x = self.left
            x += self.canvas.text(manrope(host, 26, 700, GREY), x, y) + 12
            x += self.canvas.text(manrope("·", 26, 700, DIM), x, y) + 12
            self.canvas.text(manrope(action, 26, 700, DIM), x, y)

        self.flow.add(manrope("·", 26, 700, DIM).height, draw, margin)

    def avatar(self, author: dict, x: float, y: float, size: float, initials_size: float):
        if author.get("avatar") is not None:
            self.canvas.circle_image(author["avatar"], x, y, size)
            return
        self.canvas.rect(x, y, size, size, size / 2, BLUE)
        initials = unbounded(author.get("initials") or "К", initials_size, WHITE)
        self.canvas.text(initials, x + (size - initials.width) / 2, y + (size - initials.height) / 2)

    def verified(self, x: float, y: float, size: float):
        self.canvas.svg(art.VERIFIED, x, y, size, size)

    def trust_badge(self, value: str, x_right: float, top: float, height: float, size: float):
        text = unbounded(value, size, BG)
        width = text.width + 32
        self.canvas.rect(x_right - width, top, width, height, 12, YELLOW)
        self.canvas.text(text, x_right - width + 16, top + (height - text.height) / 2)
        return width

    def title_lines(self, event: dict, size: float, tracking: float, max_width: float) -> list[Text]:
        """Teams on one line, or home team with the dash and the away team below, as in the mockup."""
        title = unbounded(event["title"], size, WHITE, tracking=tracking, line_height=1.1)
        if title.width <= max_width or not event.get("away"):
            return title.wrapped(max_width, 2)
        return [
            title.with_value(f"{event['home']} —").fitted(max_width),
            title.with_value(event["away"]).fitted(max_width),
        ]

    def title_block(self, lines: list[Text], meta: str, meta_size: float, gap: float, margin: float):
        meta_text = manrope(meta, meta_size, 700, GREY).fitted(self.width)
        height = sum(line.height for line in lines) + gap + meta_text.height

        def draw(y):
            for line in lines:
                self.canvas.text(line, self.left, y)
                y += line.height
            self.canvas.text(meta_text, self.left, y + gap)

        self.flow.add(height, draw, margin)

    def value_text(self, value: str, size: float, color: str, max_width: float, *, min_size: float = 34,
                   line_height: float = 1, tracking: float = -2) -> Text:
        """A big number or pick, shrunk until it fits the plate."""
        text = unbounded(value, size, color, tracking=tracking, line_height=line_height)
        while text.width > max_width and text.size > min_size:
            text = unbounded(value, text.size - 2, color, tracking=tracking, line_height=line_height)
        if text.width > max_width:
            text = text.fitted(max_width)
        # Keep the plate as tall as the mockup's even when the font got smaller.
        text.line_height = line_height * size / text.size
        return text

    def stat_plate(self, x, y, width, height, caption: str, value: Text, *, sub: Text | None = None,
                   sub_coin: bool = False, value_coin: bool = False, pad_x: float = 26, gap: float = 6):
        self.canvas.rect(x, y, width, height, 22, PLATE)
        caption_text = label(caption)
        self.canvas.text(caption_text, x + pad_x, y + 20)
        value_top = y + 20 + caption_text.height + gap
        if not value.value:
            # A value the public must not see, drawn as the mockup's skeleton bar.
            bar = value.size * 0.6
            self.canvas.rect(x + pad_x, value_top + (value.height - bar) / 2, min(150, width - pad_x * 2), bar, 10, SKELETON)
            value_coin = False
        value_width = self.canvas.text(value, x + pad_x, value_top)
        if value_coin:
            size = round(value.size * 0.78)
            self.canvas.paste(coin(size), x + pad_x + value_width + 6, value_top + (value.height - size) / 2)
        if sub is not None:
            sub_top = value_top + value.height + gap + 4
            sub_width = self.canvas.text(sub, x + pad_x, sub_top)
            if sub_coin:
                self.canvas.paste(coin(18), x + pad_x + sub_width + 6, sub_top + (sub.height - 18) / 2)

    @staticmethod
    def plate_height(value: Text, *, sub: Text | None = None, gap: float = 6) -> float:
        height = 20 + label("A").height + gap + value.height + 24
        if sub is not None:
            height += gap + 4 + sub.height
        return height

    def png(self) -> bytes:
        self.draw_panel()
        self.flow.render()
        return self.canvas.png()


# Coupon cards ------------------------------------------------------------------------------

def coupon_card(data: dict) -> bytes:
    events = data["events"]
    if data["state"] in RESULTS:
        return _result_card(data)
    if data.get("locked"):
        return _paid_card(data)
    if len(events) > 1:
        return _express_card(data)
    return _single_card(data)


def _event_word(count: int) -> str:
    return plural_ru(count, "событие", "события", "событий")


def _author_row(card: Card, author: dict, margin: float):
    name = manrope(author["name"], 32, 800, WHITE)
    sub = manrope("проверенный каппер" if author.get("verified") else f"@{author['username']}", 24, 700, DIM)
    height = max(76, name.height + 6 + sub.height, 56)

    def draw(y):
        card.avatar(author, card.left, y + (height - 76) / 2, 76, 28)
        badge_width = card.trust_badge(author["trust"], card.right, y + (height - 56) / 2, 56, 30) if author.get("trust") else 0
        x = card.left + 76 + 18
        name_room = card.right - badge_width - 24 - x - (38 if author.get("verified") else 0)
        block_top = y + (height - (name.height + 6 + sub.height)) / 2
        name_width = card.canvas.text(name.fitted(name_room), x, block_top)
        if author.get("verified"):
            card.verified(x + name_width + 10, block_top + (name.height - 28) / 2, 28)
        card.canvas.text(sub.fitted(name_room), x, block_top + name.height + 6)

    card.flow.add(height, draw, margin)


def _single_card(data: dict) -> bytes:
    event = data["events"][0]
    card = Card("single", event["sport"])
    card.header("ПРОГНОЗ")
    _author_row(card, data["author"], 36)
    card.title_block(card.title_lines(event, 46, -1.5, card.width), _join(event["league"], event["when"]), 28, 12, 34)
    card.flow.spacer()

    coefficient = card.value_text(data["coefficient"], 84, YELLOW, 300 - 52)
    pick_room = card.width - 300 - 16 - 52
    pick = card.value_text(event["pick"], 84, WHITE, pick_room)
    pick_width = max(230, pick.width + 52)
    height = card.plate_height(coefficient)

    def draw(y):
        card.stat_plate(card.left, y, pick_width, height, "ИСХОД", pick)
        card.stat_plate(card.left + pick_width + 16, y, 300, height, "КОЭФФИЦИЕНТ", coefficient)

    card.flow.add(height, draw)
    card.footer(data["host"], "смотреть прогноз →", 26)
    return card.png()


def _express_card(data: dict) -> bytes:
    events = data["events"]
    card = Card("coupon", data["sport"])
    card.header(f"ЭКСПРЕСС · {len(events)} {_event_word(len(events)).upper()}")
    shown = events[:3]

    def draw_rows(y):
        for index, event in enumerate(shown):
            row_top = y + index * 76
            mid = row_top + 38
            card.canvas.rect(card.left, mid - 22, 44, 44, 14, art.SPORTS.get(event["sport"], art.SPORTS["x"])[0])
            card.canvas.svg(art.glyph_svg(event["sport"]), card.left + 11, mid - 11, 22, 22)
            coefficient = unbounded(event["coefficient"], 30, YELLOW)
            pick = manrope(event["pick"], 26, 800, GREY).fitted(220)
            card.canvas.text(coefficient, card.right - coefficient.width, mid - coefficient.height / 2)
            pick_x = card.right - 110 - 16 - pick.width
            card.canvas.text(pick, pick_x, mid - pick.height / 2)
            name = manrope(event["title"], 28, 800, WHITE).fitted(pick_x - 16 - (card.left + 60))
            card.canvas.text(name, card.left + 60, mid - name.height / 2)
            if index < len(shown) - 1:
                card.canvas.rect(card.left, row_top + 74, card.width, 2, 0, LINE)

    card.flow.add(76 * len(shown), draw_rows, 26)
    if len(events) > len(shown):
        more = len(events) - len(shown)
        more_text = manrope(f"+{more} {_event_word(more)}", 26, 800, DIM)
        card.flow.add(more_text.height, lambda y: card.canvas.text(more_text, card.left, y), 14)
    card.flow.spacer()

    coefficient = card.value_text(data["coefficient"], 84, YELLOW, 420 - 52)
    total_height = card.plate_height(coefficient)
    author = data["author"]
    name = manrope(author["name"], 30, 800, WHITE)
    author_height = 20 + label("A").height + 6 + name.height + 24

    def draw_totals(y):
        card.stat_plate(card.left, y, 420, total_height, "ИТОГОВЫЙ КОЭФФИЦИЕНТ", coefficient)
        x = card.left + 420 + 16
        width = card.right - x
        top = y + total_height - author_height
        card.canvas.rect(x, top, width, author_height, 22, PLATE)
        card.canvas.text(label("АВТОР"), x + 26, top + 20)
        name_top = top + 20 + label("A").height + 6
        room = width - 52 - (34 if author.get("verified") else 0)
        name_width = card.canvas.text(name.fitted(room), x + 26, name_top)
        if author.get("verified"):
            card.verified(x + 26 + name_width + 10, name_top + (name.height - 24) / 2, 24)

    card.flow.add(total_height, draw_totals)
    card.footer(data["host"], "смотреть купон →", 26)
    return card.png()


def _result_card(data: dict) -> bytes:
    events = data["events"]
    express = len(events) > 1
    title_text, badge_bg, badge_line, badge_color, money_caption, money_color = RESULTS[data["state"]]
    card = Card("coupon", data["sport"])
    card.header("РЕЗУЛЬТАТ")

    badge = unbounded(title_text, 40, badge_color, tracking=-0.5)

    def draw_badge(y):
        card.canvas.rect(card.left, y, badge.width + 56, 76, 20, badge_bg, outline=badge_line, outline_width=2)
        card.canvas.text(badge, card.left + 28, y + (76 - badge.height) / 2)

    card.flow.add(76, draw_badge, 32)

    author_name = data["author"]["name"]
    if express:
        lines = [unbounded(f"Экспресс · {len(events)} {_event_word(len(events))}", 40, WHITE, tracking=-1.2, line_height=1.1)]
        meta = author_name
    else:
        event = events[0]
        lines = card.title_lines(event, 40, -1.2, card.width)
        meta = _join(event["league"], "" if data.get("locked") else event["pick"], author_name)
    card.title_block(lines, meta, 26, 10, 28)
    card.flow.spacer()

    first_caption, first_value = ("СОБЫТИЙ", str(len(events))) if express else ("СЧЁТ", events[0]["score"] or "— : —")
    first = card.value_text(first_value, 56, WHITE, 260)
    first_width = max(196, first.width + 52)
    coefficient = card.value_text(data["coefficient"], 56, YELLOW, 226 - 52)
    money_x = card.left + first_width + 16 + 226 + 16
    money_room = card.right - money_x - 52 - 46
    money = card.value_text(data["result_amount"], 50, money_color, money_room)
    sub_value = {"win": f"при ставке {data['stake']}", "lose": f"ставка {data['stake']}", "refund": "ставка возвращена"}[data["state"]]
    if data.get("locked"):
        sub_value = "платный прогноз"
    sub = manrope(sub_value, 22, 700, DIM)
    height = max(card.plate_height(first), card.plate_height(money, sub=sub))

    def draw_stats(y):
        card.stat_plate(card.left, y, first_width, height, first_caption, first)
        card.stat_plate(card.left + first_width + 16, y, 226, height, "КОЭФФИЦИЕНТ", coefficient)
        card.stat_plate(money_x, y, card.right - money_x, height, money_caption, money, sub=sub,
                        value_coin=True, sub_coin=data["state"] != "refund" and not data.get("locked"))

    card.flow.add(height, draw_stats)
    card.footer(data["host"], "смотреть прогноз →", 24)
    return card.png()


def _paid_card(data: dict) -> bytes:
    events = data["events"]
    card = Card("coupon", data["sport"])
    card.header("ПЛАТНЫЙ ПРОГНОЗ", gold=True)
    author_name = data["author"]["name"]
    if len(events) > 1:
        lines = [unbounded(f"Экспресс · {len(events)} {_event_word(len(events))}", 42, WHITE, tracking=-1.2, line_height=1.1)]
        meta = _join(events[0]["when"], author_name)
    else:
        event = events[0]
        lines = card.title_lines(event, 42, -1.2, card.width)
        meta = _join(event["league"], event["when"], author_name)
    card.title_block(lines, meta, 26, 10, 30)

    hidden = manrope("исход скрыт", 24, 800, DIM)

    def draw_lock(y):
        card.canvas.rect(card.left, y, card.width, 114, 22, PLATE)
        card.canvas.svg(art.LOCK, card.left + 28, y + 35, 44, 44)
        bars_x = card.left + 28 + 44 + 22
        card.canvas.rect(bars_x, y + 24, min(360, card.width - 300), 30, 10, SKELETON)
        card.canvas.rect(bars_x, y + 24 + 42, min(250, card.width - 410), 24, 10, SKELETON)
        card.canvas.text(hidden, card.right - 28 - hidden.width, y + (114 - hidden.height) / 2)

    card.flow.add(114, draw_lock, 26)
    card.flow.spacer()

    coefficient = card.value_text(data["coefficient"], 72, YELLOW, 300 - 52)
    text_x = card.left + 300 + 16
    text_room = card.right - text_x - 52
    offer = manrope(data.get("offer") or "Прогноз доступен по подписке", 28, 800, WHITE).wrapped(text_room, 2)
    price = unbounded(data["price"], 34, YELLOW).fitted(text_room) if data.get("price") else None
    offer_height = sum(line.height for line in offer) + (8 + price.height if price else 0)
    height = max(card.plate_height(coefficient), offer_height + 44)

    def draw_offer(y):
        card.stat_plate(card.left, y, 300, height, "КОЭФФИЦИЕНТ", coefficient)
        card.canvas.rect(text_x, y, card.right - text_x, height, 22, PLATE)
        top = y + (height - offer_height) / 2
        for line in offer:
            card.canvas.text(line, text_x + 26, top)
            top += line.height
        if price:
            card.canvas.text(price, text_x + 26, top + 8)

    card.flow.add(height, draw_offer)
    card.footer(data["host"], "открыть доступ →", 26)
    return card.png()


# Profile cards ---------------------------------------------------------------------------

def profile_card(data: dict) -> bytes:
    if data.get("newbie"):
        return _newbie_card(data)
    return _profile_card(data)


def _profile_card(data: dict) -> bytes:
    author = data["author"]
    card = Card("profile", data["sport"])
    leader = data.get("leader_label")
    card.header(leader or "ПРОФИЛЬ КАППЕРА", gold=bool(leader))

    name = unbounded(author["name"], 40, WHITE, tracking=-1)
    username = manrope(f"@{author['username']}", 26, 700, DIM)
    row_height = max(92, name.height + 8 + username.height, 62)

    def draw_identity(y):
        card.avatar(author, card.left, y + (row_height - 92) / 2, 92, 34)
        badge_width = card.trust_badge(author["trust"], card.right, y + (row_height - 62) / 2, 62, 32) if author.get("trust") else 0
        x = card.left + 92 + 20
        room = card.right - badge_width - 20 - x - (42 if author.get("verified") else 0)
        top = y + (row_height - (name.height + 8 + username.height)) / 2
        name_width = card.canvas.text(name.fitted(room), x, top)
        if author.get("verified"):
            card.verified(x + name_width + 12, top + (name.height - 30) / 2, 30)
        card.canvas.text(username.fitted(room), x, top + name.height + 8)

    card.flow.add(row_height, draw_identity, 30)

    roi = card.value_text(data["roi"], 68, GREEN if not data["roi"].startswith(("-", "−")) else RED, 330 - 48,
                          line_height=1.1)
    roi_note = manrope(data["roi_note"], 23, 700, DIM).wrapped(330 - 48, 2) if data.get("roi_note") else []
    roi_height = 20 + label("A").height + 4 + roi.height + 24 + (4 + 6 + sum(line.height for line in roi_note) if roi_note else 0)

    def draw_stats(y):
        card.canvas.rect(card.left, y, 330, roi_height, 22, PLATE)
        card.canvas.text(label(data["roi_label"]), card.left + 24, y + 20)
        roi_top = y + 20 + label("A").height + 4
        card.canvas.text(roi, card.left + 24, roi_top)
        top = roi_top + roi.height + 4 + 6
        for line in roi_note:
            card.canvas.text(line, card.left + 24, top)
            top += line.height
        x = card.left + 330 + 16
        width = card.right - x
        row_height_each = (roi_height - 24) / 3
        for index, (caption, value, streak) in enumerate((
            ("заходит", data["hit_rate"], False),
            ("прогнозов", data["predictions"], False),
            ("серия", data["streak"], True),
        )):
            top = y + index * (row_height_each + 12)
            card.canvas.rect(x, top, width, row_height_each, 18, PLATE)
            caption_text = manrope(caption, 25, 700, GREY)
            card.canvas.text(caption_text, x + 22, top + (row_height_each - caption_text.height) / 2)
            value_text = unbounded(value, 30, "#F2A33C" if streak and data.get("streak_hot") else WHITE)
            value_x = x + width - 22 - value_text.width
            card.canvas.text(value_text, value_x, top + (row_height_each - value_text.height) / 2)
            if streak and data.get("streak_hot"):
                card.canvas.svg(art.FLAME, value_x - 8 - 26, top + (row_height_each - 26) / 2, 26, 26)

    card.flow.add(roi_height, draw_stats, 30)

    results = data.get("recent") or []
    sports = manrope(data.get("sports") or "", 23, 800, GREY)

    def draw_recent(y):
        x = card.left
        colors = {"win": GREEN, "lose": RED, "refund": "#3A3E4A"}
        for state in results:
            card.canvas.rect(x, y + 14, 25.8, 18, 6, colors.get(state, "#3A3E4A"))
            x += 25.8 + 8
        if results:
            caption = manrope(f"последние {len(results)}", 23, 700, DIM)
            card.canvas.text(caption, x - 8 + 20, y + (46 - caption.height) / 2)
        if sports.value:
            card.pill(sports, card.right, y, 46, PLATE)

    card.flow.add(46, draw_recent, 26)
    card.flow.spacer()
    card.footer(data["host"], "смотреть профиль →", 0)
    return card.png()


def _newbie_card(data: dict) -> bytes:
    author = data["author"]
    card = Card("newbie", data["sport"])
    card.header("ПРОФИЛЬ КАППЕРА")

    name_lines = unbounded(author["name"], 38, WHITE, tracking=-1, line_height=1.15).wrapped(card.width - 92 - 22, 2)
    username = manrope(f"@{author['username']}", 26, 700, DIM)
    name_height = sum(line.height for line in name_lines)
    row_height = max(92, name_height + 8 + username.height)

    def draw_identity(y):
        card.avatar(author, card.left, y + (row_height - 92) / 2, 92, 34)
        x = card.left + 92 + 22
        top = y + (row_height - (name_height + 8 + username.height)) / 2
        for line in name_lines:
            card.canvas.text(line, x, top)
            top += line.height
        card.canvas.text(username.fitted(card.right - x), x, top + 8)

    card.flow.add(row_height, draw_identity, 40)
    card.flow.spacer()

    chip = unbounded("Новый каппер", 26, WHITE)
    count = manrope(data["predictions_label"], 28, 800, WHITE)
    # The box row has an empty flexible gap between the count and the note, so three gaps of 22.
    note_room = card.width - 60 - (chip.width + 44) - count.width - 22 * 3
    note = [
        line
        for part in ("статистика", "после 10 прогнозов")
        for line in manrope(part, 24, 700, DIM).wrapped(note_room, 2)
    ]
    box_height = 26 + max(60, count.height, sum(line.height for line in note)) + 26

    def draw_box(y):
        card.canvas.rect(card.left, y, card.width, box_height, 22, PLATE)
        mid = y + box_height / 2
        chip_width = chip.width + 44
        card.canvas.rect(card.left + 30, mid - 30, chip_width, 60, 16, BLUE)
        card.canvas.text(chip, card.left + 30 + 22, mid - chip.height / 2)
        card.canvas.text(count, card.left + 30 + chip_width + 22, mid - count.height / 2)
        top = mid - sum(line.height for line in note) / 2
        for line in note:
            card.canvas.text(line, card.right - 30 - line.width, top)
            top += line.height

    card.flow.add(box_height, draw_box)

    chips = [manrope(sport, 24, 800, GREY) for sport in data.get("sport_names") or []]
    if chips:
        def draw_chips(y):
            x = card.left
            for item in chips:
                width = item.width + 40
                if x + width > card.right:
                    break
                card.canvas.rect(x, y, width, 48, 14, PLATE)
                card.canvas.text(item, x + 20, y + (48 - item.height) / 2)
                x += width + 14

        card.flow.add(48, draw_chips, 20)
    card.footer(data["host"], "смотреть профиль →", 20)
    return card.png()


def _join(*parts: str) -> str:
    return " · ".join(part for part in parts if part)
