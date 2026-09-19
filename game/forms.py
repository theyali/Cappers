from decimal import Decimal

from django import forms

from game.models import Match, PredictionCoupon, PredictionCoverImage
from game.services.prediction_editor import can_use_rich_prediction_fields


MAX_CUSTOM_COVER_SIZE = 5 * 1024 * 1024
ALLOWED_CUSTOM_COVER_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_CUSTOM_COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class RichPredictionCouponForm(forms.Form):
    match = forms.ModelChoiceField(
        label="Матч",
        queryset=Match.objects.none(),
    )
    coupon_type = forms.ChoiceField(
        label="Тип прогноза",
        choices=PredictionCoupon.CouponType.choices,
        initial=PredictionCoupon.CouponType.SINGLE,
    )
    is_paid = forms.BooleanField(
        label="Платный прогноз",
        required=False,
    )
    coefficient = forms.DecimalField(
        label="Коэффициент",
        min_value=Decimal("0.01"),
        max_digits=8,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
    )
    prediction_text = forms.CharField(
        label="Прогноз",
        max_length=120,
    )
    headline = forms.CharField(
        label="Заголовок",
        max_length=160,
        required=False,
    )
    description = forms.CharField(
        label="Описание прогноза",
        required=False,
        widget=forms.Textarea(attrs={"rows": 8}),
    )
    cover_image = forms.ModelChoiceField(
        label="Системная обложка",
        required=False,
        queryset=PredictionCoverImage.objects.none(),
    )
    custom_cover_image = forms.ImageField(
        label="Своя обложка",
        required=False,
    )
    tags = forms.CharField(
        label="Теги",
        required=False,
        help_text="До 7 тегов через запятую.",
    )

    def __init__(self, *args, user=None, match=None, sport=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.match = match
        self.sport = sport
        self.can_use_rich_fields = can_use_rich_prediction_fields(user)

        matches = Match.objects.filter(sync_scope=Match.SyncScope.PREMATCH).select_related(
            "sport",
            "league",
            "home_team",
            "away_team",
        )
        if match is not None:
            match_id = getattr(match, "pk", match)
            matches = matches.filter(pk=match_id)
        elif sport is not None:
            sport_id = getattr(sport, "pk", sport)
            matches = matches.filter(sport_id=sport_id)
        self.fields["match"].queryset = matches.order_by("starts_at", "id")

        covers = PredictionCoverImage.objects.none()
        if self.can_use_rich_fields:
            covers = PredictionCoverImage.objects.filter(
                is_active=True,
                placement=PredictionCoverImage.Placement.GRID,
            )
            if sport is not None:
                sport_id = getattr(sport, "pk", sport)
                covers = covers.filter(
                    models_q_for_cover_sport(sport_id)
                )
            elif match is not None and getattr(match, "sport_id", None):
                covers = covers.filter(
                    models_q_for_cover_sport(match.sport_id)
                )
            covers = covers.select_related("sport").order_by(
                "cover_type",
                "sport__name_ru",
                "sport__name",
                "id",
            )
        self.fields["cover_image"].queryset = covers

        if not self.can_use_rich_fields:
            for field_name in ("description", "cover_image", "custom_cover_image"):
                self.fields[field_name].disabled = True
                self.fields[field_name].required = False

    def clean_custom_cover_image(self):
        image = self.cleaned_data.get("custom_cover_image")
        if not image:
            return image

        if not self.can_use_rich_fields:
            raise forms.ValidationError("Своя обложка доступна VIP-капперам.")

        if image.size > MAX_CUSTOM_COVER_SIZE:
            raise forms.ValidationError("Максимальный размер файла — 5 МБ.")

        content_type = getattr(image, "content_type", "")
        if content_type and content_type not in ALLOWED_CUSTOM_COVER_TYPES:
            raise forms.ValidationError("Разрешены JPG, PNG и WebP.")

        suffix = ""
        if getattr(image, "name", ""):
            dot_index = image.name.rfind(".")
            if dot_index >= 0:
                suffix = image.name[dot_index:].lower()
        if suffix not in ALLOWED_CUSTOM_COVER_EXTENSIONS:
            raise forms.ValidationError("Разрешены JPG, PNG и WebP.")

        return image

    def clean_tags(self):
        value = self.cleaned_data.get("tags", "")
        tags = []
        seen = set()
        for raw_tag in value.replace("\n", ",").split(","):
            tag = raw_tag.strip().lstrip("#").strip()
            normalized = tag.casefold()
            if not tag or normalized in seen:
                continue
            seen.add(normalized)
            tags.append(tag)
            if len(tags) == 7:
                break
        return tags

    def clean(self):
        cleaned_data = super().clean()
        is_paid = bool(cleaned_data.get("is_paid"))
        description = (cleaned_data.get("description") or "").strip()

        if is_paid and not self.can_use_rich_fields:
            self.add_error(
                "is_paid",
                "Платные прогнозы доступны VIP-капперам",
            )
        if is_paid and not description and self.can_use_rich_fields:
            self.add_error(
                "description",
                "Для платного прогноза обязательно добавьте описание.",
            )

        return cleaned_data


def models_q_for_cover_sport(sport_id):
    from django.db.models import Q

    return Q(cover_type=PredictionCoverImage.CoverType.EXPRESS) | Q(
        cover_type=PredictionCoverImage.CoverType.SPORT,
        sport_id=sport_id,
    )
