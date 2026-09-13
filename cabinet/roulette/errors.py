from django.core.exceptions import ValidationError


class RouletteSpinError(ValidationError):
    """Expected roulette spin failure that can be safely exposed by the API."""


def roulette_error(message: str, code: str) -> RouletteSpinError:
    return RouletteSpinError(message, code=code)
