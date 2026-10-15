from django import forms


class LeaderAwardCorrectionForm(forms.Form):
    expected_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    reason = forms.CharField(
        label="Причина исправления",
        min_length=10,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Текущие медали будут отозваны с сохранением истории, результаты месяца пересчитаны и награды выданы заново.",
    )
