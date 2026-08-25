from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import AnalystProfile, User


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(label="Email", required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Пользователь с таким email уже существует.")
        return email


class UserProfileForm(forms.ModelForm):
    email = forms.EmailField(label="Email", required=True)

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        queryset = User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError("Пользователь с таким email уже существует.")
        return email


class AnalystProfileForm(forms.ModelForm):
    class Meta:
        model = AnalystProfile
        fields = ("display_name", "avatar", "bio", "is_public")
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 6}),
        }
