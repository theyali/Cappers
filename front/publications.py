from html import escape
from html.parser import HTMLParser
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

from cabinet.comments.models import Comment, CommentReaction
from cabinet.comments.services import validate_comment_text
from cabinet.models import AnalystFollow, CapperArticle, User
from cabinet.paid_predictions import user_can_view_paid_coupon
from front.models import Article, News, PublicationReaction
from game.models import PredictionCoupon
from game.services.bet_options import compact_pick_label
from game.services.coupon_validation import coupon_total_coefficient
from front.prediction_metrics import annotate_author_roi
from cabinet.vip import plural_ru


class PublicationHTML(HTMLParser):
    """Keep complete top-level blocks while assigning stable heading anchors."""

    VOID = {
        "area",
        "base",
        "br",
        "col",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self, content):
        super().__init__(convert_charrefs=False)
        self.stack, self.current, self.fragments, self.headings = [], [], [], []
        self.heading = None
        self.suppressed = 0
        self.feed(content or "")
        self.flush()

    def flush(self):
        if self.current:
            self.fragments.append("".join(self.current))
            self.current = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "object"}:
            self.suppressed += 1
            return
        if self.suppressed:
            return
        attrs = [
            (key, value)
            for key, value in attrs
            if not key.lower().startswith("on")
            and key.lower() != "srcdoc"
            and not (
                key in {"href", "src"}
                and (value or "")
                .strip()
                .lower()
                .startswith(("javascript:", "data:text/html"))
            )
        ]
        if tag in {"h2", "h3"}:
            anchor = dict(attrs).get("id") or f"section-{len(self.headings) + 1}"
            attrs = [(key, value) for key, value in attrs if key != "id"] + [
                ("id", anchor)
            ]
            self.heading = {"title": "", "anchor": anchor}
            self.headings.append(self.heading)
        if tag == "table":
            self.current.append(
                '<div class="publication-table" tabindex="0" role="region" aria-label="Таблица в материале">'
            )
        self.current.append(
            "<"
            + tag
            + "".join(
                f' {key}="{escape(value or "", quote=True)}"' for key, value in attrs
            )
            + ">"
        )
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "object"} and self.suppressed:
            self.suppressed -= 1
            return
        if self.suppressed:
            return
        self.current.append(f"</{tag}>")
        if tag == "table":
            self.current.append("</div>")
        if tag in {"h2", "h3"}:
            self.heading = None
        if tag in self.stack:
            self.stack = self.stack[: len(self.stack) - 1 - self.stack[::-1].index(tag)]
        if not self.stack:
            self.flush()

    def handle_data(self, data):
        if not self.suppressed:
            self.current.append(escape(data))
            if self.heading is not None:
                self.heading["title"] += data

    def handle_entityref(self, name):
        from html import unescape

        self.handle_data(unescape(f"&{name};"))

    def handle_charref(self, name):
        from html import unescape

        self.handle_data(unescape(f"&#{name};"))


def publication_body(article, viewer):
    parsed = PublicationHTML(article.content)
    toc = []
    for line in article.table_of_contents.splitlines():
        title = line.strip().lstrip("# ")
        heading = next(
            (
                item
                for item in parsed.headings
                if item["title"].strip().casefold() == title.casefold()
            ),
            None,
        )
        if heading and heading not in toc:
            toc.append(heading)
    inserts = []
    if article.inline_image:
        inserts.append((article.inline_image_after_paragraph, {"kind": "image"}))
    if article.pull_quote:
        inserts.append((article.quote_after_paragraph, {"kind": "quote"}))
    if article.related_link_url and article.related_link_title:
        inserts.append((article.related_link_after_paragraph, {"kind": "link"}))
    if article.summary:
        inserts.append((article.summary_after_paragraph, {"kind": "summary"}))
    coupon = article.featured_prediction
    prediction = None
    if coupon and coupon.published_status == PredictionCoupon.PublishedStatus.PUBLISHED:
        positions = list(
            coupon.predictions.select_related(
                "match__home_team",
                "match__away_team",
                "match__league",
                "match__sport",
            ).order_by("pk")
        )
        if positions:
            pick = positions[0]
            can_view = (
                coupon.audience != PredictionCoupon.Audience.PAID
                or user_can_view_paid_coupon(viewer, coupon)
            )
            prediction = {
                "url": reverse(
                    "front:prediction_detail", kwargs={"prediction_id": coupon.pk}
                ),
                "match": pick.match,
                "selection": (
                    f"Экспресс · {len(positions)} игр"
                    if len(positions) > 1
                    else compact_pick_label(pick)
                )
                if can_view
                else "Платный прогноз",
                "coefficient": coupon_total_coefficient(
                    [{"coefficient": item.coefficient} for item in positions]
                )
                if can_view
                else None,
                "sport_code": "express"
                if len(positions) > 1
                else pick.match.sport_code,
            }
            inserts.append((article.prediction_after_paragraph, {"kind": "prediction"}))
    blocks, paragraphs = [], 0
    for fragment in parsed.fragments:
        blocks.append({"kind": "html", "html": fragment})
        paragraphs += fragment.lower().count("</p>")
        for position, block in list(inserts):
            if paragraphs >= max(1, position):
                blocks.append(block)
                inserts.remove((position, block))
    blocks.extend(block for _, block in inserts)
    return {
        "publication_blocks": blocks,
        "publication_toc": toc,
        "publication_toc_count_label": f"{len(toc)} {plural_ru(len(toc), 'раздел', 'раздела', 'разделов')}",
        "publication_prediction": prediction,
    }


