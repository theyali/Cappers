from django import forms

from cabinet.models import AnalystProfile, User

from .models import BotAccount


class BotAccountProfileForm(forms.ModelForm):
    avatar = forms.ImageField(
        label="Изображение",
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                "accept": "image/jpeg,image/png,image/webp",
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
                }
            ),
            "first_name": forms.TextInput(
                attrs={
                    "placeholder": "Имя",
                    "autocomplete": "off",
                }
            ),
            "last_name": forms.TextInput(
                attrs={
                    "placeholder": "Фамилия",
                    "autocomplete": "off",
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
        if not commit:
            return user

        avatar = self.cleaned_data.get("avatar")
        remove_avatar = self.cleaned_data.get("remove_avatar", False)

        if avatar is not None:
            user.avatar = avatar
        elif remove_avatar:
            user.avatar = None

        user.save()

        if user.role == User.Role.ANALYST:
            analyst_profile, _ = AnalystProfile.objects.get_or_create(user=user)
            analyst_profile.display_name = user.get_full_name() or user.username

            if avatar is not None:
                analyst_profile.avatar.name = user.avatar.name
            elif remove_avatar:
                analyst_profile.avatar = None

            analyst_profile.save(update_fields=("display_name", "avatar", "updated_at"))

        return user
