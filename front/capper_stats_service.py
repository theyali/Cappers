from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Prefetch, Q
from django.utils import timezone

from cabinet.achievements import build_achievement_badges
from cabinet.models import AnalystFollow
from game.models import Prediction, PredictionCoupon

from .expert_ranking import ranked_expert_profiles
from .prediction_metrics import ROI_PERIOD_DAYS


NEW_CAPPERS_LIMIT = 12
RISING_STARS_LIMIT = 12
POPULAR_CAPPERS_LIMIT = 12
ACTIVE_CAPPERS_LIMIT = 12
RISING_WINDOW_DAYS = 180
NEW_WINDOW_DAYS = 30
SETTLED_COUPON_STATES = {
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
    PredictionCoupon.StateStatus.REFUND,
}
MARKET_LABELS = {
    "winner": "Исход матча",
    "total": "Тотал",
    "handicap": "Фора",
    "both_score": "Обе забьют",
    "double_chance": "Двойной шанс",
    "first_half_winner": "Исход 1-го тайма",
    "first_half_total": "Тотал 1-го тайма",
    "first_half_handicap": "Фора 1-го тайма",
    "team_total": "Индивидуальный тотал",
    "exact_score": "Точный счет",
}


def _initials(name: str) -> str:
    parts = [part for part in (name or "").split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "К"


def _best_streaks_for_authors(author_ids: list[int]) -> dict[int, int]:
    if not author_ids:
        return {}

    rows = (
        PredictionCoupon.objects.filter(
            author_id__in=author_ids,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status__in=[
                PredictionCoupon.StateStatus.WIN,
                PredictionCoupon.StateStatus.LOSE,
            ],
        )
        .order_by("author_id", "settled_at", "updated_at", "id")
        .values_list("author_id", "state_status")
    )

    best: dict[int, int] = {}
    current: dict[int, int] = {}
    for author_id, state in rows:
        if state == PredictionCoupon.StateStatus.WIN:
            current[author_id] = current.get(author_id, 0) + 1
            best[author_id] = max(best.get(author_id, 0), current[author_id])
        else:
            current[author_id] = 0
    return best


class CapperStatsService:
    """Single source of truth for capper statistics and discovery rules."""

    def __init__(self, user=None):
        self.user = user

    def build_catalog_context(self) -> dict:
        profiles = ranked_expert_profiles()
        profile_ids = [profile.user_id for profile in profiles]
        best_streaks = _best_streaks_for_authors(profile_ids)
        following_ids = self._following_ids(profile_ids)

        cards_by_id = {
            profile.user_id: self._serialize_profile(
                profile,
                following_ids=following_ids,
                best_streak=best_streaks.get(profile.user_id, 0),
            )
            for profile in profiles
        }
        experts = [cards_by_id[profile.user_id] for profile in profiles]

        new_profiles = self._new_profiles(profiles)
        rising_profiles = self._rising_profiles(profiles)
        popular_profiles = self._popular_profiles(profiles)
        active_profiles = self._active_profiles(profiles)

        now = timezone.now()
        new_cutoff = now - timedelta(days=NEW_WINDOW_DAYS)
        summary = {
            "experts": len(profiles),
            "verified": sum(1 for profile in profiles if profile.is_verified),
            "publications": sum(profile.publications_count for profile in profiles),
            "active_30d": sum(
                1 for profile in profiles if profile.recent_publications_count > 0
            ),
            "new_30d": sum(
                1
                for profile in profiles
                if self._joined_at(profile) >= new_cutoff
            ),
            "rising": len(rising_profiles),
        }

        return {
            "experts": experts,
            "experts_count": len(experts),
            "summary": summary,
            "roi_period_days": ROI_PERIOD_DAYS,
            "new_cappers": [cards_by_id[profile.user_id] for profile in new_profiles],
            "rising_stars": [cards_by_id[profile.user_id] for profile in rising_profiles],
            "popular_cappers": [cards_by_id[profile.user_id] for profile in popular_profiles],
            "active_cappers": [cards_by_id[profile.user_id] for profile in active_profiles],
        }

    def build_expert_profile_context(self, profile) -> dict:
        analyst = profile.user
        published = PredictionCoupon.objects.filter(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        stats = published.aggregate(
            predictions=Count("id"),
            wins=Count("id", filter=Q(state_status=PredictionCoupon.StateStatus.WIN)),
            losses=Count("id", filter=Q(state_status=PredictionCoupon.StateStatus.LOSE)),
            refunds=Count("id", filter=Q(state_status=PredictionCoupon.StateStatus.REFUND)),
            open_predictions=Count("id", filter=Q(state_status=PredictionCoupon.StateStatus.PENDING)),
        )
        engagement = published.aggregate(
            likes=Count("likes", distinct=True),
            saves=Count("favorites", distinct=True),
        )

        wins_count = stats["wins"] or 0
        losses_count = stats["losses"] or 0
        refunds_count = stats["refunds"] or 0
        predictions_count = stats["predictions"] or 0
        decided_predictions = wins_count + losses_count
        settled_predictions = decided_predictions + refunds_count
        win_rate = round(wins_count / decided_predictions * 100, 1) if decided_predictions else 0

        followers_count = AnalystFollow.objects.filter(analyst=analyst).count()
        total_likes_count = engagement["likes"] or 0
        total_saves_count = engagement["saves"] or 0

        published_coupons = list(published.order_by("settled_at", "updated_at", "id"))
        settled_coupons = [
            coupon
            for coupon in published_coupons
            if coupon.state_status in SETTLED_COUPON_STATES
        ]
        total_profit = sum(
            (self._coupon_profit(coupon) for coupon in settled_coupons),
            Decimal("0"),
        )
        settled_stake = sum(
            (coupon.total_stake or Decimal("0") for coupon in settled_coupons),
            Decimal("0"),
        )
        overall_roi = self._roi(total_profit, settled_stake)

        coefficient_values = [
            (coupon.possible_payout / coupon.total_stake)
            for coupon in published_coupons
            if coupon.total_stake and coupon.total_stake > 0 and coupon.possible_payout
        ]
        avg_coupon_coefficient = (
            sum(coefficient_values, Decimal("0")) / len(coefficient_values)
            if coefficient_values
            else Decimal("0")
        )

        published_items = Prediction.objects.filter(
            coupon__author=analyst,
            coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        avg_prediction_coefficient = (
            published_items.aggregate(value=Avg("coefficient"))["value"] or Decimal("0")
        )

        now = timezone.now()
        profit_periods = {
            str(days): self._profit_period(settled_coupons, days=days, now=now)
            for days in (7, 30, 90)
        }
        profit_chart = {
            str(days): self._profit_chart(settled_coupons, days=days, now=now)
            for days in (7, 30, 90)
        }

        is_following = False
        if (
            getattr(self.user, "is_authenticated", False)
            and self.user.pk != analyst.pk
        ):
            is_following = AnalystFollow.objects.filter(
                follower=self.user,
                analyst=analyst,
            ).exists()

        name = profile.display_name or analyst.get_full_name() or analyst.username
        return {
            "expert": analyst,
            "analyst_profile": profile,
            "expert_name": name,
            "expert_initials": _initials(name),
            "followers_count": followers_count,
            "predictions_count": predictions_count,
            "total_likes_count": total_likes_count,
            "total_saves_count": total_saves_count,
            "wins_count": wins_count,
            "losses_count": losses_count,
            "refunds_count": refunds_count,
            "open_predictions_count": stats["open_predictions"] or 0,
            "coupons_count": predictions_count,
            "avg_coefficient": avg_prediction_coefficient,
            "avg_coupon_coefficient": avg_coupon_coefficient,
            "win_rate": win_rate,
            "settled_count": settled_predictions,
            "settled_coupons_count": len(settled_coupons),
            "settled_stake": settled_stake,
            "total_profit": total_profit,
            "total_profit_display": self._signed_money(total_profit),
            "overall_roi": overall_roi,
            "profit_periods": profit_periods,
            "profit_chart": profit_chart,
            "current_streak": self._current_streak(published),
            "market_distribution": self._market_rows(published_items),
            "league_distribution": self._league_rows(published_items),
            "status_distribution": self._status_rows(stats, predictions_count),
            "is_following": is_following,
            "is_self": bool(
                getattr(self.user, "is_authenticated", False)
                and self.user.pk == analyst.pk
            ),
            "latest_predictions": self._latest_prediction_cards(analyst),
        }

    def _following_ids(self, profile_ids: list[int]) -> set[int]:
        if not getattr(self.user, "is_authenticated", False) or not profile_ids:
            return set()
        return set(
            AnalystFollow.objects.filter(
                follower=self.user,
                analyst_id__in=profile_ids,
            ).values_list("analyst_id", flat=True)
        )

    def _serialize_profile(
        self,
        profile,
        *,
        following_ids: set[int],
        best_streak: int,
    ) -> dict:
        name = profile.display_name or profile.user.get_full_name() or profile.user.username
        unlocked_achievements = build_achievement_badges(
            predictions_count=profile.publications_count,
            wins_count=profile.wins_count,
            overall_roi=profile.author_roi_all_time,
            followers_count=profile.followers_count,
            best_win_streak=best_streak,
            is_verified=profile.is_verified,
        )
        return {
            "id": profile.user_id,
            "name": name,
            "username": profile.user.username,
            "initials": _initials(name),
            "avatar_url": profile.avatar.url if profile.avatar else "",
            "verified": profile.is_verified,
            "roi": profile.author_roi,
            "roi_period_days": ROI_PERIOD_DAYS,
            "ranking_score": profile.ranking_score,
            "settled": profile.settled_count,
            "settled_in_roi_period": profile.roi_settled_count,
            "followers": profile.followers_count,
            "publications": profile.publications_count,
            "sports": profile.sports_count,
            "recent_publications": profile.recent_publications_count,
            "wins": profile.wins_count,
            "last_publication_at": profile.last_publication_at,
            "joined_at": self._joined_at(profile),
            "latest_achievements": list(reversed(unlocked_achievements[-5:])),
            "is_self": bool(
                getattr(self.user, "is_authenticated", False)
                and self.user.pk == profile.user_id
            ),
            "is_following": profile.user_id in following_ids,
        }

    @staticmethod
    def _joined_at(profile):
        return profile.onboarding_completed_at or profile.created_at

    def _new_profiles(self, profiles: list) -> list:
        completed = [profile for profile in profiles if profile.onboarding_completed_at]
        source = completed or profiles
        return sorted(
            source,
            key=lambda profile: (self._joined_at(profile), profile.user_id),
            reverse=True,
        )[:NEW_CAPPERS_LIMIT]

    def _rising_profiles(self, profiles: list) -> list:
        cutoff = timezone.now() - timedelta(days=RISING_WINDOW_DAYS)
        candidates = [
            profile
            for profile in profiles
            if profile.recent_publications_count > 0
            and (
                self._joined_at(profile) >= cutoff
                or profile.publications_count <= 25
            )
        ]
        candidates.sort(key=lambda profile: profile.user.username.lower())
        candidates.sort(
            key=lambda profile: (
                profile.recent_publications_count,
                profile.ranking_score,
                profile.wins_count,
                profile.followers_count,
                -profile.publications_count,
            ),
            reverse=True,
        )
        return candidates[:RISING_STARS_LIMIT]

    @staticmethod
    def _popular_profiles(profiles: list) -> list:
        return sorted(
            profiles,
            key=lambda profile: (
                profile.followers_count,
                profile.ranking_score,
                profile.publications_count,
            ),
            reverse=True,
        )[:POPULAR_CAPPERS_LIMIT]

    @staticmethod
    def _active_profiles(profiles: list) -> list:
        active = [profile for profile in profiles if profile.recent_publications_count > 0]
        active.sort(
            key=lambda profile: (
                profile.recent_publications_count,
                profile.last_publication_at or profile.created_at,
                profile.ranking_score,
            ),
            reverse=True,
        )
        return active[:ACTIVE_CAPPERS_LIMIT]

    @staticmethod
    def _coupon_profit(coupon: PredictionCoupon) -> Decimal:
        stake = coupon.total_stake or Decimal("0")
        payout = coupon.possible_payout or Decimal("0")
        if coupon.state_status == PredictionCoupon.StateStatus.WIN:
            return payout - stake
        if coupon.state_status == PredictionCoupon.StateStatus.LOSE:
            return -stake
        return Decimal("0")

    @staticmethod
    def _coupon_result_date(coupon: PredictionCoupon):
        return coupon.settled_at or coupon.updated_at or coupon.published_at or coupon.created_at

    @staticmethod
    def _signed_money(value: Decimal) -> str:
        value = value.quantize(Decimal("0.01"))
        prefix = "+" if value > 0 else ""
        return f"{prefix}{value:.2f}"

    @staticmethod
    def _roi(profit: Decimal, stake: Decimal) -> float:
        if not stake:
            return 0.0
        return round(float(profit / stake * Decimal("100")), 1)

    def _profit_period(self, coupons: list[PredictionCoupon], *, days: int, now) -> dict:
        cutoff = now - timedelta(days=days)
        selected = [
            coupon
            for coupon in coupons
            if self._coupon_result_date(coupon) >= cutoff
        ]
        stake = sum(
            (coupon.total_stake or Decimal("0") for coupon in selected),
            Decimal("0"),
        )
        profit = sum(
            (self._coupon_profit(coupon) for coupon in selected),
            Decimal("0"),
        )
        return {
            "days": days,
            "profit": float(profit),
            "profit_display": self._signed_money(profit),
            "roi": self._roi(profit, stake),
            "stake": float(stake),
            "count": len(selected),
            "positive": profit > 0,
            "negative": profit < 0,
        }

    def _profit_chart(self, coupons: list[PredictionCoupon], *, days: int, now) -> list[dict]:
        today = timezone.localtime(now).date()
        start_date = today - timedelta(days=days - 1)
        daily_profit: dict = {}

        for coupon in coupons:
            result_date = timezone.localtime(self._coupon_result_date(coupon)).date()
            if result_date < start_date or result_date > today:
                continue
            daily_profit[result_date] = daily_profit.get(result_date, Decimal("0")) + self._coupon_profit(coupon)

        points = []
        balance = Decimal("0")
        for offset in range(days):
            day = start_date + timedelta(days=offset)
            balance += daily_profit.get(day, Decimal("0"))
            points.append({"label": day.strftime("%d.%m"), "value": round(float(balance), 2)})
        return points

    @staticmethod
    def _current_streak(queryset) -> dict:
        states = list(
            queryset.filter(
                state_status__in=[
                    PredictionCoupon.StateStatus.WIN,
                    PredictionCoupon.StateStatus.LOSE,
                ]
            )
            .order_by("-settled_at", "-updated_at", "-id")
            .values_list("state_status", flat=True)[:100]
        )
        if not states:
            return {"count": 0, "label": "Нет серии", "state": "none"}

        current = states[0]
        count = 0
        for state in states:
            if state != current:
                break
            count += 1
        return {
            "count": count,
            "label": "побед подряд" if current == PredictionCoupon.StateStatus.WIN else "поражений подряд",
            "state": current,
        }

    @staticmethod
    def _latest_prediction_cards(analyst) -> list[Prediction]:
        positions = Prediction.objects.select_related(
            "match__league__country",
            "match__home_team",
            "match__away_team",
        ).order_by("id")
        coupons = list(
            PredictionCoupon.objects.filter(
                author=analyst,
                published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            )
            .prefetch_related(
                Prefetch("predictions", queryset=positions, to_attr="public_positions")
            )
            .order_by("-published_at", "-created_at", "-id")[:12]
        )

        cards = []
        for coupon in coupons:
            items = list(getattr(coupon, "public_positions", []) or [])
            if not items:
                continue
            item = items[0]
            item.confidence = coupon.confidence
            item.state_status = coupon.state_status
            if coupon.total_stake:
                item.coefficient = (
                    coupon.possible_payout / coupon.total_stake
                ).quantize(Decimal("0.01"))
            if len(items) > 1:
                item.market = f"Экспресс · {len(items)} игр"
                item.selection = f"{item.selection} + ещё {len(items) - 1}"
            cards.append(item)
        return cards

    @staticmethod
    def _market_rows(queryset) -> list[dict]:
        rows = (
            queryset.values("market")
            .annotate(
                total=Count("id"),
                wins=Count("id", filter=Q(state_status=Prediction.StateStatus.WIN)),
                losses=Count("id", filter=Q(state_status=Prediction.StateStatus.LOSE)),
                refunds=Count("id", filter=Q(state_status=Prediction.StateStatus.REFUND)),
                avg_coefficient=Avg("coefficient"),
            )
            .order_by("-total", "market")[:8]
        )
        result = []
        for row in rows:
            settled = (row["wins"] or 0) + (row["losses"] or 0)
            result.append(
                {
                    "label": MARKET_LABELS.get(row["market"], row["market"] or "Рынок"),
                    "count": row["total"] or 0,
                    "wins": row["wins"] or 0,
                    "losses": row["losses"] or 0,
                    "refunds": row["refunds"] or 0,
                    "win_rate": round((row["wins"] or 0) / settled * 100) if settled else 0,
                    "avg_coefficient": row["avg_coefficient"] or 0,
                }
            )
        return result

    @staticmethod
    def _league_rows(queryset) -> list[dict]:
        rows = (
            queryset.values("match__league__name_ru", "match__league__name")
            .annotate(
                total=Count("id"),
                wins=Count("id", filter=Q(state_status=Prediction.StateStatus.WIN)),
                losses=Count("id", filter=Q(state_status=Prediction.StateStatus.LOSE)),
                refunds=Count("id", filter=Q(state_status=Prediction.StateStatus.REFUND)),
                avg_coefficient=Avg("coefficient"),
            )
            .order_by("-total", "match__league__name_ru")[:8]
        )
        result = []
        for row in rows:
            settled = (row["wins"] or 0) + (row["losses"] or 0)
            result.append(
                {
                    "label": row["match__league__name_ru"] or row["match__league__name"] or "Лига не указана",
                    "count": row["total"] or 0,
                    "wins": row["wins"] or 0,
                    "losses": row["losses"] or 0,
                    "refunds": row["refunds"] or 0,
                    "win_rate": round((row["wins"] or 0) / settled * 100) if settled else 0,
                    "avg_coefficient": row["avg_coefficient"] or 0,
                }
            )
        return result

    @staticmethod
    def _status_rows(stats: dict, total: int) -> list[dict]:
        source = [
            ("Победы", stats["wins"] or 0, "win"),
            ("Поражения", stats["losses"] or 0, "lose"),
            ("Возвраты", stats["refunds"] or 0, "refund"),
            ("В ожидании", stats["open_predictions"] or 0, "open"),
        ]
        return [
            {
                "label": label,
                "count": count,
                "percent": round(count / total * 100) if total else 0,
                "state": state,
            }
            for label, count, state in source
        ]
