from django.core.management.base import BaseCommand

from bots.models import BotAccount
from bots.services import (
    EXPERT_NAMES,
    READER_NAMES,
    _expert_bio,
    _telegram_account,
    _telegram_channel,
)
from cabinet.models import User


class Command(BaseCommand):
    help = "Обновляет имена уже созданных бот-пользователей."

    def handle(self, *args, **options):
        updated = 0
        updated += self._rename_group("bot_reader_", READER_NAMES)
        updated += self._rename_group("bot_expert_", EXPERT_NAMES, experts=True)
        self.stdout.write(self.style.SUCCESS(f"Обновлено ботов: {updated}"))

    def _rename_group(self, prefix: str, profiles: list[tuple[str, str]], *, experts: bool = False) -> int:
        updated = 0
        for index, item in enumerate(profiles, start=1):
            full_name, new_username = item
            legacy_username = f"{prefix}{index:03d}"
            bot = (
                BotAccount.objects.select_related("user")
                .filter(user__username__in=[legacy_username, new_username])
                .first()
            )
            if bot is None:
                continue

            first_name, _, last_name = full_name.partition(" ")
            user = bot.user
            user.username = self._available_username(new_username, user.pk)
            user.first_name = first_name
            user.last_name = last_name
            user.email = f"{user.username}@bots.cappers.local"
            user.save(update_fields=["username", "first_name", "last_name", "email"])

            bot.persona = full_name
            bot.save(update_fields=["persona", "updated_at"])

            if experts and hasattr(user, "analyst_profile"):
                profile = user.analyst_profile
                profile.display_name = full_name
                profile.bio = _expert_bio(index, full_name)
                profile.telegram_channel = _telegram_channel(user.username)
                profile.telegram_account = _telegram_account(user.username)
                profile.save(
                    update_fields=[
                        "display_name",
                        "bio",
                        "telegram_channel",
                        "telegram_account",
                        "updated_at",
                    ]
                )
            updated += 1
        return updated

    def _available_username(self, username: str, user_id: int) -> str:
        if not User.objects.exclude(pk=user_id).filter(username=username).exists():
            return username
        suffix = 2
        while User.objects.exclude(pk=user_id).filter(username=f"{username}{suffix}").exists():
            suffix += 1
        return f"{username}{suffix}"
