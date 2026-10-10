from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from django.utils.timesince import timesince

from .models import (
    WikiTerm,
    WikiTermSection,
    WikiVideo,
    WikiVideoProgress,
    WikiVideoReaction,
    WikiVideoSection,
)
from .wiki_metrics import (
    increment_wiki_video_views,
    save_wiki_video_progress,
    set_wiki_video_reaction,
)


WIKI_TERMS_PAGE_SIZE = 12
WIKI_AUTHOR_NAME = "КапперХаб"


def _wiki_terms_context(request):
    term_sections = list(
        WikiTermSection.objects.filter(is_active=True)
        .annotate(
            term_count=Count(
                "terms",
                filter=Q(terms__is_published=True),
            )
        )
        .filter(term_count__gt=0)
        .order_by("sort_order", "name", "id")
    )

    terms_base_qs = WikiTerm.objects.filter(
        is_published=True,
        section__is_active=True,
    )
    all_term_count = terms_base_qs.count()

    terms_qs = terms_base_qs.select_related("section").order_by(
        "section__sort_order",
        "section__name",
        "sort_order",
        "term",
        "id",
    )

    selected_term_section = None
    selected_term_section_id = request.GET.get("term_section", "").strip()
    if selected_term_section_id.isdigit():
        selected_term_section = next(
            (section for section in term_sections if section.pk == int(selected_term_section_id)),
            None,
        )
        if selected_term_section is not None:
            terms_qs = terms_qs.filter(section=selected_term_section)

    term_query = request.GET.get("q", "").strip()
    if term_query:
        terms_qs = terms_qs.filter(
            Q(term__icontains=term_query) | Q(description__icontains=term_query)
        )

    filtered_term_count = terms_qs.count()
    show_all_terms = request.GET.get("show") == "all"
    if show_all_terms:
        terms = list(terms_qs)
    else:
        terms = list(terms_qs[:WIKI_TERMS_PAGE_SIZE])

    return {
        "wiki_terms": terms,
        "wiki_term_sections": term_sections,
        "wiki_selected_term_section": selected_term_section,
        "wiki_term_query": term_query,
        "wiki_term_count": all_term_count,
        "wiki_filtered_term_count": filtered_term_count,
        "wiki_terms_has_more": not show_all_terms and filtered_term_count > len(terms),
    }


@ensure_csrf_cookie
def wiki(request):
    terms_context = _wiki_terms_context(request)

    is_terms_ajax = (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        and request.GET.get("fragment") == "terms"
    )
    if is_terms_ajax:
        return JsonResponse(
            {
                "html": render_to_string(
                    "front/includes/_wiki_term_results.html",
                    terms_context,
                    request=request,
                ),
                "selected_section_id": (
                    terms_context["wiki_selected_term_section"].pk
                    if terms_context["wiki_selected_term_section"]
                    else None
                ),
                "filtered_count": terms_context["wiki_filtered_term_count"],
            }
        )

    video_sections = list(
        WikiVideoSection.objects.filter(
            is_active=True,
            videos__is_published=True,
        )
        .distinct()
        .order_by("sort_order", "name", "id")
    )

    videos_qs = (
        WikiVideo.objects.filter(
            is_published=True,
            section__is_active=True,
        )
        .select_related("section")
        .order_by("section__sort_order", "section__name", "sort_order", "title", "id")
    )
    all_video_count = videos_qs.count()

    selected_video_section = None
    selected_video_section_id = request.GET.get("section", "").strip()
    if selected_video_section_id.isdigit():
        selected_video_section = next(
            (section for section in video_sections if section.pk == int(selected_video_section_id)),
            None,
        )
        if selected_video_section is not None:
            videos_qs = videos_qs.filter(section=selected_video_section)

    video_query = request.GET.get("q", "").strip()
    if video_query:
        videos_qs = videos_qs.filter(
            Q(title__icontains=video_query)
            | Q(description__icontains=video_query)
            | Q(tags__icontains=video_query)
            | Q(section__name__icontains=video_query)
        )

    videos = list(videos_qs)
    for index, video in enumerate(videos, start=1):
        video.wiki_author_name = WIKI_AUTHOR_NAME
        video.wiki_views_label = _compact_views(video.views_count)
        video.wiki_added_label = _added_ago(video.created_at)
        video.wiki_duration_label = video.duration or _media_duration_label(video)
        video.wiki_color_index = (index - 1) % 6

    user_completed_count = 0
    user_progress_percent = 0
    if request.user.is_authenticated and videos:
        video_ids = [video.pk for video in videos]
        progress_by_video = {
            item.video_id: item
            for item in WikiVideoProgress.objects.filter(
                user=request.user,
                video_id__in=video_ids,
            )
        }
        for video in videos:
            video.wiki_user_progress = progress_by_video.get(video.pk)
        user_completed_count = sum(1 for item in progress_by_video.values() if item.completed)
        user_progress_percent = round(user_completed_count * 100 / len(videos)) if videos else 0

    context = {
        "page_class": "wiki-youtube-page",
        "hide_site_chrome": True,
        "hide_footer": True,
        "wiki_videos": videos,
        "wiki_video_sections": video_sections,
        "wiki_selected_video_section": selected_video_section,
        "wiki_video_count": all_video_count,
        "wiki_total_count": all_video_count + terms_context["wiki_term_count"],
        "wiki_user_completed_count": user_completed_count,
        "wiki_user_progress_percent": user_progress_percent,
        "wiki_user_remaining_minutes": max(0, (len(videos) - user_completed_count) * 2),
    }
    context.update(terms_context)

    return render(request, "front/wiki.html", context)


