from pathlib import Path
import re

ROOT = Path('.')
MAIN = ROOT / 'front/static/front/css/main.css'
MOBILE = ROOT / 'front/static/front/css/mobile.css'
TOURNAMENTS = ROOT / 'templates/tournaments/index.html'
CAPPERS = ROOT / 'templates/front/cappers_table.html'
FAVORITES = ROOT / 'templates/front/favorites.html'
VIP_SOURCE = ROOT / 'front/vip_cappers.py'
VIP_TEMPLATE = ROOT / 'templates/front/banners/vip_cappers.html'
OLD_TEMPLATE = ROOT / 'templates/front/includes/_vip_experts_sidebar.html'
WORKFLOW = ROOT / '.github/workflows/vip-step5.yml'
SELF = ROOT / '.github/vip_step5_apply.py'


def replace_once(path: Path, old: str, new: str):
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'Expected text not found in {path}: {old!r}')
    path.write_text(text.replace(old, new, 1))


def append_script_block(path: Path):
    text = path.read_text()
    script = "<script src=\"{% static 'front/js/expert-follow.js' %}\" defer></script>"
    if script in text:
        return
    text = text.rstrip() + f'\n\n{{% block extra_js %}}\n{script}\n{{% endblock %}}\n'
    path.write_text(text)


# The CTA is now a real button for authenticated users; normalize native button styles.
replace_once(
    MAIN,
    '''    padding: 11px 14px;\n    color: var(--ink);\n    background: var(--yellow);\n    font-size: 14px;\n    font-weight: 600;\n''',
    '''    padding: 11px 14px;\n    border: 0;\n    color: var(--ink);\n    background: var(--yellow);\n    font: inherit;\n    font-size: 14px;\n    font-weight: 600;\n    cursor: pointer;\n''',
)

subscribe_anchor = '''.vip-cappers-banner__subscribe:hover,\n.vip-cappers-banner__subscribe:focus-visible {\n    color: var(--ink);\n    background: var(--yellow);\n}\n'''
subscribe_states = subscribe_anchor + '''\n.vip-cappers-banner__subscribe.is-active {\n    color: #fff;\n    background: var(--blue);\n}\n\n.vip-cappers-banner__subscribe:disabled {\n    cursor: wait;\n    opacity: .68;\n}\n'''
replace_once(MAIN, subscribe_anchor, subscribe_states)

# Reuse the existing follow service on every page where the reusable VIP banner appears.
append_script_block(TOURNAMENTS)
append_script_block(CAPPERS)

favorite_follow = "<script src=\"{% static 'front/js/expert-follow.js' %}\" defer></script>"
favorites_text = FAVORITES.read_text()
if favorite_follow not in favorites_text:
    replace_once(
        FAVORITES,
        "<script src=\"{% static 'front/js/prediction-follow.js' %}\" defer></script>",
        favorite_follow + "\n<script src=\"{% static 'front/js/prediction-follow.js' %}\" defer></script>",
    )

# Static audit for step 5.
legacy_tokens = (
    'vip-experts-panel',
    'vip-experts-list',
    'vip-expert-card',
    'vip-expert-record',
    'vip-expert-roi',
    'vip_experts_sidebar',
    '_vip_experts_sidebar.html',
)
for path in (MAIN, MOBILE, TOURNAMENTS, CAPPERS, FAVORITES, VIP_TEMPLATE):
    text = path.read_text()
    leftovers = [token for token in legacy_tokens if token in text]
    if leftovers:
        raise SystemExit(f'Legacy VIP tokens remain in {path}: {leftovers}')

if OLD_TEMPLATE.exists():
    raise SystemExit('Legacy VIP sidebar template still exists')

for path in (TOURNAMENTS, CAPPERS, FAVORITES):
    text = path.read_text()
    if text.count('{% vip_cappers_banner 6 %}') != 1:
        raise SystemExit(f'{path} must contain exactly one VIP banner call')
    if "front/js/expert-follow.js" not in text:
        raise SystemExit(f'{path} does not load the existing expert follow handler')

if 'predictions-filter-sidebar tournaments-left-sidebar' in TOURNAMENTS.read_text():
    raise SystemExit('Old tournaments VIP wrapper still exists')
if '<aside class="bookmakers-sidebar favorites-right-sidebar"' in FAVORITES.read_text():
    raise SystemExit('Old favorites bookmakers wrapper still exists')

source = VIP_SOURCE.read_text()
for required in (
    '.select_related("user")',
    'followers_count=Count(',
    'wins_count=Count(',
    'losses_count=Count(',
    'is_following=Exists(',
    'list(queryset.order_by("-vip_sort_at", "-id")[:safe_limit])',
):
    if required not in source:
        raise SystemExit(f'VIP queryset audit failed, missing: {required}')
if 'annotate_author_roi' in source:
    raise SystemExit('Unused ROI subquery still exists in VIP banner source')

# Verify banner typography and visual restrictions in the scoped CSS only.
main_text = MAIN.read_text()
main_marker = '/* VIP cappers banner */'
if main_marker not in main_text:
    raise SystemExit('VIP banner CSS marker missing')
scoped_css = main_text.split(main_marker, 1)[1]
mobile_text = MOBILE.read_text()
mobile_marker = '/* VIP cappers banner responsive */'
if mobile_marker not in mobile_text:
    raise SystemExit('VIP mobile CSS marker missing')
scoped_css += '\n' + mobile_text.split(mobile_marker, 1)[1]

for value in re.findall(r'font-size:\s*(\d+)px', scoped_css):
    if int(value) > 17:
        raise SystemExit(f'VIP banner font-size exceeds 17px: {value}px')
for value in re.findall(r'font-weight:\s*(\d+)', scoped_css):
    if int(value) > 600:
        raise SystemExit(f'VIP banner font-weight exceeds 600: {value}')
if 'gradient(' in scoped_css:
    raise SystemExit('Gradient found in VIP banner scoped CSS')

# The old weekly-list mechanic must not survive in the reusable banner.
if 'Рейтинг недели' in VIP_TEMPLATE.read_text():
    raise SystemExit('Old weekly ranking label still exists in VIP banner')
if 'href="{{ vip_main.profile_url }}"' not in VIP_TEMPLATE.read_text():
    raise SystemExit('Main VIP profile link is missing')
if 'href="{{ vip_ranking_url }}"' not in VIP_TEMPLATE.read_text():
    raise SystemExit('VIP ranking link is missing')

# Remove one-shot helper files from the resulting project commit.
SELF.unlink(missing_ok=True)
WORKFLOW.unlink(missing_ok=True)
