from django.contrib import admin
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from game.models import (
    Country,
    League,
    LeagueSeason,
    Match,
    MatchManualReview,
    MatchOdds,
    Prediction,
    PredictionCoupon,
    PredictionCoverImage,
    Sport,
    Team,
    Venue,
    country_logo_upload_path,
    league_logo_upload_path,
    sport_image_upload_path,
    team_logo_upload_path,
)
from game.services.local_logos import sync_entity_logo


def _local_media_preview(url: str, *, size: int = 40):
    if not url:
        return "—"
    return format_html(
        '<img src="{}" width="{}" height="{}" alt="">',
        url,
        size,
        size,
    )


def _refresh_selected_local_media(
    queryset,
    *,
    field_name: str,
    remote_field: str,
    target_builder,
):
    downloaded = 0
    skipped = 0
    failed = 0
    for instance in queryset.iterator(chunk_size=100):
        remote_url = str(getattr(instance, remote_field, "") or "").strip()
        if not remote_url:
            skipped += 1
            continue

        if sync_entity_logo(
            instance,
            field_name=field_name,
            remote_url=remote_url,
            target_name=target_builder(instance, ""),
            force=True,
        ):
            downloaded += 1
        else:
            failed += 1
    return downloaded, skipped, failed


class PredictionCoverImageInline(admin.TabularInline):
    model = PredictionCoverImage
    extra = 1
    fields = ("placement", "image", "title", "is_active")
    verbose_name = "Обложка прогноза"
    verbose_name_plural = "Обложки прогнозов"

    def get_queryset(self, request):
        return super().get_queryset(request).filter(cover_type=PredictionCoverImage.CoverType.SPORT)


@admin.register(Sport)
class SportAdmin(admin.ModelAdmin):
    list_display = ("image_preview", "name_ru", "name", "code", "external_id", "provider")
    search_fields = ("name", "name_ru", "code", "=external_id")
    list_filter = ("provider",)
    readonly_fields = ("remote_image_url", "image_preview")
    actions = ("refresh_local_images",)
    inlines = (PredictionCoverImageInline,)

    @admin.display(description="Изображение")
    def image_preview(self, obj):
        return _local_media_preview(obj.image_url)

    @admin.action(description="Обновить локальные изображения")
    def refresh_local_images(self, request, queryset):
        downloaded, skipped, failed = _refresh_selected_local_media(
            queryset,
            field_name="image",
            remote_field="remote_image_url",
            target_builder=sport_image_upload_path,
        )
        self.message_user(
            request,
            f"Обновлено: {downloaded}; без remote URL: {skipped}; ошибок: {failed}.",
        )


@admin.register(PredictionCoverImage)
class PredictionCoverImageAdmin(admin.ModelAdmin):
    list_display = ("id", "placement", "cover_type", "sport", "title", "is_active", "created_at")
    list_filter = ("placement", "cover_type", "sport", "is_active", "created_at")
    search_fields = ("title", "sport__name", "sport__name_ru", "sport__code")
    autocomplete_fields = ("sport",)
    readonly_fields = ("created_at",)
    fields = ("placement", "cover_type", "sport", "image", "title", "is_active", "created_at")


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ("logo_preview", "name_ru", "name", "code", "external_id", "provider")
    search_fields = ("name", "name_ru", "code", "=external_id")
    list_filter = ("provider",)
    readonly_fields = ("remote_logo_url", "logo_preview")
    actions = ("refresh_local_logos",)

    @admin.display(description="Лого")
    def logo_preview(self, obj):
        return _local_media_preview(obj.logo_url)

    @admin.action(description="Обновить локальные логотипы")
    def refresh_local_logos(self, request, queryset):
        downloaded, skipped, failed = _refresh_selected_local_media(
            queryset,
            field_name="logo",
            remote_field="remote_logo_url",
            target_builder=country_logo_upload_path,
        )
        self.message_user(
            request,
            f"Обновлено: {downloaded}; без remote URL: {skipped}; ошибок: {failed}.",
        )


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ("name_ru", "name", "city_ru", "city", "external_id", "provider")
    search_fields = ("name", "name_ru", "city", "city_ru", "=external_id")
    list_filter = ("provider",)


