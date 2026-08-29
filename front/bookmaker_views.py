from django.shortcuts import render

from back.models import Bookmaker


def bookmakers(request):
    return render(
        request,
        "front/bookmakers.html",
        {
            "bookmakers": Bookmaker.objects.all(),
        },
    )
