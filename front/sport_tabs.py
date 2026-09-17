from django.urls import reverse

from game.models import Sport


SPORT_ORDER = {
    "football": 10,
    "hockey": 20,
    "basketball": 30,
    "tennis": 40,
}


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


def _url_with_query(path: str, params) -> str:
    query = params.urlencode()
    return f"{path}?{query}" if query else path
