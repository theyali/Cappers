from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from .models import Article


ARTICLES_PAGE_SIZE = 9


def articles(request):
    queryset = Article.objects.filter(is_published=True).order_by("-created_at", "-id")
    paginator = Paginator(queryset, ARTICLES_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    return render(
        request,
        "front/articles.html",
        {
            "page_obj": page_obj,
            "total_articles": paginator.count,
        },
    )


def article_detail(request, slug: str):
    article = get_object_or_404(Article, slug=slug, is_published=True)
    related_articles = (
        Article.objects.filter(is_published=True)
        .exclude(pk=article.pk)
        .order_by("-created_at", "-id")[:3]
    )
    return render(
        request,
        "front/article_detail.html",
        {
            "article": article,
            "related_articles": related_articles,
        },
    )