@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = (
        "logo_preview",
        "name_ru",
        "name",
        "sport",
        "country",
        "is_top",
        "top_order",
        "external_id",
        "provider",
    )
    list_editable = ("is_top", "top_order")
    search_fields = ("name", "name_ru", "slug", "=external_id")
    list_filter = ("is_top", "provider", "sport", "country")
    autocomplete_fields = ("sport", "country")
    readonly_fields = ("remote_logo_url", "logo_preview")
    actions = ("refresh_local_logos",)
    ordering = ("-is_top", "top_order", "name_ru", "name", "id")

    @admin.display(description="Лого")
    def logo_preview(self, obj):
        return _local_media_preview(obj.logo_url)

    @admin.action(description="Обновить локальные логотипы")
    def refresh_local_logos(self, request, queryset):
        downloaded, skipped, failed = _refresh_selected_local_media(
            queryset.select_related("sport"),
            field_name="logo",
            remote_field="remote_logo_url",
            target_builder=league_logo_upload_path,
        )
        self.message_user(
            request,
            f"Обновлено: {downloaded}; без remote URL: {skipped}; ошибок: {failed}.",
        )


@admin.register(LeagueSeason)
class LeagueSeasonAdmin(admin.ModelAdmin):
    list_display = ("league", "year", "is_current", "round_name_ru", "start_date", "end_date")
    search_fields = ("league__name", "league__name_ru", "round_name", "round_name_ru")
    list_filter = ("is_current", "sport", "year")
    autocomplete_fields = ("league", "sport")


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("logo_preview", "name_ru", "name", "sport", "country", "external_id", "provider")
    search_fields = ("name", "name_ru", "slug", "=external_id")
    list_filter = ("provider", "sport", "country")
    autocomplete_fields = ("sport", "country", "venue")
    readonly_fields = ("remote_logo_url", "logo_preview")
    actions = ("refresh_local_logos",)

    @admin.display(description="Лого")
    def logo_preview(self, obj):
        return _local_media_preview(obj.logo_url)

    @admin.action(description="Обновить локальные логотипы")
    def refresh_local_logos(self, request, queryset):
        downloaded, skipped, failed = _refresh_selected_local_media(
            queryset.select_related("sport"),
            field_name="logo",
            remote_field="remote_logo_url",
            target_builder=team_logo_upload_path,
        )
        self.message_user(
            request,
            f"Обновлено: {downloaded}; без remote URL: {skipped}; ошибок: {failed}.",
        )


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = (
        "external_id",
        "sport",
        "sync_scope",
        "starts_at",
        "league_name",
        "home_team_name",
        "away_team_name",
        "score",
        "open_reviews_count",
        "live_minute_label",
        "updated_at",
    )
    list_filter = ("sport", "sync_scope", "time_status", "league__country")
    search_fields = (
        "=external_id",
        "slug",
        "league__name",
        "league__name_ru",
        "home_team__name",
        "home_team__name_ru",
        "away_team__name",
        "away_team__name_ru",
    )
    readonly_fields = ("created_at", "updated_at", "last_seen_at", "raw_data")
    autocomplete_fields = ("sport", "league", "league_season", "home_team", "away_team", "venue")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _open_reviews_count=Count(
                "manual_reviews",
                filter=Q(manual_reviews__status=MatchManualReview.Status.OPEN),
                distinct=True,
            )
        )

    @admin.display(description="На проверке", ordering="_open_reviews_count")
    def open_reviews_count(self, obj):
        count = int(obj._open_reviews_count or 0)
        if not count:
            return 0
        url = reverse("admin:game_matchmanualreview_changelist")
        return format_html(
            '<a href="{}?q={}&status__exact={}">{}</a>',
            url,
            obj.pk,
            MatchManualReview.Status.OPEN,
            count,
        )


