from django.shortcuts import render

from .models import WikiTerm, WikiVideo, WikiVideoSection


def wiki(request):
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

    selected_section = None
    selected_section_id = request.GET.get("section", "").strip()
    if selected_section_id.isdigit():
        selected_section = next(
            (section for section in video_sections if section.pk == int(selected_section_id)),
            None,
        )
        if selected_section is not None:
            videos_qs = videos_qs.filter(section=selected_section)

    videos = list(videos_qs)
    terms = list(WikiTerm.objects.filter(is_published=True))

    return render(
        request,
        "front/wiki.html",
        {
            "wiki_videos": videos,
            "wiki_video_sections": video_sections,
            "wiki_selected_video_section": selected_section,
            "wiki_terms": terms,
            "wiki_video_count": all_video_count,
            "wiki_term_count": len(terms),
            "wiki_total_count": all_video_count + len(terms),
        },
    )
