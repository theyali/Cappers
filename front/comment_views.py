import json

from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_http_methods, require_POST

from cabinet.comments.services.predictions import (
    CommentServiceError,
    create_prediction_comment,
    get_accessible_prediction,
    prediction_comments_count,
    prediction_comments_queryset,
    serialize_comment,
    soft_delete_comment,
)


COMMENTS_PAGE_SIZE = 20


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
        queryset = prediction_comments_queryset(prediction)
        paginator = Paginator(queryset, COMMENTS_PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get("page") or 1)
        return JsonResponse(
            {
                "ok": True,
                "comments": [
                    serialize_comment(comment, viewer=request.user)
                    for comment in page_obj.object_list
                ],
                "comments_count": paginator.count,
                "page": page_obj.number,
                "pages": paginator.num_pages,
                "has_next": page_obj.has_next(),
                "next_page": page_obj.next_page_number() if page_obj.has_next() else None,
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
            "comments_count": prediction_comments_count(prediction),
        },
        status=201,
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

    return JsonResponse(
        {
            "ok": True,
            "comment_id": comment.pk,
            "status": comment.status,
            "comments_count": comments_count,
        }
    )


def _comment_text_from_request(request) -> str:
    content_type = (request.content_type or "").split(";", 1)[0].strip().lower()
    if content_type == "application/json":
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid_json") from exc
        if not isinstance(payload, dict):
            raise ValueError("invalid_json")
        return payload.get("text", "")

    return request.POST.get("text", "")
