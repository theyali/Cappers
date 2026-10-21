from django.core.paginator import Paginator
from django.db.models import BooleanField, CharField, DateTimeField, F, Q, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse

from cabinet.models import CapperArticle, User

from .models import Article, ArticleCategory, News, NewsCategory


ARTICLES_PAGE_SIZE = 9
# Columns of a listing row; editorial and capper articles share them in one sorted union.
ARTICLE_SORT_OPTIONS = {
    "new": ("-is_main", "-published", "-id"),
    "old": ("is_main", "published", "id"),
    "read_time": ("reading_time_minutes", "-published", "-id"),
}
ARTICLE_SOURCES = (("", "Все"), ("editorial", "Редакция"), ("cappers", "Капперы"))
EDITORIAL, CAPPER = "editorial", "capper"


def _is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _base_querystring(request):
    query = request.GET.copy()
    query.pop("page", None)
    return query.urlencode()


def _search_q(query: str, description_field: str) -> Q:
    return (
        Q(title__icontains=query)
        | Q(**{f"{description_field}__icontains": query})
        | Q(tags__icontains=query)
        | Q(category__name__icontains=query)
    )


def _filter_publications(request, *, rows, category_model):
    """Category, search, sort and page over listing rows: a callable (category, query) -> queryset
    of values with the ARTICLE_SORT_OPTIONS columns and "id"."""
    categories = category_model.objects.filter(is_active=True)
    selected_category = None
    category_slug = request.GET.get("category") or ""
    if category_slug:
        selected_category = get_object_or_404(categories, slug=category_slug)
    search_query = (request.GET.get("q") or "").strip()

    sort = request.GET.get("sort") or "new"
    if sort not in ARTICLE_SORT_OPTIONS:
        sort = "new"

    paginator = Paginator(rows(selected_category, search_query).order_by(*ARTICLE_SORT_OPTIONS[sort]), ARTICLES_PAGE_SIZE)
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


def _news_rows(category, query):
    queryset = News.objects.filter(is_published=True)
    if category:
        queryset = queryset.filter(category=category)
    if query:
        queryset = queryset.filter(_search_q(query, "description"))
    return queryset.select_related("category").annotate(published=F("created_at"))


def _public_capper_articles():
    return CapperArticle.objects.filter(
        status=CapperArticle.Status.APPROVED,
        author__role=User.Role.ANALYST,
        author__analyst_profile__is_public=True,
    )


def _article_rows(source: str):
    def rows(category, query):
        editorial = Article.objects.filter(is_published=True)
        cappers = _public_capper_articles()
        if category:
            editorial = editorial.filter(category=category)
            cappers = cappers.filter(category=category)
        if query:
            editorial = editorial.filter(_search_q(query, "description"))
            cappers = cappers.filter(_search_q(query, "excerpt"))
        if source == "editorial":
            cappers = cappers.none()
        elif source == "cappers":
            editorial = editorial.none()
        columns = ("id", "reading_time_minutes", "kind", "published", "is_main")
        editorial = editorial.annotate(
            kind=Value(EDITORIAL, output_field=CharField()),
            published=F("created_at"),
        ).values(*columns)
        cappers = cappers.annotate(
            kind=Value(CAPPER, output_field=CharField()),
            published=Coalesce("published_at", "created_at", output_field=DateTimeField()),
            is_main=Value(False, output_field=BooleanField()),
        ).values(*columns)
        return editorial.union(cappers, all=True)

    return rows


def _article_page_items(rows) -> list:
    """The page's union rows as Article and CapperArticle objects, in the page's order."""
    ids = {EDITORIAL: [], CAPPER: []}
    for row in rows:
        ids[row["kind"]].append(row["id"])
    editorial = Article.objects.select_related("category").in_bulk(ids[EDITORIAL])
    cappers = CapperArticle.objects.select_related("category", "author", "author__analyst_profile").in_bulk(ids[CAPPER])
    items = []
    for row in rows:
        if row["kind"] == EDITORIAL:
            items.append(editorial[row["id"]])
            continue
        article = cappers[row["id"]]
        article.author_name = str(article.author.analyst_profile)
        article.author_url = reverse("front:expert_profile", args=[article.author.username])
        items.append(article)
    return items


def _source_tabs(request, current: str) -> list[dict]:
    tabs = []
    for value, label in ARTICLE_SOURCES:
        query = request.GET.copy()
        query.pop("page", None)
        query.pop("source", None)
        if value:
            query["source"] = value
        tabs.append({"label": label, "value": value, "active": value == current, "url": f"?{query.urlencode()}" if query else "?"})
    return tabs


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
    source = request.GET.get("source") or ""
    if source not in dict(ARTICLE_SOURCES):
        source = ""
    listing_context = _filter_publications(
        request,
        rows=_article_rows(source),
        category_model=ArticleCategory,
    )
    page_obj = listing_context["page_obj"]
    page_obj.object_list = _article_page_items(list(page_obj.object_list))
    listing_context.update(
        {
            "current_source": source,
            "source_tabs": _source_tabs(request, source),
            "article_categories": listing_context["categories"],
            "total_articles": listing_context["total_count"],
            "page_title": "Все статьи",
            "page_intro": "Аналитика, стратегии и разборы от редакции и капперов КапперХаб.",
            "page_kind": "articles",
            "list_url_name": "front:articles",
            "read_label": "Читать статью",
            "empty_title": "Статей пока нет",
            "empty_text": "Новые материалы редакции и капперов появятся здесь после публикации.",
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
        rows=_news_rows,
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


def capper_article_detail(request, username: str, article_id: int, slug: str):
    article = get_object_or_404(
        _public_capper_articles().select_related("category", "author", "author__analyst_profile"),
        pk=article_id,
        author__username=username,
    )
    if article.slug != slug:
        return redirect(article.get_absolute_url(), permanent=True)

    related_articles = (
        _public_capper_articles().filter(author=article.author)
        .exclude(pk=article.pk)
        .order_by("-published_at", "-id")[:3]
    )
    author_name = str(article.author.analyst_profile)
    return render(
        request,
        "front/article_detail.html",
        {
            "article": article,
            "related_articles": related_articles,
            "article_detail_source": author_name,
            "article_author_url": reverse("front:expert_profile", args=[username]),
            "related_eyebrow": "Ещё от каппера",
            "related_title": f"Статьи: {author_name}",
            "related_all_label": "Все статьи",
        },
    )
