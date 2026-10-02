from django.urls import reverse

from game.models import Sport


SPORT_ORDER = {
    "football": 10,
    "hockey": 20,
    "basketball": 30,
    "tennis": 40,
}
MOBILE_MATCH_SCOPE_TABS = (
    ("all", "Все"),
    ("live", "Live"),
    ("prematch", "Прематч"),
    ("finished", "Завершенные"),
)


def build_sport_filter_tabs(
    request,
    *,
    active_sport=None,
    base_url: str | None = None,
    drop_params: tuple[str, ...] = (),
) -> list[dict]:
    active_code = ""
    if isinstance(active_sport, Sport):
        active_code = active_sport.code
    elif active_sport and active_sport != "all":
        active_code = str(active_sport)

    params = request.GET.copy()
    params.pop("page", None)
    for key in drop_params:
        params.pop(key, None)

    path = base_url or request.path

    all_params = params.copy()
    all_params.pop("sport", None)
    tabs = [
        {
            "code": "",
            "label": "Все",
            "href": _url_with_query(path, all_params),
            "active": not active_code,
        }
    ]

    sports = sorted(
        Sport.objects.all(),
        key=lambda sport: (
            SPORT_ORDER.get((sport.code or "").lower(), 999),
            (sport.name_ru or sport.name or sport.code or "").lower(),
        ),
    )
    for sport in sports:
        tab_params = params.copy()
        tab_params["sport"] = sport.code
        tabs.append(
            {
                "code": sport.code,
                "label": sport.name_ru or sport.name or sport.code,
                "href": _url_with_query(path, tab_params),
                "active": active_code == sport.code,
            }
        )
    return tabs


def build_mobile_prediction_filter_tabs(
    request,
    *,
    reset_url: str | None = None,
    top_experts_tab: dict | None = None,
) -> list[dict]:
    params = request.GET.copy()
    params.pop("page", None)

    tabs = []
    for key, label in (("today", "Дата"), ("live", "Live")):
        tab_params = params.copy()
        active = tab_params.get(key) == "1"
        if active:
            tab_params.pop(key, None)
        else:
            tab_params[key] = "1"
        tabs.append(
            {
                "key": key,
                "label": label,
                "href": _url_with_query(request.path, tab_params),
                "active": active,
            }
        )

    if top_experts_tab:
        tabs.append(
            {
                "key": "top",
                "label": "Топовые эксперты",
                "href": top_experts_tab["href"],
                "active": bool(top_experts_tab.get("active")),
            }
        )

    tabs.append(
        {
            "key": "filters",
            "label": "Сбросить фильтры" if len(params) else "Фильтры",
            "href": reset_url or request.path,
            "active": bool(params),
        }
    )
    return tabs


def build_mobile_prediction_match_scope_tabs(request) -> list[dict]:
    params = request.GET.copy()
    params.pop("page", None)
    active_scope = params.get("match_scope", "all")
    valid_scopes = {key for key, _ in MOBILE_MATCH_SCOPE_TABS}
    if active_scope not in valid_scopes:
        active_scope = "all"

    tabs = []
    for key, label in MOBILE_MATCH_SCOPE_TABS:
        tab_params = params.copy()
        tab_params.pop("live", None)
        if key == "all":
            tab_params.pop("match_scope", None)
        else:
            tab_params["match_scope"] = key
        tabs.append(
            {
                "key": key,
                "label": label,
                "href": _url_with_query(request.path, tab_params),
                "active": active_scope == key,
            }
        )
    return tabs


def _url_with_query(path: str, params) -> str:
    query = params.urlencode()
    return f"{path}?{query}" if query else path
