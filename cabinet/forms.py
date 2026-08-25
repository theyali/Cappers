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
        widgets = {
            "first_name": forms.TextInput(attrs={"placeholder": "Имя"}),
            "last_name": forms.TextInput(attrs={"placeholder": "Фамилия"}),
            "email": forms.EmailInput(attrs={"placeholder": "name@example.com"}),
        }

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        queryset = User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError("Пользователь с таким email уже существует.")
        return email


class AnalystProfileForm(forms.ModelForm):
    class Meta:
        model = AnalystProfile
        fields = ("display_name", "bio", "is_public")
        widgets = {
            "display_name": forms.TextInput(attrs={"placeholder": "Имя, которое увидят другие"}),
            "bio": forms.Textarea(
                attrs={
                    "rows": 6,
                    "placeholder": "Расскажите немного о себе и своей спортивной специализации",
                }
            ),
        }


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
