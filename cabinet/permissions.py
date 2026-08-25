from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import User


def role_required(role: str):
    """Require an authenticated user with the requested cabinet role."""

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped(request, *args, **kwargs):
            if request.user.role != role:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


analyst_required = role_required(User.Role.ANALYST)
reader_required = role_required(User.Role.READER)
