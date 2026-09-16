from pathlib import Path

path = Path("front/static/front/css/mobile.css")
text = path.read_text()
start_marker = "/* VIP experts sidebar */"
end_marker = "/* Match prediction feed heading/count */"

if start_marker not in text:
    raise SystemExit("Legacy VIP experts CSS block was not found")
if end_marker not in text:
    raise SystemExit("CSS end marker was not found")

before, tail = text.split(start_marker, 1)
_, after = tail.split(end_marker, 1)
cleaned = before.rstrip() + "\n\n" + end_marker + after

legacy_tokens = (
    ".vip-experts-panel",
    ".vip-experts-list",
    ".vip-expert-card",
    ".vip-expert-record",
    ".vip-expert-roi",
)
if any(token in cleaned for token in legacy_tokens):
    raise SystemExit("Legacy VIP experts selectors still remain after cleanup")

path.write_text(cleaned)
