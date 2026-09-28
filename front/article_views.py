from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from .models import Article, ArticleCategory, News, NewsCategory


ARTICLES_PAGE_SIZE = 9
SPORTS_NEWS_PAGE_SIZE = ARTICLES_PAGE_SIZE


def articles(request):
    categories = ArticleCategory.objects.filter(is_active=True)
    selected_category = None
    queryset = Article.objects.filter(is_published=True).select_related("category")
    category_slug = request.GET.get("category") or ""
    if category_slug:
        selected_category = get_object_or_404(categories, slug=category_slug)
        queryset = queryset.filter(category=selected_category)

    queryset = queryset.order_by("-is_main", "-created_at", "-id")
    paginator = Paginator(queryset, ARTICLES_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    return render(
        request,
        "front/articles.html",
        {
            "page_obj": page_obj,
            "article_categories": categories,
            "selected_category": selected_category,
            "total_articles": paginator.count,
        },
    )


def sports_news(request):
    categories = NewsCategory.objects.filter(is_active=True)
    selected_category = None
    queryset = News.objects.filter(is_published=True).select_related("category")
    category_slug = request.GET.get("category") or ""
    if category_slug:
        selected_category = get_object_or_404(categories, slug=category_slug)
        queryset = queryset.filter(category=selected_category)

    queryset = queryset.order_by("-is_main", "-created_at", "-id")
    paginator = Paginator(queryset, SPORTS_NEWS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    return render(
        request,
        "front/sports_news.html",
        {
            "page_obj": page_obj,
            "news_categories": categories,
            "selected_category": selected_category,
            "total_news": paginator.count,
        },
    )


def news_detail(request, slug: str):
    article = get_object_or_404(
        News.objects.select_related("category"),
        slug=slug,
        is_published=True,
    )
    related_articles = (
        News.objects.filter(is_published=True)
        .select_related("category")
        .exclude(pk=article.pk)
        .order_by("-created_at", "-id")[:3]
    )
    return render(
        request,
        "front/article_detail.html",
        {
            "article": article,
            "related_articles": related_articles,
            "article_back_url_name": "front:sports_news",
            "article_back_label": "Все новости",
            "article_detail_source": "Новости спорта",
            "related_eyebrow": "Дальше",
            "related_title": "Ещё новости",
            "related_all_label": "Все новости",
        },
    )


def article_detail(request, slug: str):
    article = get_object_or_404(
        Article.objects.select_related("category"),
        slug=slug,
        is_published=True,
    )
    related_articles = (
        Article.objects.filter(is_published=True)
        .select_related("category")
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