def _compact_views(value: int) -> str:
    value = max(0, int(value or 0))
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}".replace(".", ",").rstrip("0").rstrip(",") + " млн."
    if value >= 1_000:
        return f"{value / 1_000:.1f}".replace(".", ",").rstrip("0").rstrip(",") + " тыс."
    return str(value)


def _added_ago(value) -> str:
    if not value:
        return ""
    return f"{timesince(value).split(',')[0]} назад"


def _media_duration_label(video: WikiVideo) -> str:
    try:
        path = video.video.path
    except (NotImplementedError, ValueError):
        return ""

    try:
        seconds = _mp4_duration_seconds(path)
    except (OSError, IndexError, UnicodeDecodeError):
        return ""

    if not seconds:
        return ""

    total = max(0, round(seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _mp4_duration_seconds(path: str) -> float | None:
    def read_atoms(file_obj, end):
        while file_obj.tell() + 8 <= end:
            start = file_obj.tell()
            header = file_obj.read(8)
            if len(header) < 8:
                return
            size = int.from_bytes(header[:4], "big")
            atom_type = header[4:8].decode("latin1")
            header_size = 8
            if size == 1:
                size = int.from_bytes(file_obj.read(8), "big")
                header_size = 16
            elif size == 0:
                size = end - start
            if size < header_size:
                return
            yield start, size, atom_type, header_size
            file_obj.seek(start + size)

    def find_atom(file_obj, end, atom_path):
        for start, size, atom_type, header_size in read_atoms(file_obj, end):
            if atom_type != atom_path[0]:
                continue
            if len(atom_path) == 1:
                return start, size, header_size
            file_obj.seek(start + header_size)
            found = find_atom(file_obj, start + size, atom_path[1:])
            if found:
                return found
        return None

    with open(path, "rb") as file_obj:
        file_obj.seek(0, 2)
        end = file_obj.tell()
        file_obj.seek(0)
        atom = find_atom(file_obj, end, ["moov", "mvhd"])
        if not atom:
            return None

        start, _, header_size = atom
        file_obj.seek(start + header_size)
        version = file_obj.read(1)[0]
        file_obj.read(3)
        if version == 1:
            file_obj.read(16)
            timescale = int.from_bytes(file_obj.read(4), "big")
            duration = int.from_bytes(file_obj.read(8), "big")
        else:
            file_obj.read(8)
            timescale = int.from_bytes(file_obj.read(4), "big")
            duration = int.from_bytes(file_obj.read(4), "big")

    return duration / timescale if timescale else None


@require_POST
def wiki_video_view(request, video_id: int):
    video = get_object_or_404(
        WikiVideo,
        pk=video_id,
        is_published=True,
        section__is_active=True,
    )
    video = increment_wiki_video_views(video)
    return JsonResponse(
        {
            "ok": True,
            "views_count": video.views_count,
        }
    )


@login_required
@require_POST
def wiki_video_reaction(request, video_id: int):
    video = get_object_or_404(
        WikiVideo,
        pk=video_id,
        is_published=True,
        section__is_active=True,
    )
    kind = request.POST.get("kind", "").strip()
    if kind not in {WikiVideoReaction.KIND_LIKE, WikiVideoReaction.KIND_DISLIKE}:
        return JsonResponse(
            {"ok": False, "error": "Неизвестная реакция."},
            status=400,
        )

    active_kind, video = set_wiki_video_reaction(video, request.user, kind)
    return JsonResponse(
        {
            "ok": True,
            "active_kind": active_kind,
            "likes_count": video.likes_count,
            "dislikes_count": video.dislikes_count,
        }
    )


@login_required
@require_POST
def wiki_video_progress(request, video_id: int):
    video = get_object_or_404(
        WikiVideo,
        pk=video_id,
        is_published=True,
        section__is_active=True,
    )
    try:
        position_seconds = int(float(request.POST.get("position_seconds", 0) or 0))
        duration_seconds = int(float(request.POST.get("duration_seconds", 0) or 0))
    except (TypeError, ValueError):
        return JsonResponse(
            {"ok": False, "error": "Некорректное время просмотра."},
            status=400,
        )

    progress = save_wiki_video_progress(
        video,
        request.user,
        position_seconds=position_seconds,
        duration_seconds=duration_seconds,
    )
    return JsonResponse(
        {
            "ok": True,
            "position_seconds": progress.position_seconds,
            "duration_seconds": progress.duration_seconds,
            "percent": progress.percent,
            "completed": progress.completed,
        }
    )
