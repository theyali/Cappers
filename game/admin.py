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

