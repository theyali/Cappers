"""Drawing primitives for the cards: CSS-like text boxes, rounded plates and pasted SVG.

Everything is drawn at SCALE times the 1200x630 card and shrunk at the end, which smooths the
edges of shapes that Pillow draws without anti-aliasing.
"""

from functools import lru_cache
from io import BytesIO
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw, ImageFont, features

WIDTH, HEIGHT = 1200, 630
SCALE = 2

FONT_DIR = Path(__file__).resolve().parent / "fonts"
# File, ascender and descender as share of the em (hhea), as the browser uses them for line boxes.
FONTS = {
    "manrope": ("Manrope-Variable.ttf", 1.066, 0.3),
    "unbounded": ("Unbounded-Variable.ttf", 0.995, 0.245),
}
LAYOUT = ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC


@lru_cache(maxsize=128)
def font(family: str, size: float, weight: int) -> ImageFont.FreeTypeFont:
    file_name = FONTS[family][0]
    face = ImageFont.truetype(str(FONT_DIR / file_name), round(size * SCALE), layout_engine=LAYOUT)
    face.set_variation_by_axes([weight])
    return face


def line_box(family: str, size: float, line_height: float | None = None) -> tuple[float, float]:
    """Height of one line and the baseline offset inside it, like a browser's line box."""
    _file, ascender, descender = FONTS[family]
    ascent, descent = round(ascender * size), round(descender * size)
    height = ascent + descent if line_height is None else line_height * size
    return height, (height - ascent - descent) / 2 + ascent


class Text:
    """A run of text in one style; widths include letter-spacing after every glyph, as in CSS."""

    def __init__(self, value: str, family: str, size: float, weight: int, color: str, *,
                 tracking: float = 0.0, line_height: float | None = None):
        self.value = value
        self.family = family
        self.size = size
        self.weight = weight
        self.color = color
        self.tracking = tracking
        self.line_height = line_height

    @property
    def face(self):
        return font(self.family, self.size, self.weight)

    def width_of(self, value: str) -> float:
        return self.face.getlength(value) / SCALE + self.tracking * len(value)

    @property
    def width(self) -> float:
        return self.width_of(self.value)

    @property
    def height(self) -> float:
        return line_box(self.family, self.size, self.line_height)[0]

    @property
    def baseline(self) -> float:
        return line_box(self.family, self.size, self.line_height)[1]

    def with_value(self, value: str) -> "Text":
        return Text(value, self.family, self.size, self.weight, self.color,
                    tracking=self.tracking, line_height=self.line_height)

    def fitted(self, max_width: float) -> "Text":
        """Cut with an ellipsis so the text fits max_width."""
        if self.width <= max_width:
            return self
        value = self.value
        while value and self.width_of(value.rstrip() + "…") > max_width:
            value = value[:-1]
        return self.with_value(value.rstrip() + "…")

    def wrapped(self, max_width: float, max_lines: int) -> list["Text"]:
        """Break on spaces like a browser; past max_lines the last line ends with an ellipsis (line-clamp)."""
        lines: list[str] = []
        current = ""
        for word in self.value.split():
            candidate = f"{current} {word}".strip()
            if not current or self.width_of(candidate) <= max_width:
                current = candidate
                continue
            lines.append(current)
            current = word
        if current:
            lines.append(current)
        result = [self.with_value(line).fitted(max_width) for line in lines[:max_lines]]
        if len(lines) > max_lines:
            last = result[-1].value.rstrip("…")
            result[-1] = self.with_value(last + "…")
            if result[-1].width > max_width:
                result[-1] = self.with_value(last).fitted(max_width)
        return result


def svg_image(svg: str | bytes, width: float, height: float) -> Image.Image:
    data = svg.encode() if isinstance(svg, str) else svg
    png = cairosvg.svg2png(bytestring=data, output_width=round(width * SCALE), output_height=round(height * SCALE))
    return Image.open(BytesIO(png)).convert("RGBA")


def hex_rgba(color: str) -> tuple[int, int, int, int]:
    value = color.lstrip("#")
    if len(value) == 6:
        value += "ff"
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4, 6))


class Canvas:
    def __init__(self, background: str):
        self.image = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), background)
        self.draw = ImageDraw.Draw(self.image)

    @staticmethod
    def _box(x, y, width, height):
        return [round(x * SCALE), round(y * SCALE), round((x + width) * SCALE) - 1, round((y + height) * SCALE) - 1]

    def rect(self, x, y, width, height, radius, fill, *, outline=None, outline_width=0):
        """A rounded plate; colours with alpha are blended over what is already drawn."""
        left, top, right, bottom = self._box(x, y, width, height)
        layer = Image.new("RGBA", (right - left + 1, bottom - top + 1), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        box = [0, 0, right - left, bottom - top]
        if fill:
            draw.rounded_rectangle(box, radius=radius * SCALE, fill=hex_rgba(fill))
        if outline:
            draw.rounded_rectangle(box, radius=radius * SCALE, outline=hex_rgba(outline),
                                   width=round(outline_width * SCALE))
        self.image.paste(layer, (left, top), layer)

    def text(self, item: Text, x: float, top: float) -> float:
        """Draw a line whose line box starts at top; returns its width."""
        face = item.face
        baseline = (top + item.baseline) * SCALE
        if not item.tracking:
            self.draw.text((x * SCALE, baseline), item.value, font=face, fill=item.color, anchor="ls")
        else:
            for index, char in enumerate(item.value):
                offset = face.getlength(item.value[:index]) + index * item.tracking * SCALE
                self.draw.text((x * SCALE + offset, baseline), char, font=face, fill=item.color, anchor="ls")
        return item.width

    def paste(self, image: Image.Image, x: float, y: float):
        self.image.paste(image, (round(x * SCALE), round(y * SCALE)), image)

    def svg(self, svg: str | bytes, x: float, y: float, width: float, height: float):
        self.paste(svg_image(svg, width, height), x, y)

    def circle_image(self, source: Image.Image, x: float, y: float, size: float):
        """A picture cropped to a circle, e.g. an avatar."""
        pixels = round(size * SCALE)
        picture = source.convert("RGBA")
        side = min(picture.size)
        left, top = (picture.width - side) // 2, (picture.height - side) // 2
        picture = picture.crop((left, top, left + side, top + side)).resize((pixels, pixels), Image.LANCZOS)
        mask = Image.new("L", (pixels * 4, pixels * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, pixels * 4 - 1, pixels * 4 - 1), fill=255)
        mask = mask.resize((pixels, pixels), Image.LANCZOS)
        alpha = Image.composite(picture.getchannel("A"), Image.new("L", picture.size, 0), mask)
        picture.putalpha(alpha)
        self.paste(picture, x, y)

    def png(self) -> bytes:
        output = BytesIO()
        self.image.resize((WIDTH, HEIGHT), Image.LANCZOS).save(output, format="PNG", optimize=True)
        return output.getvalue()
