from django.shortcuts import render

from back.models import Bonus, Bookmaker


def bookmakers(request):
    selected_filter = (request.GET.get("filter") or "all").strip().lower()
    selected_sort = (request.GET.get("sort") or "popular").strip().lower()
    bookmakers_queryset = Bookmaker.objects.all()
    if selected_filter == "bonus":
        bookmakers_queryset = bookmakers_queryset.exclude(bonus_text="")
    elif selected_filter == "reliable":
        bookmakers_queryset = bookmakers_queryset.filter(is_reliable=True)
    elif selected_filter == "popular":
        bookmakers_queryset = bookmakers_queryset.filter(is_popular=True)
    elif selected_filter == "newbie":
        bookmakers_queryset = bookmakers_queryset.filter(for_beginners=True)
    elif selected_filter == "mobile":
        bookmakers_queryset = bookmakers_queryset.filter(has_mobile_app=True)
    else:
        selected_filter = "all"

    if selected_sort == "name":
        bookmakers_queryset = bookmakers_queryset.order_by("name", "id")
    elif selected_sort == "bonus":
        bookmakers_queryset = bookmakers_queryset.order_by("-bonus_text", "order", "id")
    else:
        selected_sort = "popular"
        bookmakers_queryset = bookmakers_queryset.order_by("-is_popular", "order", "id")

    return render(
        request,
        "front/bookmakers.html",
        {
            "bookmakers": bookmakers_queryset,
            "bookmaker_filter": selected_filter,
            "bookmaker_sort": selected_sort,
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
