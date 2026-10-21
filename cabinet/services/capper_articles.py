from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import slugify

from cabinet.comments.services.anti_spam import check_comment_spam
from cabinet.comments.services.moderation import (
    contains_forbidden_link,
    contains_profanity,
    normalize_comment_text,
)
from cabinet.models import CapperArticle, CapperArticleDailyUsage, User
from cabinet.vip import get_active_vip


_CYRILLIC_TRANSLIT = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "c",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
        "А": "A",
        "Б": "B",
        "В": "V",
        "Г": "G",
        "Д": "D",
        "Е": "E",
        "Ё": "E",
        "Ж": "Zh",
        "З": "Z",
        "И": "I",
        "Й": "Y",
        "К": "K",
        "Л": "L",
        "М": "M",
        "Н": "N",
        "О": "O",
        "П": "P",
        "Р": "R",
        "С": "S",
        "Т": "T",
        "У": "U",
        "Ф": "F",
        "Х": "H",
        "Ц": "C",
        "Ч": "Ch",
        "Ш": "Sh",
        "Щ": "Sch",
        "Ъ": "",
        "Ы": "Y",
        "Ь": "",
        "Э": "E",
        "Ю": "Yu",
        "Я": "Ya",
    }
)


MAX_ARTICLE_TAGS = 5
MAX_ARTICLE_TAG_LENGTH = 30
EXCERPT_MAX_LENGTH = 300
WORDS_PER_MINUTE = 200
DEFAULT_DAILY_ARTICLE_LIMIT = 2


def get_article_daily_limit(user, *, at=None) -> int:
    subscription = get_active_vip(user, at=at)
    return subscription.plan.daily_article_limit if subscription and subscription.plan else DEFAULT_DAILY_ARTICLE_LIMIT


def build_article_daily_quota(user, *, at=None) -> dict:
    now = at or timezone.now()
    limit = get_article_daily_limit(user, at=now)
    used = CapperArticleDailyUsage.objects.filter(author=user, date=timezone.localdate(now)).values_list("submitted_count", flat=True).first() or 0
    return {"limit": limit, "used": used, "remaining": max(0, limit - used)}


def article_reading_minutes(content: str) -> int:
    return max(1, (len(strip_tags(content or "").split()) + WORDS_PER_MINUTE - 1) // WORDS_PER_MINUTE)


def normalize_article_tags(value: str) -> str:
    """Comma-separated tags without repeats, up to MAX_ARTICLE_TAGS."""
    tags = []
    for raw in str(value or "").split(","):
        tag = normalize_comment_text(raw).strip(" #")[:MAX_ARTICLE_TAG_LENGTH]
        if tag and tag.lower() not in {existing.lower() for existing in tags}:
            tags.append(tag)
    return ", ".join(tags[:MAX_ARTICLE_TAGS])


_ARTICLE_VISUAL_TONES = (
    "football",
    "hockey",
    "basketball",
    "tennis",
    "football-alt",
    "purple",
)


def decorate_capper_articles(articles) -> list:
    decorated = list(articles)
    for index, article in enumerate(decorated):
        article.reading_minutes = article.reading_time_minutes
        article.article_visual_tone = _ARTICLE_VISUAL_TONES[index % len(_ARTICLE_VISUAL_TONES)]
        article.article_views_count = int(getattr(article, "views_count", 0) or 0)
        article.article_comments_count = int(getattr(article, "comments_count", 0) or 0)
    return decorated


def can_create_capper_article(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_analyst", False)
        and getattr(user, "is_vip", False)
    )


def can_edit_capper_article(user, article: CapperArticle) -> bool:
    return bool(
        can_create_capper_article(user)
        and article.author_id == getattr(user, "pk", None)
        and article.status in {
            CapperArticle.Status.DRAFT,
            CapperArticle.Status.REJECTED,
        }
    )


def build_capper_articles_context(user) -> dict:
    is_analyst = bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_analyst", False)
    )
    can_create = can_create_capper_article(user)
    articles = list(
        CapperArticle.objects.filter(author=user)
        .select_related("reviewed_by")
        .order_by("-updated_at", "-id")
    ) if is_analyst else []
    articles = decorate_capper_articles(articles)
    for article in articles:
        article.can_edit = can_edit_capper_article(user, article)

    return {
        "articles": articles,
        "articles_total_count": len(articles),
        "articles_total_views": sum(article.article_views_count for article in articles),
        "articles_approved_count": sum(
            article.status == CapperArticle.Status.APPROVED for article in articles
        ),
        "articles_pending_count": sum(
            article.status == CapperArticle.Status.PENDING for article in articles
        ),
        "articles_draft_count": sum(
            article.status == CapperArticle.Status.DRAFT for article in articles
        ),
        "can_create_article": can_create,
        "active_tab": "articles",
        "vip_locked_label": "Стать VIP, чтобы публиковать статьи",
        "vip_upgrade_url": reverse("cabinet:vip_plans"),
        "article_create_url": reverse("cabinet:capper_article_create"),
        "article_daily_quota": build_article_daily_quota(user) if can_create else None,
    }