@admin.register(MatchManualReview)
class MatchManualReviewAdmin(admin.ModelAdmin):
    list_display = (
        "match",
        "reason",
        "status",
        "match_score",
        "match_scope",
        "created_at",
        "updated_at",
    )
    list_filter = (
        "status",
        "reason",
        "match__sport",
        "match__sync_scope",
    )
    search_fields = (
        "=match__id",
        "=match__external_id",
        "match__home_team__name",
        "match__home_team__name_ru",
        "match__away_team__name",
        "match__away_team__name_ru",
        "match__league__name",
        "match__league__name_ru",
    )
    autocomplete_fields = ("match",)
    list_select_related = (
        "match",
        "match__sport",
        "match__league",
        "match__home_team",
        "match__away_team",
    )
    readonly_fields = ("created_at", "updated_at", "resolved_at", "details")
    actions = ("mark_resolved", "mark_ignored")

    @admin.display(description="Счёт", ordering="match__score")
    def match_score(self, obj):
        return obj.match.score or "—"

    @admin.display(description="Статус матча", ordering="match__sync_scope")
    def match_scope(self, obj):
        return obj.match.get_sync_scope_display()

    @admin.action(description="Отметить выбранные как решённые")
    def mark_resolved(self, request, queryset):
        queryset.filter(status=MatchManualReview.Status.OPEN).update(
            status=MatchManualReview.Status.RESOLVED,
            resolved_at=timezone.now(),
            updated_at=timezone.now(),
        )

    @admin.action(description="Игнорировать выбранные")
    def mark_ignored(self, request, queryset):
        queryset.filter(status=MatchManualReview.Status.OPEN).update(
            status=MatchManualReview.Status.IGNORED,
            resolved_at=timezone.now(),
            updated_at=timezone.now(),
        )


@admin.register(MatchOdds)
class MatchOddsAdmin(admin.ModelAdmin):
    list_display = ("match", "home_win_bet", "x_bet", "away_win_bet", "goals_over_2_5", "goals_under_2_5")
    search_fields = (
        "match__home_team__name",
        "match__home_team__name_ru",
        "match__away_team__name",
        "match__away_team__name_ru",
        "=match__external_id",
    )
    autocomplete_fields = ("match",)
    readonly_fields = ("raw_data", "extra_markets")


class PredictionItemInline(admin.TabularInline):
    model = Prediction
    extra = 0
    autocomplete_fields = ("match",)
    fields = ("match", "market", "selection", "coefficient", "stake", "state_status")
    verbose_name = "Позиция прогноза"
    verbose_name_plural = "Позиции прогноза"


@admin.register(PredictionCoupon)
class PredictionCouponAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "author",
        "coupon_type",
        "confidence",
        "published_status",
        "state_status",
        "audience",
        "cover_image",
        "total_stake",
        "possible_payout",
        "published_at",
        "settled_at",
    )
    list_filter = (
        "coupon_type",
        "published_status",
        "state_status",
        "audience",
        "created_at",
        "settled_at",
    )
    search_fields = ("author__username",)
    autocomplete_fields = ("cover_image",)
    readonly_fields = ("coupon_type",)
    fields = (
        "author",
        "coupon_type",
        "confidence",
        "published_status",
        "state_status",
        "audience",
        "cover_image",
        "total_stake",
        "possible_payout",
        "published_at",
        "settled_at",
    )
    inlines = (PredictionItemInline,)


@admin.register(Prediction)
class PredictionItemAdmin(admin.ModelAdmin):
    list_display = ("id", "coupon", "match", "market", "selection", "stake", "state_status")
    list_filter = ("state_status", "market")
    search_fields = (
        "coupon__author__username",
        "match__home_team__name",
        "match__home_team__name_ru",
        "match__away_team__name",
        "match__away_team__name_ru",
        "selection",
    )
    autocomplete_fields = ("coupon", "match")
