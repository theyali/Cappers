from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string

from .models import Article, ArticleCategory, News, NewsCategory


ARTICLES_PAGE_SIZE = 9
ARTICLE_SORT_OPTIONS = {
    "new": ("-is_main", "-created_at", "-id"),
    "old": ("is_main", "created_at", "id"),
    "read_time": ("reading_time_minutes", "-created_at", "-id"),
}


def _is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _base_querystring(request):
    query = request.GET.copy()
    query.pop("page", None)
    return query.urlencode()


def _filter_publications(request, *, model, category_model):
    categories = category_model.objects.filter(is_active=True)
    selected_category = None
    queryset = model.objects.filter(is_published=True).select_related("category")

    category_slug = request.GET.get("category") or ""
    if category_slug:
        selected_category = get_object_or_404(categories, slug=category_slug)
        queryset = queryset.filter(category=selected_category)

    search_query = (request.GET.get("q") or "").strip()
    if search_query:
        queryset = queryset.filter(
            Q(title__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(tags__icontains=search_query)
            | Q(category__name__icontains=search_query)
        )

    sort = request.GET.get("sort") or "new"
    if sort not in ARTICLE_SORT_OPTIONS:
        sort = "new"

    queryset = queryset.order_by(*ARTICLE_SORT_OPTIONS[sort])
    paginator = Paginator(queryset, ARTICLES_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page") or 1)

    return {
        "categories": categories,
        "selected_category": selected_category,
        "selected_category_slug": selected_category.slug if selected_category else "",
        "current_query": search_query,
        "current_sort": sort,
        "page_obj": page_obj,
        "total_count": paginator.count,
        "base_querystring": _base_querystring(request),
    }


def _render_publication_listing(request, *, template_name, context):
    if _is_ajax(request):
        html = render_to_string(
            "front/includes/_articles_results.html",
            context,
            request=request,
        )
        return JsonResponse({"html": html, "total": context["total_count"]})

    return render(request, template_name, context)


def articles(request):
    listing_context = _filter_publications(
        request,
        model=Article,
        category_model=ArticleCategory,
    )
    listing_context.update(
        {
            "article_categories": listing_context["categories"],
            "total_articles": listing_context["total_count"],
            "page_title": "Все статьи",
            "page_intro": "Актуальные материалы, аналитика и советы от экспертов КапперХаб.",
            "page_kind": "articles",
            "list_url_name": "front:articles",
            "read_label": "Читать статью",
            "empty_title": "Статей пока нет",
            "empty_text": "Новые материалы появятся здесь после публикации через админку.",
            "search_placeholder": "Поиск по статьям...",
            "all_category_label": "Все статьи",
            "breadcrumbs": [],
        }
    )
    return _render_publication_listing(
        request,
        template_name="front/articles.html",
        context=listing_context,
    )


def sports_news(request):
    listing_context = _filter_publications(
        request,
        model=News,
        category_model=NewsCategory,
    )
    listing_context.update(
        {
            "news_categories": listing_context["categories"],
            "total_news": listing_context["total_count"],
            "page_title": "Новости спорта",
            "page_intro": "Свежие материалы о матчах, командах, турнирах и главных событиях спортивного дня.",
            "page_kind": "news",
            "list_url_name": "front:sports_news",
            "read_label": "Читать новость",
            "empty_title": "Новостей пока нет",
            "empty_text": "Новые спортивные материалы появятся здесь после публикации.",
            "search_placeholder": "Поиск по новостям...",
            "all_category_label": "Все новости",
            "breadcrumbs": [],
        }
    )
    return _render_publication_listing(
        request,
        template_name="front/sports_news.html",
        context=listing_context,
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
