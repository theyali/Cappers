from django import forms

from .models import AdminNotificationCampaign


class AdminNotificationCampaignForm(forms.ModelForm):
    class Meta:
        model = AdminNotificationCampaign
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        audience = cleaned_data.get("audience")

        if (
            audience == AdminNotificationCampaign.Audience.INACTIVE_USERS
            and not cleaned_data.get("inactive_days")
        ):
            self.add_error(
                "inactive_days",
                "Укажите количество дней неактивности.",
            )

        if (
            audience == AdminNotificationCampaign.Audience.TOURNAMENT_PARTICIPANTS
            and not cleaned_data.get("tournament")
        ):
            self.add_error(
                "tournament",
                "Выберите турнир для этой аудитории.",
            )

        return cleaned_data
