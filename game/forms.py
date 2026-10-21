from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from game.cover_images import prediction_editor_covers
from game.models import PredictionCoupon, PredictionCoverImage
from game.services.prediction_editor import can_use_rich_prediction_fields, validate_paid_prediction_content, validate_paid_prediction_settings
from tournaments.services.coupons import predictable_tournaments


MAX_CUSTOM_COVER_SIZE = 5 * 1024 * 1024
ALLOWED_CUSTOM_COVER_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_CUSTOM_COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class RichPredictionCouponForm(forms.Form):
    total_stake = forms.DecimalField(
        label="Сумма",
        required=False,
        min_value=Decimal("100"),
        max_value=Decimal("1000000"),
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"min": "100", "max": "1000000", "step": "1"}),
    )
    confidence = forms.IntegerField(
        label="Уверенность",
        required=False,
        min_value=0,
        max_value=100,
        widget=forms.TextInput(
            attrs={
                "type": "range",
                "min": "0",
                "max": "100",
                "step": "1",
                "class": "coupon-confidence-range",
                "data-rich-confidence": "",
            }
        ),
    )
    draft_revision = forms.CharField(required=False, widget=forms.HiddenInput)
    remove_prediction_ids = forms.CharField(
        required=False,
        widget=forms.HiddenInput,
    )
    is_paid = forms.BooleanField(
        label="Платный прогноз",
        required=False,
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
    tournament = forms.ChoiceField(label="Турнир", required=False)
    published_status = forms.ChoiceField(
        required=False,
        choices=(
            (PredictionCoupon.PublishedStatus.DRAFT, "Черновик"),
            (PredictionCoupon.PublishedStatus.PUBLISHED, "Опубликован"),
        ),
    )

    def __init__(self, *args, user=None, coupon=None, sport=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.coupon = coupon
        self.sport = sport
        self.can_use_rich_fields = can_use_rich_prediction_fields(user)
        self.tournaments = predictable_tournaments(user)
        self.fields["tournament"].choices = [("", "Без турнира")] + [
            (str(tournament.pk), tournament.title) for tournament in self.tournaments
        ]

        covers = PredictionCoverImage.objects.none()
        if self.can_use_rich_fields:
            covers = prediction_editor_covers()
        self.fields["cover_image"].queryset = covers

        if not self.can_use_rich_fields:
            # Tournament predictions need a description, so participants may write one.
            locked_fields = ("cover_image", "custom_cover_image") if self.tournaments else ("description", "cover_image", "custom_cover_image")
            for field_name in locked_fields:
                self.fields[field_name].disabled = True
                self.fields[field_name].required = False

        if coupon is not None and coupon.published_status == PredictionCoupon.PublishedStatus.PUBLISHED:
            # The stake was charged on publish; the stake, the confidence, the audience and the tournament
            # stay fixed afterwards.
            self.fields["total_stake"].disabled = True
            self.fields["confidence"].disabled = True
            self.fields["is_paid"].disabled = True
            self.fields["tournament"].disabled = True

    def _tournament_requires_text(self, tournament_id) -> bool:
        # A published coupon keeps its tournament even after the tournament leaves the user's live list.
        known = list(self.tournaments) + ([self.coupon.tournament] if self.coupon and self.coupon.tournament_id else [])
        tournament = next((item for item in known if str(item.pk) == str(tournament_id)), None)
        return tournament is None or tournament.requires_prediction_text

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

    def clean_remove_prediction_ids(self):
        value = self.cleaned_data.get("remove_prediction_ids", "")
        ids = []
        seen = set()
        for raw_id in str(value or "").replace(" ", "").split(","):
            if not raw_id:
                continue
            try:
                prediction_id = int(raw_id)
            except (TypeError, ValueError):
                raise forms.ValidationError("Некорректная позиция купона.")
            if prediction_id <= 0 or prediction_id in seen:
                continue
            seen.add(prediction_id)
            ids.append(prediction_id)
        return ids

    def clean(self):
        cleaned_data = super().clean()
        is_paid = bool(cleaned_data.get("is_paid"))
        description = (cleaned_data.get("description") or "").strip()

        tournament = cleaned_data.get("tournament")
        publishing = cleaned_data.get("published_status") == PredictionCoupon.PublishedStatus.PUBLISHED
        if tournament and is_paid:
            self.add_error("is_paid", "Платный прогноз нельзя отправить в турнир.")
        if tournament and publishing and self._tournament_requires_text(tournament):
            try:
                validate_paid_prediction_content(cleaned_data.get("headline"), description, kind="турнирного прогноза")
            except ValidationError as exc:
                for field, messages in exc.message_dict.items():
                    for message in messages:
                        self.add_error(field, message)
        if is_paid and not self.can_use_rich_fields:
            self.add_error(
                "is_paid",
                "Платные прогнозы доступны VIP-капперам",
            )
        if is_paid and self.can_use_rich_fields:
            try:
                validate_paid_prediction_settings(self.user, self.coupon)
            except ValidationError as exc:
                for field, messages in exc.message_dict.items():
                    for message in messages:
                        self.add_error(field, message)
            try:
                validate_paid_prediction_content(cleaned_data.get("headline"), description)
            except ValidationError as exc:
                for field, messages in exc.message_dict.items():
                    for message in messages:
                        self.add_error(field, message)

        return cleaned_data
