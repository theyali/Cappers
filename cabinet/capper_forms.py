from django import forms


class CapperIdentityForm(forms.Form):
    first_name = forms.CharField(label="Имя", max_length=150, required=False)
    last_name = forms.CharField(label="Фамилия", max_length=150, required=False)
    display_name = forms.CharField(
        label="Публичное имя",
        max_length=120,
        help_text="Так вас увидят в рейтинге, прогнозах и публичном профиле.",
    )
    avatar = forms.ImageField(
        label="Фото профиля",
        required=False,
        help_text="JPG, PNG или WebP до 5 МБ.",
    )

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if not avatar:
            return avatar
        if avatar.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Максимальный размер файла — 5 МБ.")
        content_type = getattr(avatar, "content_type", "")
        if content_type and content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise forms.ValidationError("Разрешены JPG, PNG и WebP.")
        return avatar


class CapperAboutForm(forms.Form):
    specialization = forms.CharField(
        label="Чем вы занимаетесь",
        max_length=220,
        widget=forms.TextInput(
            attrs={"placeholder": "Например: футбольная аналитика, live, тоталы"}
        ),
    )
    bio = forms.CharField(
        label="О себе",
        max_length=2000,
        widget=forms.Textarea(
            attrs={
                "rows": 7,
                "placeholder": "Опишите подход к прогнозам, опыт и то, что отличает вашу аналитику.",
            }
        ),
    )


class CapperFocusForm(forms.Form):
    favorite_sports = forms.CharField(
        label="Любимые виды спорта",
        max_length=320,
        widget=forms.TextInput(attrs={"placeholder": "Футбол, теннис, баскетбол"}),
        help_text="Можно перечислить через запятую.",
    )
    favorite_leagues = forms.CharField(
        label="Любимые лиги",
        max_length=500,
        required=False,
        widget=forms.TextInput(
            attrs={"placeholder": "АПЛ, Ла Лига, Лига чемпионов, ATP"}
        ),
        help_text="Это поможет пользователям быстрее понять вашу специализацию.",
    )


class CapperSocialsForm(forms.Form):
    telegram_channel = forms.CharField(
        label="Telegram-канал",
        max_length=160,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "@channel или https://t.me/channel"}),
    )
    telegram_account = forms.CharField(
        label="Telegram-аккаунт",
        max_length=160,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "@username или https://t.me/username"}),
    )
    instagram = forms.CharField(
        label="Instagram",
        max_length=160,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "@username или ссылка"}),
    )
    youtube = forms.CharField(
        label="YouTube",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "@channel или ссылка"}),
    )
    tiktok = forms.CharField(
        label="TikTok",
        max_length=160,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "@username или ссылка"}),
    )
