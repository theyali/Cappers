from decimal import Decimal

from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import AnalystProfile, User


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(label="Email", required=True)
    role = forms.ChoiceField(
        label="Тип аккаунта",
        choices=User.Role.choices,
        widget=forms.HiddenInput(),
        initial=User.Role.READER,
    )
    accept_terms = forms.BooleanField(
        label="Согласие с правилами",
        required=True,
        error_messages={
            "required": "Для регистрации необходимо принять правила сервиса.",
        },
        widget=forms.CheckboxInput(attrs={"class": "auth-agreement-checkbox"}),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "accept_terms",
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Пользователь с таким email уже существует.")
        return email


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name")
        widgets = {
            "first_name": forms.TextInput(attrs={"placeholder": "Имя"}),
            "last_name": forms.TextInput(attrs={"placeholder": "Фамилия"}),
        }


class AnalystProfileForm(forms.ModelForm):
    class Meta:
        model = AnalystProfile
        fields = (
            "display_name",
            "specialization",
            "bio",
            "favorite_sports",
            "favorite_leagues",
            "telegram_channel",
            "telegram_account",
            "instagram",
            "threads",
            "youtube",
            "tiktok",
            "facebook",
            "paid_predictions_enabled",
            "paid_predictions_price",
            "is_public",
        )
        widgets = {
            "display_name": forms.TextInput(attrs={"placeholder": "Имя, которое увидят другие"}),
            "specialization": forms.TextInput(attrs={"placeholder": "Например: футбольная аналитика, live, тоталы"}),
            "bio": forms.Textarea(
                attrs={
                    "rows": 6,
                    "placeholder": "Расскажите немного о себе и своей спортивной специализации",
                }
            ),
            "favorite_sports": forms.TextInput(attrs={"placeholder": "Футбол, теннис, баскетбол"}),
            "favorite_leagues": forms.TextInput(attrs={"placeholder": "АПЛ, Ла Лига, Лига чемпионов"}),
            "telegram_channel": forms.TextInput(attrs={"placeholder": "Необязательно: @channel или https://t.me/channel"}),
            "telegram_account": forms.TextInput(attrs={"placeholder": "Необязательно: @username или https://t.me/username"}),
            "instagram": forms.TextInput(attrs={"placeholder": "@username или ссылка"}),
            "threads": forms.TextInput(attrs={"placeholder": "@username или ссылка"}),
            "youtube": forms.TextInput(attrs={"placeholder": "@channel или ссылка"}),
            "tiktok": forms.TextInput(attrs={"placeholder": "@username или ссылка"}),
            "facebook": forms.TextInput(attrs={"placeholder": "@username или ссылка"}),
            "paid_predictions_price": forms.NumberInput(
                attrs={
                    "min": "0",
                    "step": "1",
                    "placeholder": "Например: 1990",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["telegram_channel"].required = False
        self.fields["telegram_account"].required = False
        self.fields["paid_predictions_price"].required = False
        self.fields["telegram_channel"].label = "Telegram-канал (необязательно)"
        self.fields["telegram_account"].label = "Telegram-аккаунт (необязательно)"
        self.fields["paid_predictions_enabled"].label = "Платные прогнозы"
        self.fields["paid_predictions_price"].label = "Стоимость в месяц, ₽"

    def clean(self):
        cleaned_data = super().clean()
        paid_enabled = cleaned_data.get("paid_predictions_enabled")
        price = cleaned_data.get("paid_predictions_price")
        if price in (None, ""):
            price = Decimal("0")
            cleaned_data["paid_predictions_price"] = price
        if paid_enabled and price <= 0:
            self.add_error(
                "paid_predictions_price",
                "Укажите стоимость платной подписки.",
            )
        return cleaned_data


class AnalystAvatarForm(forms.ModelForm):
    class Meta:
        model = AnalystProfile
        fields = ("avatar",)

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if not avatar:
            raise forms.ValidationError("Выберите изображение.")

        if avatar.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Максимальный размер файла — 5 МБ.")

        content_type = getattr(avatar, "content_type", "")
        allowed_types = {"image/jpeg", "image/png", "image/webp"}
        if content_type and content_type not in allowed_types:
            raise forms.ValidationError("Разрешены JPG, PNG и WebP.")

        return avatar
