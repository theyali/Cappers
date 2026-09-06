from django.shortcuts import render

from .models import WikiTerm, WikiVideo


def wiki(request):
    videos = list(WikiVideo.objects.filter(is_published=True))
    terms = list(WikiTerm.objects.filter(is_published=True))

    return render(
        request,
        "front/wiki.html",
        {
            "wiki_videos": videos,
            "wiki_terms": terms,
            "wiki_video_count": len(videos),
            "wiki_term_count": len(terms),
            "wiki_total_count": len(videos) + len(terms),
        },
    )
