from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        READER = "reader", "Пользователь"
        ANALYST = "analyst", "Аналитик"

    role = models.CharField(
        "Роль",
        max_length=16,
        choices=Role.choices,
        default=Role.READER,
        db_index=True,
    )

    @property
    def is_analyst(self) -> bool:
        return self.role == self.Role.ANALYST
