import re

from django import forms
from django.contrib.auth.forms import PasswordResetForm

from cabinet.models import User


CODE_RE = re.compile(r"^\d{6}$")


class EmailAddressForm(forms.Form):
    new_email = forms.EmailField(
        label="Новая почта",
        widget=forms.EmailInput(attrs={"placeholder": "name@example.com", "autocomplete": "email"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_new_email(self):
        email = self.cleaned_data["new_email"].strip().lower()
        if self.user and self.user.email and self.user.email.lower() == email:
            raise forms.ValidationError("Эта почта уже привязана к вашему аккаунту.")
        if User.objects.filter(email__iexact=email).exclude(pk=getattr(self.user, "pk", None)).exists():
            raise forms.ValidationError("Пользователь с такой почтой уже существует.")
        return email


class EmailCodeForm(forms.Form):
    code = forms.CharField(
        label="Код подтверждения",
        min_length=6,
        max_length=6,
        widget=forms.TextInput(
            attrs={
                "placeholder": "000000",
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
            }
        ),
    )

    def clean_code(self):
        code = re.sub(r"\s+", "", self.cleaned_data["code"])
        if not CODE_RE.match(code):
            raise forms.ValidationError("Введите шестизначный код.")
        return code


class AccountPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        label="Адрес электронной почты",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
                "placeholder": "name@example.com",
            }
        ),
    )

    def save(self, *, request=None, **kwargs):
        from .services import start_password_reset

        if request is None:
            raise ValueError("request is required for password reset")

        email = self.cleaned_data["email"]
        for user in self.get_users(email):
            start_password_reset(user, request=request)
