from django.shortcuts import render

from back.models import Bonus, Bookmaker


def bookmakers(request):
    return render(
        request,
        "front/bookmakers.html",
        {
            "bookmakers": Bookmaker.objects.all(),
        },
    )


def bonuses(request):
    return render(
        request,
        "front/bonuses.html",
        {
            "bonuses": Bonus.objects.select_related("bookmaker").all(),
        },
    )