def publication_author(article, viewer):
    author = getattr(article, "author", None)
    if not author or not author.is_analyst:
        return None
    profile = getattr(author, "analyst_profile", None)
    if not profile or not profile.is_public:
        return None
    stats = (
        annotate_author_roi(
            User.objects.filter(pk=author.pk),
            author_outer_ref="pk",
            annotation_name="publication_roi",
            period_days=None,
        )
        .annotate(
            predictions=Count(
                "prediction_coupons",
                filter=Q(prediction_coupons__published_status="published"),
            )
        )
        .values("publication_roi", "predictions")
        .get()
    )
    total = CapperArticle.objects.filter(
        author=author, status=CapperArticle.Status.APPROVED
    ).count()
    total += Article.objects.filter(author=author, is_published=True).count()
    return {
        "user": author,
        "name": profile.display_name or author.get_full_name() or author.username,
        "url": reverse("front:expert_profile", args=[author.username]),
        "bio": profile.bio,
        "specialization": profile.specialization,
        "verified": profile.is_verified,
        "vip": author.is_vip,
        "followers": AnalystFollow.objects.filter(analyst=author).count(),
        "predictions": stats["predictions"] or 0,
        "roi": round(stats["publication_roi"], 1),
        "articles_count": total,
        "is_following": bool(
            viewer.is_authenticated
            and AnalystFollow.objects.filter(follower=viewer, analyst=author).exists()
        ),
        "can_follow": author.pk != getattr(viewer, "pk", None),
    }


def public_publications(model):
    if model is CapperArticle:
        return model.objects.filter(
            status=CapperArticle.Status.APPROVED,
            author__role="analyst",
            author__analyst_profile__is_public=True,
        )
    return model.objects.filter(is_published=True)


def publication_action(request, article):
    if not request.user.is_authenticated:
        return redirect(
            f"{reverse('cabinet:login')}?{urlencode({'next': article.get_absolute_url()})}"
        )
    content_type = ContentType.objects.get_for_model(article)
    action = request.POST.get("action")
    try:
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            if action in {"like", "bookmark"}:
                reaction, _ = PublicationReaction.objects.get_or_create(
                    user=request.user, content_type=content_type, object_id=article.pk
                )
                field = "is_liked" if action == "like" else "is_bookmarked"
                setattr(reaction, field, not getattr(reaction, field))
                reaction.save(update_fields=[field])
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse(
                        {
                            "ok": True,
                            "active": getattr(reaction, field),
                            "likes": article.publication_reactions.filter(
                                is_liked=True
                            ).count(),
                        }
                    )
            elif action == "comment" and article.comments_enabled:
                parent = None
                if request.POST.get("parent_id"):
                    parent = article.publication_comments.filter(
                        pk=request.POST["parent_id"], status=Comment.Status.PUBLISHED
                    ).first()
                    if parent is None:
                        raise ValidationError("Комментарий для ответа не найден.")
                moderation = validate_comment_text(
                    request.POST.get("text", ""), request.user, target=article
                )
                if not moderation.allowed:
                    raise ValidationError(moderation.public_message)
                Comment.objects.create(
                    user=request.user,
                    content_type=content_type,
                    object_id=article.pk,
                    text=moderation.normalized_text,
                    status=Comment.Status.PUBLISHED,
                    parent=parent,
                )
            elif action == "comment_like" and article.comments_enabled:
                comment = article.publication_comments.filter(
                    pk=request.POST.get("comment_id"), status=Comment.Status.PUBLISHED
                ).first()
                if comment is None:
                    raise ValidationError("Комментарий не найден.")
                reaction, created = CommentReaction.objects.get_or_create(
                    comment=comment, user=request.user, defaults={"kind": "like"}
                )
                if not created:
                    if reaction.kind == "like":
                        reaction.delete()
                    else:
                        reaction.kind = "like"
                        reaction.save(update_fields=["kind"])
            else:
                raise ValidationError("Действие недоступно.")
    except (ValidationError, ValueError) as exc:
        message = (
            "; ".join(exc.messages)
            if isinstance(exc, ValidationError)
            else "Некорректные данные запроса."
        )
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "error": message}, status=400)
        messages.error(request, message)
        request.session["publication_comment_draft"] = {
            "target": f"{content_type.pk}:{article.pk}",
            "text": request.POST.get("text", "")[:1000],
        }
    return redirect(article.get_absolute_url() + "#publication-comments")


