from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text()
    if old not in text:
        raise SystemExit(f"Expected text not found in {path}: {old[:160]!r}")
    file_path.write_text(text.replace(old, new, 1))


# front/prediction_views.py: source all reaction counters from persisted metrics.
replace_once(
    "front/prediction_views.py",
    '''from django.http import Http404, HttpResponsePermanentRedirect, JsonResponse\n''',
    '''from django.db.models.functions import Coalesce\nfrom django.http import Http404, HttpResponsePermanentRedirect, JsonResponse\n''',
)
replace_once(
    "front/prediction_views.py",
    '''from .expert_ranking import ranked_expert_profiles\nfrom .models import PredictionFavorite, PredictionLike\n''',
    '''from .expert_ranking import ranked_expert_profiles\nfrom .metrics import (\n    increment_prediction_views,\n    toggle_prediction_favorite_metric,\n    toggle_prediction_like_metric,\n)\nfrom .models import PredictionFavorite, PredictionLike\n''',
)
replace_once(
    "front/prediction_views.py",
    '''        .select_related(\n            "author",\n            "author__analyst_profile",\n            "cover_image",\n        )\n''',
    '''        .select_related(\n            "author",\n            "author__analyst_profile",\n            "cover_image",\n            "metrics",\n        )\n''',
)
replace_once(
    "front/prediction_views.py",
    '''        .annotate(\n            likes_count=Count("likes", distinct=True),\n            favorites_count=Count("favorites", distinct=True),\n            positions_count=Count("predictions", distinct=True),\n            combined_coefficient=_combined_coefficient_expression(),\n        )\n''',
    '''        .annotate(\n            likes_count=Coalesce(\n                F("metrics__likes_count"),\n                Value(0),\n                output_field=IntegerField(),\n            ),\n            favorites_count=Coalesce(\n                F("metrics__favorites_count"),\n                Value(0),\n                output_field=IntegerField(),\n            ),\n            comments_count=Coalesce(\n                F("metrics__comments_count"),\n                Value(0),\n                output_field=IntegerField(),\n            ),\n            views_count=Coalesce(\n                F("metrics__views_count"),\n                Value(0),\n                output_field=IntegerField(),\n            ),\n            shares_count=Coalesce(\n                F("metrics__shares_count"),\n                Value(0),\n                output_field=IntegerField(),\n            ),\n            positions_count=Count("predictions", distinct=True),\n            combined_coefficient=_combined_coefficient_expression(),\n        )\n''',
)
replace_once(
    "front/prediction_views.py",
    '''        likes_count=getattr(coupon, "likes_count", 0),\n        favorites_count=getattr(coupon, "favorites_count", 0),\n        followers_count=0,\n''',
    '''        likes_count=getattr(coupon, "likes_count", 0),\n        favorites_count=getattr(coupon, "favorites_count", 0),\n        comments_count=getattr(coupon, "comments_count", 0),\n        views_count=getattr(coupon, "views_count", 0),\n        shares_count=getattr(coupon, "shares_count", 0),\n        followers_count=0,\n''',
)
replace_once(
    "front/prediction_views.py",
    '''        .select_related("author", "author__analyst_profile")\n''',
    '''        .select_related("author", "author__analyst_profile", "metrics")\n''',
)
replace_once(
    "front/prediction_views.py",
    '''        .annotate(\n            likes_count=Count("likes", distinct=True),\n            favorites_count=Count("favorites", distinct=True),\n        ),\n''',
    '''        .annotate(\n            likes_count=Coalesce(\n                F("metrics__likes_count"),\n                Value(0),\n                output_field=IntegerField(),\n            ),\n            favorites_count=Coalesce(\n                F("metrics__favorites_count"),\n                Value(0),\n                output_field=IntegerField(),\n            ),\n            comments_count=Coalesce(\n                F("metrics__comments_count"),\n                Value(0),\n                output_field=IntegerField(),\n            ),\n            views_count=Coalesce(\n                F("metrics__views_count"),\n                Value(0),\n                output_field=IntegerField(),\n            ),\n            shares_count=Coalesce(\n                F("metrics__shares_count"),\n                Value(0),\n                output_field=IntegerField(),\n            ),\n        ),\n''',
)
replace_once(
    "front/prediction_views.py",
    '''    if (\n        coupon.audience == PredictionCoupon.Audience.PAID\n        and not user_can_view_paid_predictions(request.user, coupon.author)\n    ):\n        raise Http404("Прогноз не найден.")\n    positions = list(getattr(coupon, "detail_positions", []) or [])\n''',
    '''    if (\n        coupon.audience == PredictionCoupon.Audience.PAID\n        and not user_can_view_paid_predictions(request.user, coupon.author)\n    ):\n        raise Http404("Прогноз не найден.")\n\n    metrics = increment_prediction_views(coupon.pk)\n    coupon.likes_count = metrics.likes_count\n    coupon.favorites_count = metrics.favorites_count\n    coupon.comments_count = metrics.comments_count\n    coupon.views_count = metrics.views_count\n    coupon.shares_count = metrics.shares_count\n    positions = list(getattr(coupon, "detail_positions", []) or [])\n''',
)
replace_once(
    "front/prediction_views.py",
    '''    reaction, created = PredictionLike.objects.get_or_create(\n        prediction=prediction,\n        user=request.user,\n    )\n    active = created\n    if not created:\n        reaction.delete()\n        active = False\n\n    return JsonResponse(\n        {\n            "ok": True,\n            "active": active,\n            "count": PredictionLike.objects.filter(prediction=prediction).count(),\n        }\n    )\n''',
    '''    active, metrics = toggle_prediction_like_metric(prediction, request.user)\n    return JsonResponse(\n        {\n            "ok": True,\n            "active": active,\n            "count": metrics.likes_count,\n        }\n    )\n''',
)
replace_once(
    "front/prediction_views.py",
    '''    favorite, created = PredictionFavorite.objects.get_or_create(\n        prediction=prediction,\n        user=request.user,\n    )\n    active = created\n    if not created:\n        favorite.delete()\n        active = False\n\n    return JsonResponse({"ok": True, "active": active})\n''',
    '''    active, metrics = toggle_prediction_favorite_metric(prediction, request.user)\n    return JsonResponse(\n        {\n            "ok": True,\n            "active": active,\n            "count": metrics.favorites_count,\n        }\n    )\n''',
)

# front/home_views.py: important-match cards read Prediction count from MatchMetrics.
replace_once(
    "front/home_views.py",
    '''    F,\n    Prefetch,\n''',
    '''    F,\n    IntegerField,\n    Prefetch,\n''',
)
replace_once(
    "front/home_views.py",
    '''from django.shortcuts import render\n''',
    '''from django.db.models.functions import Coalesce\nfrom django.shortcuts import render\n''',
)
replace_once(
    "front/home_views.py",
    '''            "away_team__country",\n            "odds",\n        )\n        .annotate(\n            predictions_count=Count(\n                "predictions__coupon",\n                filter=Q(\n                    predictions__coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,\n                    predictions__coupon__audience=PredictionCoupon.Audience.FREE,\n                ),\n                distinct=True,\n            )\n        )\n''',
    '''            "away_team__country",\n            "odds",\n            "metrics",\n        )\n        .annotate(\n            predictions_count=Coalesce(\n                F("metrics__predictions_count"),\n                Value(0),\n                output_field=IntegerField(),\n            )\n        )\n''',
)
