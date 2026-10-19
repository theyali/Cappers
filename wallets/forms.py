from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from .services import validate_copybetting_stake

from game.models import Sport

from .models import CopyBettingSubscription


class CopyBettingForm(forms.ModelForm):
    min_total_coefficient = forms.DecimalField(
        label="Минимальный общий коэффициент", min_value=Decimal("1.01"),
        max_digits=8, decimal_places=2, initial=Decimal("1.01"),
        widget=forms.NumberInput(attrs={"min": "1.01", "step": "0.01", "inputmode": "decimal"}),
    )
    coupon_types = forms.ChoiceField(
        label="Типы прогнозов", required=False,
        choices=[("regular", "Обычные"), ("tournament", "Турнирные"), ("both", "Оба типа")],
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial["min_total_coefficient"] = max(self.instance.min_total_coefficient, Decimal("1.01"))
        regular = self.instance.copy_regular_coupons
        tournament = self.instance.copy_tournament_coupons
        self.initial["coupon_types"] = "both" if regular and tournament else "tournament" if tournament else "regular"

    def clean(self):
        cleaned = super().clean()
        types = cleaned.get("coupon_types")
        if types:
            cleaned["copy_regular_coupons"] = types in {"regular", "both"}
            cleaned["copy_tournament_coupons"] = types in {"tournament", "both"}
        if not cleaned.get("copy_regular_coupons") and not cleaned.get("copy_tournament_coupons"):
            self.add_error("coupon_types", "Выберите тип прогнозов для копирования.")
        stake_fields = ("bank_amount", "stake_percent", "max_single_stake")
        if all(cleaned.get(key) is not None for key in stake_fields):
            try:
                validate_copybetting_stake(**{key: cleaned[key] for key in stake_fields})
            except ValidationError as exc:
                self.add_error(None, exc)
        return cleaned

    allowed_sports = forms.ModelMultipleChoiceField(
        queryset=Sport.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Виды спорта",
        help_text="Если ничего не выбрать, будут копироваться все виды спорта.",
    )

    class Meta:
        model = CopyBettingSubscription
        fields = (
            "bank_amount",
            "stake_percent",
            "stop_loss_amount",
            "max_single_stake",
            "min_total_coefficient",
            "copy_regular_coupons",
            "copy_tournament_coupons",
            "allowed_sports",
        )
        widgets = {
            "bank_amount": forms.NumberInput(attrs={"min": "1", "step": "1"}),
            "stake_percent": forms.NumberInput(attrs={"min": "0.01", "max": "100", "step": "0.01"}),
            "stop_loss_amount": forms.NumberInput(attrs={"min": "0", "step": "1"}),
            "max_single_stake": forms.NumberInput(attrs={"min": "0", "step": "1"}),
            "copy_regular_coupons": forms.CheckboxInput(),
            "copy_tournament_coupons": forms.CheckboxInput(),
        }
        labels = {
            "bank_amount": "Банк для копирования, коины",
            "stake_percent": "Процент от банка на ставку",
            "stop_loss_amount": "Стоп-лосс, коины",
            "max_single_stake": "Максимум на одну ставку, коины",
            "min_total_coefficient": "Минимальный общий коэффициент",
            "copy_regular_coupons": "Копировать обычные прогнозы",
            "copy_tournament_coupons": "Копировать турнирные прогнозы",
        }
        help_texts = {
            "max_single_stake": "Оставьте 0, если лимит на одну ставку не нужен.",
            "stop_loss_amount": "Когда просадка достигнет лимита, копирование остановится.",
            "min_total_coefficient": "Минимум — 1,01. Прогнозы ниже порога пропускаются.",
        }