def build_publication_context(request, article, related):
    content_type = ContentType.objects.get_for_model(article)
    key = f"{content_type.pk}:{article.pk}"
    seen = request.session.get("publication_views", [])
    if key not in seen:
        type(article).objects.filter(pk=article.pk).update(
            views_count=F("views_count") + 1
        )
        article.views_count += 1
        request.session["publication_views"] = [*seen[-199:], key]
    reactions = article.publication_reactions
    reaction = (
        reactions.filter(user=request.user).first()
        if request.user.is_authenticated
        else None
    )
    author = (
        publication_author(article, request.user)
        if not isinstance(article, News)
        else None
    )
    queryset = public_publications(type(article)).select_related("category")
    if isinstance(article, CapperArticle):
        queryset = queryset.select_related("author", "author__analyst_profile")
    neighbors = queryset.order_by("created_at", "pk")
    previous = neighbors.filter(
        Q(created_at__lt=article.created_at)
        | Q(created_at=article.created_at, pk__lt=article.pk)
    ).last()
    following = neighbors.filter(
        Q(created_at__gt=article.created_at)
        | Q(created_at=article.created_at, pk__gt=article.pk)
    ).first()
    comments = (
        article.publication_comments.filter(status=Comment.Status.PUBLISHED)
        .select_related("user", "user__analyst_profile", "parent__user")
        .annotate(likes=Count("reactions", filter=Q(reactions__kind="like")))
        .order_by("-created_at", "-pk")
    )
    comment_page = (
        Paginator(comments, 10).get_page(request.GET.get("comments_page"))
        if article.comments_enabled
        else None
    )
    draft = request.session.pop("publication_comment_draft", {})
    if request.user.is_authenticated and comment_page:
        comment_page.object_list = comment_page.object_list.annotate(
            is_liked=Exists(
                CommentReaction.objects.filter(
                    comment_id=OuterRef("pk"), user=request.user, kind="like"
                )
            ),
        )
    more = []
    if author:
        for model in (Article, CapperArticle):
            rows = public_publications(model).filter(author_id=author["user"].pk)
            if type(article) is model:
                rows = rows.exclude(pk=article.pk)
            more.extend(rows.order_by("-created_at", "-pk")[:3])
        more = sorted(more, key=lambda item: item.created_at, reverse=True)[:3]
    related = related.select_related("category")
    if not isinstance(article, News):
        related = related.select_related("author", "author__analyst_profile")
    back_url = reverse(
        "front:sports_news" if isinstance(article, News) else "front:articles"
    )
    if author:
        author["articles_url"] = (
            reverse("front:articles")
            + "?"
            + urlencode({"author": author["user"].username})
        )
    return {
        **publication_body(article, request.user),
        "publication_author": author,
        "publication_likes": reactions.filter(is_liked=True).count(),
        "publication_liked": bool(reaction and reaction.is_liked),
        "publication_bookmarked": bool(reaction and reaction.is_bookmarked),
        "publication_comments": comment_page,
        "publication_comments_count": comments.count()
        if article.comments_enabled
        else 0,
        "publication_comment_draft": draft.get("text", "")
        if draft.get("target") == key
        else "",
        "publication_previous": previous,
        "publication_next": following,
        "publication_more_author": more,
        "related_articles": list(related),
        "publication_login_url": reverse("cabinet:login")
        + "?"
        + urlencode({"next": article.get_absolute_url()}),
        "publication_category_url": back_url
        + "?"
        + urlencode({"category": article.category.slug})
        if article.category
        else back_url,
        "publication_is_news": isinstance(article, News),
        "breadcrumbs_inside_content": True,
    }
