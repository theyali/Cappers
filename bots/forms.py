from django import forms

from cabinet.forms import AnalystProfileForm, UserProfileForm
from cabinet.models import AnalystProfile, User

from .models import BotAccount


class BotAccountProfileForm(forms.ModelForm):
    avatar = forms.ImageField(
        label="Изображение",
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                "accept": "image/jpeg,image/png,image/webp",
                "class": "avatar-upload-input",
                "aria-label": "Загрузить изображение бота",
            }
        ),
    )
    remove_avatar = forms.BooleanField(
        label="Удалить текущее изображение",
        required=False,
    )

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name")
        widgets = {
            "username": forms.TextInput(
                attrs={
                    "placeholder": "Логин бота",
                    "autocomplete": "off",
                    "aria-label": "Логин бота",
                }
            ),
            "first_name": forms.TextInput(
                attrs={
                    "placeholder": "Имя",
                    "autocomplete": "off",
                    "aria-label": "Имя бота",
                }
            ),
            "last_name": forms.TextInput(
                attrs={
                    "placeholder": "Фамилия",
                    "autocomplete": "off",
                    "aria-label": "Фамилия бота",
                }
            ),
        }

    def __init__(self, *args, bot_account: BotAccount, **kwargs):
        self.bot_account = bot_account
        super().__init__(*args, **kwargs)

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if not username:
            raise forms.ValidationError("Укажите логин бота.")

        duplicate = User.objects.filter(username__iexact=username).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError("Пользователь с таким логином уже существует.")
        return username

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if avatar is None:
            return avatar

        if avatar.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Изображение должно быть не больше 5 МБ.")

        content_type = getattr(avatar, "content_type", "")
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise forms.ValidationError("Разрешены JPG, PNG и WEBP.")
        return avatar

    def save(self, commit=True):
        user = super().save(commit=False)
        avatar = self.cleaned_data.get("avatar")
        remove_avatar = self.cleaned_data.get("remove_avatar", False)

        if avatar is not None:
            user.avatar = avatar
        elif remove_avatar:
            user.avatar = None

        if not commit:
            return user
        user.save()

        if user.role == User.Role.ANALYST:
            analyst_profile, _ = AnalystProfile.objects.get_or_create(user=user)
            if not analyst_profile.display_name:
                analyst_profile.display_name = user.get_full_name() or user.username
                analyst_profile.save(update_fields=("display_name", "updated_at"))

        return user


class BotAccountDetailsForm(BotAccountProfileForm):
    gender = UserProfileForm.base_fields["gender"]
    country = UserProfileForm.base_fields["country"]

    class Meta(BotAccountProfileForm.Meta):
        fields = (*BotAccountProfileForm.Meta.fields, "gender", "country", "email", "telegram_username")
        labels = {"email": "Email", "telegram_username": "Логин Telegram"}

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip()
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Этот email уже используется другим пользователем.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        if "email" in self.changed_data:
            user.email_verified = False
        if commit:
            user.save()
        return user


class BotPublicProfileForm(forms.ModelForm):
    class Meta:
        model = AnalystProfile
        fields = (
            "display_name", "specialization", "bio", "favorite_sports", "favorite_leagues",
            "telegram_channel", "telegram_account", "instagram", "threads", "youtube",
            "tiktok", "facebook", "x", "is_public", "is_verified", "is_recommended",
        )
        widgets = AnalystProfileForm.Meta.widgets


class BotSettingsForm(forms.ModelForm):
    class Meta:
        model = BotAccount
        fields = ("persona", "is_active")
        labels = {"persona": "Персона бота", "is_active": "Автоматическая активность бота включена"}