@transaction.atomic
def save_capper_article(user, data, files, article=None) -> CapperArticle:
    _ensure_article_access(user)

    if article is not None:
        article = CapperArticle.objects.select_for_update().get(pk=article.pk)
        _ensure_article_owner(user, article)
        if not can_edit_capper_article(user, article):
            raise ValidationError("Редактировать можно только черновик или отклонённую статью.")
    else:
        article = CapperArticle(author=user)

    title = normalize_comment_text(data.get("title", ""))
    excerpt = normalize_comment_text(data.get("excerpt", ""))
    content = str(data.get("content") or "").strip()

    if not title:
        raise ValidationError({"title": "Укажите заголовок статьи."})
    if len(title) > 180:
        raise ValidationError({"title": "Заголовок не может быть длиннее 180 символов."})
    if not normalize_comment_text(strip_tags(content)):
        raise ValidationError({"content": "Добавьте текст статьи."})
    if len(excerpt) > EXCERPT_MAX_LENGTH:
        raise ValidationError({"excerpt": f"Краткое описание не может быть длиннее {EXCERPT_MAX_LENGTH} символов."})

    article.title = title
    article.slug = _article_slug(title)
    article.excerpt = excerpt
    article.content = content
    article.category = data.get("category")
    article.tags = normalize_article_tags(data.get("tags", ""))
    article.reading_time_minutes = article_reading_minutes(content)

    cover_image = files.get("cover_image") if files else None
    if cover_image is not None:
        article.cover_image = cover_image
    elif data.get("cover_image") is False:
        article.cover_image.delete(save=False)
        article.cover_image = None

    if article.status == CapperArticle.Status.REJECTED:
        article.status = CapperArticle.Status.DRAFT
        article.moderation_note = ""
        article.reviewed_by = None
        article.reviewed_at = None
        article.published_at = None

    article.save()
    return article


def _article_slug(title: str) -> str:
    transliterated = str(title or "").translate(_CYRILLIC_TRANSLIT)
    return slugify(transliterated, allow_unicode=False)[:220] or "article"


# Field order of the editor, for the error summary at the top.
EDITOR_FIELDS = ("cover_image", "title", "excerpt", "category", "tags", "content")


def build_article_editor_context(user, form, article=None) -> dict:
    profile = getattr(user, "analyst_profile", None)
    author_name = str(profile) if profile else user.get_full_name() or user.username
    errors = [(None, error) for error in form.non_field_errors()]
    for name in EDITOR_FIELDS:
        label = form.fields[name].label
        errors += [(form[name].id_for_label, f"{label}: {error}" if name == "cover_image" else error) for error in form.errors.get(name, [])]
    status = article.status if article else CapperArticle.Status.DRAFT
    return {
        "form": form,
        "article": article,
        "page_title": "Редактирование статьи" if article else "Новая статья",
        "article_status": status,
        "article_status_label": CapperArticle.Status(status).label,
        "rejection_note": article.moderation_note if article and status == CapperArticle.Status.REJECTED else "",
        "editor_errors": errors,
        "cover_url": article.cover_image.url if article and article.cover_image else "",
        "editor_tags": [tag.strip() for tag in str(form["tags"].value() or "").split(",") if tag.strip()],
        "preview_author": {
            "name": author_name,
            "initials": "".join(part[0] for part in author_name.split()[:2]).upper() or "К",
            "avatar_url": user.avatar.url if user.avatar else "",
            "verified": bool(profile and profile.is_verified),
        },
        "max_tags": MAX_ARTICLE_TAGS,
        "article_daily_quota": build_article_daily_quota(user),
        "excerpt_max_length": EXCERPT_MAX_LENGTH,
        "active_tab": "articles",
    }


