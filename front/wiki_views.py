from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string

from .models import WikiTerm, WikiTermSection, WikiVideo, WikiVideoSection


WIKI_TERMS_PAGE_SIZE = 12


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

    videos = list(videos_qs)

    context = {
        "wiki_videos": videos,
        "wiki_video_sections": video_sections,
        "wiki_selected_video_section": selected_video_section,
        "wiki_video_count": all_video_count,
        "wiki_total_count": all_video_count + terms_context["wiki_term_count"],
    }
    context.update(terms_context)

    return render(request, "front/wiki.html", context)
