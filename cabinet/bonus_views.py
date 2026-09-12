from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def bonuses(request):
    return render(
        request,
        "cabinet/bonuses.html",
        {
            "active_tab": "bonuses",
            "page_class": "cabinet-bonuses-page",
        },
    )