@transaction.atomic
def submit_capper_article_for_moderation(user, article) -> CapperArticle:
    _ensure_article_access(user)
    # All submissions for an author share this lock, including different articles.
    User.objects.select_for_update().get(pk=user.pk)
    article = CapperArticle.objects.select_for_update().get(pk=article.pk)
    _ensure_article_owner(user, article)

    if article.status not in {
        CapperArticle.Status.DRAFT,
        CapperArticle.Status.REJECTED,
    }:
        raise ValidationError("Эту статью нельзя повторно отправить на модерацию.")

    now = timezone.now()
    limit = get_article_daily_limit(user, at=now)
    usage, _ = CapperArticleDailyUsage.objects.get_or_create(author=user, date=timezone.localdate(now))
    if usage.submitted_count >= limit:
        raise ValidationError(
            f"Дневной лимит статей исчерпан: {usage.submitted_count} из {limit}. Можно сохранить черновик и отправить его завтра."
            if limit else "Отправка статей отключена для вашего VIP-тарифа. Черновики можно сохранять."
        )
    _validate_article_text(article, user=user, check_spam=True)

    article.status = CapperArticle.Status.PENDING
    article.submitted_at = now
    article.published_at = None
    article.moderation_note = ""
    article.reviewed_by = None
    article.reviewed_at = None
    article.save(
        update_fields=[
            "status",
            "submitted_at",
            "published_at",
            "moderation_note",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        ]
    )
    usage.submitted_count += 1
    usage.save(update_fields=["submitted_count"])
    return article


@transaction.atomic
def approve_capper_article(article, moderator) -> CapperArticle:
    _ensure_moderator(moderator)
    article = CapperArticle.objects.select_for_update().select_related("author").get(pk=article.pk)
    if article.status != CapperArticle.Status.PENDING:
        raise ValidationError("Опубликовать можно только статью на модерации.")
    _validate_article_text(article, user=article.author, check_spam=False)

    now = timezone.now()
    article.status = CapperArticle.Status.APPROVED
    article.published_at = now
    article.reviewed_by = moderator
    article.reviewed_at = now
    article.moderation_note = ""
    article.save(
        update_fields=[
            "status",
            "published_at",
            "reviewed_by",
            "reviewed_at",
            "moderation_note",
            "updated_at",
        ]
    )
    return article


@transaction.atomic
def reject_capper_article(article, moderator, note: str) -> CapperArticle:
    _ensure_moderator(moderator)
    article = CapperArticle.objects.select_for_update().get(pk=article.pk)
    if article.status != CapperArticle.Status.PENDING:
        raise ValidationError("Отклонить можно только статью на модерации.")

    now = timezone.now()
    article.status = CapperArticle.Status.REJECTED
    article.moderation_note = normalize_comment_text(note)
    article.published_at = None
    article.reviewed_by = moderator
    article.reviewed_at = now
    article.save(
        update_fields=[
            "status",
            "moderation_note",
            "published_at",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        ]
    )
    return article


def _validate_article_text(
    article: CapperArticle,
    *,
    user,
    check_spam: bool,
) -> None:
    plain_text = normalize_comment_text(
        " ".join(
            part
            for part in (
                article.title,
                article.excerpt,
                strip_tags(article.content),
            )
            if part
        )
    )
    if not plain_text:
        raise ValidationError("Статья не может быть пустой.")

    raw_text = " ".join(
        part
        for part in (
            article.title,
            article.excerpt,
            article.content,
        )
        if part
    )
    if contains_forbidden_link(raw_text):
        raise ValidationError(
            "Статья содержит ссылку, e-mail или упоминание, которое не прошло модерацию."
        )
    if contains_profanity(plain_text):
        raise ValidationError("Статья содержит запрещённые слова.")

    if check_spam:
        anti_spam_result = check_comment_spam(
            plain_text,
            user,
            target=article,
        )
        if not anti_spam_result.allowed:
            raise ValidationError(
                anti_spam_result.public_message
                or "Статья не прошла anti-spam проверку."
            )


def _ensure_article_access(user) -> None:
    if not can_create_capper_article(user):
        raise PermissionDenied("Публикация статей доступна только VIP-капперам.")


def _ensure_article_owner(user, article: CapperArticle) -> None:
    if article.author_id != getattr(user, "pk", None):
        raise PermissionDenied("Нельзя редактировать чужую статью.")


def _ensure_moderator(user) -> None:
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_staff", False):
        raise PermissionDenied("Недостаточно прав для модерации статьи.")
