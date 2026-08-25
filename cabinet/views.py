from django.contrib.auth.decorators import login_required
from django.http import HttpResponse


@login_required
def dashboard(request):
    """Temporary cabinet entry point. Role-specific UI is added in Stage 3."""
    return HttpResponse("Cabinet")
