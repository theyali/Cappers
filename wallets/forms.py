from django import forms

from game.models import Sport

from .models import CopyBettingSubscription


class CopyBettingForm(forms.ModelForm):
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
            "bank_amount": forms.NumberInput(attrs={"min": "1", "step": "0.01"}),
            "stake_percent": forms.NumberInput(attrs={"min": "0.01", "max": "100", "step": "0.01"}),
            "stop_loss_amount": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
            "max_single_stake": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
            "min_total_coefficient": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
            "copy_regular_coupons": forms.CheckboxInput(),
            "copy_tournament_coupons": forms.CheckboxInput(),
        }
        labels = {
            "bank_amount": "Банк для копирования, ₽",
            "stake_percent": "Процент от банка на ставку",
            "stop_loss_amount": "Стоп-лосс, ₽",
            "max_single_stake": "Максимум на одну ставку, ₽",
            "min_total_coefficient": "Минимальный общий коэффициент",
            "copy_regular_coupons": "Копировать обычные прогнозы",
            "copy_tournament_coupons": "Копировать турнирные прогнозы",
        }
        help_texts = {
            "max_single_stake": "Оставьте 0, если лимит на одну ставку не нужен.",
            "stop_loss_amount": "Когда просадка достигнет лимита, копирование остановится.",
            "min_total_coefficient": "Оставьте 0, если фильтр по коэффициенту не нужен.",
        }
