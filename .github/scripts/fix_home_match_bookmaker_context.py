from pathlib import Path

index = Path("templates/front/index.html")
text = index.read_text(encoding="utf-8")
old = '{% include "game/_home_match_card.html" with match=match request=request only %}'
new = '{% include "game/_home_match_card.html" with match=match request=request website_settings=website_settings only %}'
if old not in text:
    raise SystemExit("home match include marker not found")
index.write_text(text.replace(old, new, 1), encoding="utf-8")

home_card = Path("templates/game/_home_match_card.html")
text = home_card.read_text(encoding="utf-8")
old = '{% include "game/includes/_match_card.html" with match=match request=request can_write_coupon=1 card_home=1 only %}'
new = '{% include "game/includes/_match_card.html" with match=match request=request website_settings=website_settings can_write_coupon=1 card_home=1 only %}'
if old not in text:
    raise SystemExit("nested home match include marker not found")
home_card.write_text(text.replace(old, new, 1), encoding="utf-8")

assert "website_settings=website_settings" in index.read_text(encoding="utf-8")
assert "website_settings=website_settings" in home_card.read_text(encoding="utf-8")
