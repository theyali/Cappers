import json

from django.http import Http404, JsonResponse
from django.views.decorators.http import require_http_methods, require_POST

from cabinet.comments.services.predictions import (
    CommentServiceError,
    attach_comment_replies,
    comment_replies_count,
    comment_replies_queryset,
    create_prediction_comment,
    get_accessible_comment_parent,
    get_accessible_prediction,
    prediction_comment_target_counts,
    prediction_comments_count,
    prediction_comments_queryset,
    prediction_comments_total_count,
    serialize_comment,
    set_comment_reaction,
    soft_delete_comment,
)


COMMENTS_PAGE_SIZE = 3
COMMENT_REPLIES_PAGE_SIZE = 3


@require_http_methods(["GET", "POST"])
def prediction_comments(request, prediction_id: int):
    if request.method == "POST" and not request.user.is_authenticated:
        return JsonResponse(
            {
                "ok": False,
                "code": "authentication_required",
                "error": "Для отправки комментария нужно войти в аккаунт.",
            },
            status=401,
        )

    try:
        prediction = get_accessible_prediction(request.user, prediction_id)
    except Http404:
        return JsonResponse(
            {"ok": False, "code": "not_found", "error": "Прогноз не найден."},
            status=404,
        )

    if request.method == "GET":
        root_comments_count = prediction_comments_count(prediction)
        comments_count = prediction_comments_total_count(prediction)
        pages = max(1, (root_comments_count + COMMENTS_PAGE_SIZE - 1) // COMMENTS_PAGE_SIZE)
        page = _page_number(request.GET.get("page"), pages)
        offset = (page - 1) * COMMENTS_PAGE_SIZE
        comments = list(prediction_comments_queryset(prediction)[
            offset : offset + COMMENTS_PAGE_SIZE
        ])
        attach_comment_replies(comments, limit=0)
        return JsonResponse(
            {
                "ok": True,
                "comments": [
                    serialize_comment(comment, viewer=request.user)
                    for comment in comments
                ],
                "comments_count": comments_count,
                "root_comments_count": root_comments_count,
                "page": page,
                "pages": pages,
                "has_next": page < pages,
                "next_page": page + 1 if page < pages else None,
            }
        )

    try:
        text = _comment_text_from_request(request)
    except ValueError:
        return JsonResponse(
            {
                "ok": False,
                "code": "invalid_json",
                "error": "Некорректные данные комментария.",
            },
            status=400,
        )

    try:
        comment = create_prediction_comment(
            prediction=prediction,
            user=request.user,
            text=text,
            parent_id=_parent_id_from_request(request),
        )
    except CommentServiceError as exc:
        return JsonResponse(
            {
                "ok": False,
                "code": exc.code,
                "error": exc.public_message,
            },
            status=exc.http_status,
        )

    return JsonResponse(
        {
            "ok": True,
            "comment": serialize_comment(comment, viewer=request.user),
            "comments_count": prediction_comments_total_count(prediction),
            "root_comments_count": prediction_comments_count(prediction),
        },
        status=201,
    )


@require_http_methods(["GET"])
def comment_replies(request, comment_id: int):
    try:
        parent = get_accessible_comment_parent(request.user, comment_id)
    except Http404:
        return JsonResponse(
            {"ok": False, "code": "not_found", "error": "Комментарий не найден."},
            status=404,
        )

    replies_count = comment_replies_count(parent)
    pages = max(1, (replies_count + COMMENT_REPLIES_PAGE_SIZE - 1) // COMMENT_REPLIES_PAGE_SIZE)
    page = _page_number(request.GET.get("page"), pages)
    offset = (page - 1) * COMMENT_REPLIES_PAGE_SIZE
    replies = comment_replies_queryset(parent)[offset : offset + COMMENT_REPLIES_PAGE_SIZE]
    return JsonResponse(
        {
            "ok": True,
            "parent_id": parent.pk,
            "replies": [
                serialize_comment(reply, viewer=request.user)
                for reply in replies
            ],
            "replies_count": replies_count,
            "page": page,
            "pages": pages,
            "has_next": page < pages,
            "next_page": page + 1 if page < pages else None,
        }
    )


@require_POST
def delete_comment(request, comment_id: int):
    if not request.user.is_authenticated:
        return JsonResponse(
            {
                "ok": False,
                "code": "authentication_required",
                "error": "Для удаления комментария нужно войти в аккаунт.",
            },
            status=401,
        )

    try:
        comment, comments_count = soft_delete_comment(
            comment_id=comment_id,
            actor=request.user,
        )
    except Http404:
        return JsonResponse(
            {"ok": False, "code": "not_found", "error": "Комментарий не найден."},
            status=404,
        )
    except CommentServiceError as exc:
        return JsonResponse(
            {
                "ok": False,
                "code": exc.code,
                "error": exc.public_message,
            },
            status=exc.http_status,
        )

    counts = prediction_comment_target_counts(comment)
    return JsonResponse(
        {
            "ok": True,
            "comment_id": comment.pk,
            "status": comment.status,
            "comments_count": counts["comments_count"] if counts["comments_count"] is not None else comments_count,
            "root_comments_count": counts["root_comments_count"],
        }
    )


@require_POST
def comment_reaction(request, comment_id: int):
    if not request.user.is_authenticated:
        return JsonResponse(
            {
                "ok": False,
                "code": "authentication_required",
                "error": "Для реакции на комментарий нужно войти в аккаунт.",
            },
            status=401,
        )

    try:
        payload = _json_payload(request)
    except ValueError:
        return JsonResponse(
            {
                "ok": False,
                "code": "invalid_json",
                "error": "Некорректные данные реакции.",
            },
            status=400,
        )

    try:
        comment = set_comment_reaction(
            comment_id=comment_id,
            user=request.user,
            kind=payload.get("kind", ""),
        )
    except Http404:
        return JsonResponse(
            {"ok": False, "code": "not_found", "error": "Комментарий не найден."},
            status=404,
        )
    except CommentServiceError as exc:
        return JsonResponse(
            {
                "ok": False,
                "code": exc.code,
                "error": exc.public_message,
            },
            status=exc.http_status,
        )

    return JsonResponse(
        {
            "ok": True,
            "comment": serialize_comment(comment, viewer=request.user),
        }
    )


def _page_number(raw_value, pages: int) -> int:
    try:
        value = int(raw_value or 1)
    except (TypeError, ValueError):
        value = 1
    return min(max(value, 1), pages)


def _comment_text_from_request(request) -> str:
    content_type = (request.content_type or "").split(";", 1)[0].strip().lower()
    if content_type == "application/json":
        payload = _json_payload(request)
        return payload.get("text", "")

    return request.POST.get("text", "")


def _parent_id_from_request(request) -> int | None:
    content_type = (request.content_type or "").split(";", 1)[0].strip().lower()
    raw_value = ""
    if content_type == "application/json":
        try:
            raw_value = _json_payload(request).get("parent_id", "")
        except ValueError:
            return None
    else:
        raw_value = request.POST.get("parent_id", "")
    if raw_value in ("", None):
        return None
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _json_payload(request) -> dict:
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid_json")
    return payload
