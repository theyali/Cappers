from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from cabinet.models import CapperArticle, User
from front.models import Article, News
from game.models import Match


class StaticViewSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.8

    def items(self):
        return (
            "front:sports_news",
            "front:articles",
            "game:match_list",
        )

    def location(self, item):
        return reverse(item)


class ArticleSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.7

    def items(self):
        return (
            Article.objects.filter(is_published=True)
            .only("slug", "updated_at")
            .order_by("-updated_at", "-id")
        )

    def lastmod(self, obj):
        return obj.updated_at


class CapperArticleSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.6

    def items(self):
        return (
            CapperArticle.objects.filter(
                status=CapperArticle.Status.APPROVED,
                author__role=User.Role.ANALYST,
                author__analyst_profile__is_public=True,
            )
            .select_related("author")
            .only("pk", "slug", "updated_at", "author__username")
            .order_by("-updated_at", "-id")
        )

    def lastmod(self, obj):
        return obj.updated_at


class NewsSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.8

    def items(self):
        return (
            News.objects.filter(is_published=True)
            .only("slug", "updated_at")
            .order_by("-updated_at", "-id")
        )

    def lastmod(self, obj):
        return obj.updated_at


class MatchSitemap(Sitemap):
    changefreq = "hourly"
    priority = 0.6

    def items(self):
        return (
            Match.objects.exclude(slug__isnull=True)
            .exclude(slug="")
            .only("slug", "updated_at")
            .order_by("-updated_at", "-id")
        )

    def lastmod(self, obj):
        return obj.updated_at


sitemaps = {
    "static": StaticViewSitemap,
    "articles": ArticleSitemap,
    "capper-articles": CapperArticleSitemap,
    "news": NewsSitemap,
    "matches": MatchSitemap,
}
