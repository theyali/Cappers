from pathlib import Path


def replace_once(path, old, new):
    file_path = Path(path)
    text = file_path.read_text()
    if old not in text:
        raise SystemExit(f"Expected text not found in {path}: {old!r}")
    file_path.write_text(text.replace(old, new, 1))


# Tournaments: render the reusable VIP banner directly as the left grid column.
replace_once(
    "templates/tournaments/index.html",
    '''        <div class="predictions-filter-sidebar tournaments-left-sidebar">\n            <aside class="bookmakers-sidebar" aria-label="VIP прогнозисты и реклама">\n                {% vip_cappers_banner 6 %}\n            </aside>\n        </div>\n''',
    '''        {% vip_cappers_banner 6 %}\n''',
)

# Cappers table: use the same inclusion tag under the existing rating filters.
replace_once(
    "templates/front/cappers_table.html",
    '''{% load capper_trust capper_table_stats static %}''',
    '''{% load capper_trust capper_table_stats static site_extras %}''',
)
replace_once(
    "templates/front/cappers_table.html",
    '''                </nav>\n            </section>\n        </aside>\n\n        <div class="predictions-content cappers-table-page">''',
    '''                </nav>\n            </section>\n\n            {% vip_cappers_banner 6 %}\n        </aside>\n\n        <div class="predictions-content cappers-table-page">''',
)

# Favorites: keep the right-column container for VIP + ads, but drop the legacy
# bookmakers-sidebar styling hook around the new banner.
replace_once(
    "templates/front/favorites.html",
    '''        <aside class="bookmakers-sidebar favorites-right-sidebar" aria-label="VIP прогнозисты и реклама">''',
    '''        <aside class="favorites-right-sidebar" aria-label="VIP прогнозисты и реклама">''',
)

# Sanity checks: one shared tag per target page and no legacy tournaments wrapper.
for path in (
    "templates/tournaments/index.html",
    "templates/front/cappers_table.html",
    "templates/front/favorites.html",
):
    text = Path(path).read_text()
    if text.count("{% vip_cappers_banner 6 %}") != 1:
        raise SystemExit(f"Unexpected VIP banner tag count in {path}")

if "predictions-filter-sidebar tournaments-left-sidebar" in Path("templates/tournaments/index.html").read_text():
    raise SystemExit("Legacy tournaments left wrapper still exists")
if "bookmakers-sidebar favorites-right-sidebar" in Path("templates/front/favorites.html").read_text():
    raise SystemExit("Legacy favorites VIP sidebar wrapper still exists")

# Remove the one-shot helper and workflow from the resulting project tree.
Path(".github/step4_vip_apply.py").unlink()
Path(".github/workflows/step4-vip.yml").unlink()
