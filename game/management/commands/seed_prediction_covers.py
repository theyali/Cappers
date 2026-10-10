from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from game.cover_images import (
    assign_coupon_cover_image,
    assign_prediction_cover_images,
    invalidate_cover_ids_cache,
)
from game.models import Prediction, PredictionCoupon, PredictionCoverImage, Sport


SPORT_ALIASES = {
    "football": ("football", "soccer"),
    "basketball": ("basketball",),
    "hockey": ("hockey",),
    "tennis": ("tennis",),
}


def _title_from_file(path: Path) -> str:
    title = path.stem.replace("@2x", "").replace("_", " ").replace("-", " ")
    return " ".join(part for part in title.split() if part)


def _sport_key(path: Path) -> str:
    return path.name.split("_", 1)[0].strip().lower()


def _cover_files(directory: Path) -> tuple[list[Path], Path | None]:
    desktop_dir = directory / "desktop"
    mobile_dir = directory / "mobile"
    if desktop_dir.is_dir():
        return sorted(desktop_dir.glob("*.png")), mobile_dir if mobile_dir.is_dir() else None
    return sorted(directory.glob("*.png")), None


def _matching_mobile_file(mobile_dir: Path | None, desktop_path: Path) -> Path | None:
    if mobile_dir is None:
        return None
    exact = mobile_dir / desktop_path.name
    if exact.is_file():
        return exact
    stem = desktop_path.stem
    if stem.endswith("@2x"):
        stem = stem.removesuffix("@2x")
    matches = sorted(mobile_dir.glob(f"{stem}*.png"))
    return matches[0] if matches else None


def _matching_sports(key: str):
    aliases = SPORT_ALIASES.get(key, (key,))
    query = Q()
    for alias in aliases:
        query |= Q(code__icontains=alias) | Q(name__icontains=alias) | Q(name_ru__icontains=alias)
    return Sport.objects.filter(query).order_by("id")


class Command(BaseCommand):
    help = (
        "Replace PredictionCoverImage rows from seed_data, then reassign system covers "
        "for existing coupons."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--seed-dir",
            default=str(settings.BASE_DIR / "seed_data"),
            help="Directory containing express/ and sport/ cover images.",
        )
        parser.add_argument(
            "--skip-reassign",
            action="store_true",
            help="Only delete and seed PredictionCoverImage rows; do not update coupons.",
        )

    def handle(self, *args, **options):
        seed_dir = Path(options["seed_dir"]).expanduser().resolve()
        express_dir = seed_dir / "express"
        sport_dir = seed_dir / "sport"
        if not express_dir.is_dir() or not sport_dir.is_dir():
            raise CommandError(
                f"Seed directory must contain express/ and sport/: {seed_dir}"
            )

        express_files, express_mobile_dir = _cover_files(express_dir)
        sport_files, sport_mobile_dir = _cover_files(sport_dir)
        if not express_files and not sport_files:
            raise CommandError(f"No PNG covers found in {seed_dir}")

        with transaction.atomic():
            coupon_count = PredictionCoupon.objects.count()
            event_count = Prediction.objects.count()
            PredictionCoupon.objects.update(cover_image=None)
            Prediction.objects.update(cover_image=None)
            deleted_count, _ = PredictionCoverImage.objects.all().delete()

            created_express = self._seed_express(express_files, express_mobile_dir)
            created_sport, skipped_sport = self._seed_sport(sport_files, sport_mobile_dir)
            invalidate_cover_ids_cache()

            reassigned = 0
            reassigned_events = 0
            if not options["skip_reassign"]:
                coupons = (
                    PredictionCoupon.objects.prefetch_related("predictions__match__sport")
                    .order_by("id")
                )
                for coupon in coupons.iterator(chunk_size=500):
                    if assign_coupon_cover_image(coupon):
                        reassigned += 1
                event_queryset = Prediction.objects.select_related("match__sport").order_by("id")
                batch = []
                for prediction in event_queryset.iterator(chunk_size=500):
                    batch.append(prediction)
                    if len(batch) >= 500:
                        reassigned_events += assign_prediction_cover_images(batch)
                        batch = []
                if batch:
                    reassigned_events += assign_prediction_cover_images(batch)

        self.stdout.write(
            self.style.SUCCESS(
                "Prediction covers replaced: "
                f"deleted={deleted_count}, express={created_express}, sport={created_sport}, "
                f"skipped_sport_files={skipped_sport}, coupons_reset={coupon_count}, "
                f"events_reset={event_count}, coupons_reassigned={reassigned}, "
                f"events_reassigned={reassigned_events}."
            )
        )

    def _save_cover_files(
        self,
        cover: PredictionCoverImage,
        *,
        desktop_path: Path,
        mobile_path: Path | None,
        desktop_name: str,
        mobile_name: str,
    ) -> None:
        with desktop_path.open("rb") as source:
            cover.image.save(desktop_name, File(source), save=False)
        if mobile_path is not None:
            with mobile_path.open("rb") as source:
                cover.mobile_image.save(mobile_name, File(source), save=False)
        cover.save()

    def _seed_express(self, files: list[Path], mobile_dir: Path | None) -> int:
        created = 0
        for path in files:
            mobile_path = _matching_mobile_file(mobile_dir, path)
            cover = PredictionCoverImage(
                placement=PredictionCoverImage.Placement.GRID,
                cover_type=PredictionCoverImage.CoverType.EXPRESS,
                title=_title_from_file(path),
                is_active=True,
            )
            self._save_cover_files(
                cover,
                desktop_path=path,
                mobile_path=mobile_path,
                desktop_name=f"seed_data/express/desktop/{path.name}",
                mobile_name=f"seed_data/express/mobile/{mobile_path.name if mobile_path else path.name}",
            )
            created += 1
        return created

    def _seed_sport(self, files: list[Path], mobile_dir: Path | None) -> tuple[int, int]:
        created = 0
        skipped = 0
        for path in files:
            mobile_path = _matching_mobile_file(mobile_dir, path)
            sports = list(_matching_sports(_sport_key(path)))
            if not sports:
                skipped += 1
                self.stdout.write(
                    self.style.WARNING(f"No matching sport for cover file: {path.name}")
                )
                continue

            for sport in sports:
                cover = PredictionCoverImage(
                    placement=PredictionCoverImage.Placement.GRID,
                    cover_type=PredictionCoverImage.CoverType.SPORT,
                    sport=sport,
                    title=_title_from_file(path),
                    is_active=True,
                )
                self._save_cover_files(
                    cover,
                    desktop_path=path,
                    mobile_path=mobile_path,
                    desktop_name=f"seed_data/sport/desktop/{sport.code}/{path.name}",
                    mobile_name=(
                        f"seed_data/sport/mobile/{sport.code}/{mobile_path.name if mobile_path else path.name}"
                    ),
                )
                created += 1
        return created, skipped
