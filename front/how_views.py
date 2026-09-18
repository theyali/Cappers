from django.shortcuts import render


def how_it_works(request):
    context={
        'page_class':"how_it_works"
    }
    return render(request, "front/how_it_works.html", context)
