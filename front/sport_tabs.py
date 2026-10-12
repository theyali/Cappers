from django.urls import reverse

from game.models import Sport


SPORT_ORDER = {
    "football": 10,
    "hockey": 20,
    "basketball": 30,
    "tennis": 40,
}
SPORT_TILE_KEYS = {
    "football": "f",
    "soccer": "f",
    "tennis": "t",
    "basketball": "b",
    "hockey": "h",
    "ice-hockey": "h",
    "ice_hockey": "h",
    "esports": "e",
    "cybersport": "e",
    "volleyball": "v",
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
    active_express: bool = False,
    base_url: str | None = None,
    drop_params: tuple[str, ...] = (),
    counts_by_code: dict | None = None,
    total_count: int | None = None,
    include_express: bool = False,
    express_count: int = 0,
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
    all_params.pop("express", None)
    all_href = _url_with_query(path, all_params)
    tabs = [
        {
            "code": "",
            "label": "Все",
            "count": total_count or 0,
            "href": all_href,
            "url": all_href,
            "toggle_url": all_href,
            "tile_key": "all",
            "active": not active_code and not active_express,
        }
    ]
    if include_express:
        express_params = params.copy()
        express_params.pop("sport", None)
        express_params.pop("league", None)
        express_params["express"] = "1"
        express_href = _url_with_query(path, express_params)
        tabs.append(
            {
                "code": "express",
                "label": "Экспрессы",
                "count": int(express_count or 0),
                "href": express_href,
                "url": express_href,
                "toggle_url": all_href if active_express else express_href,
                "tile_key": "x",
                "active": active_express,
            }
        )

    sports = sorted(
        Sport.objects.all(),
        key=lambda sport: (
            SPORT_ORDER.get((sport.code or "").lower(), 999),
            (sport.name_ru or sport.name or sport.code or "").lower(),
        ),
    )
    for sport in sports:
        tab_params = params.copy()
        tab_params.pop("express", None)
        tab_params["sport"] = sport.code
        href = _url_with_query(path, tab_params)
        code = sport.code or ""
        active = active_code == code
        tabs.append(
            {
                "code": code,
                "label": sport.name_ru or sport.name or code,
                "count": int((counts_by_code or {}).get(code, 0) or 0),
                "href": href,
                "url": href,
                "toggle_url": all_href if active else href,
                "tile_key": SPORT_TILE_KEYS.get(code.lower(), "x"),
                "active": active,
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
