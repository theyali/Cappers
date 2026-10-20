import uuid

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_GET

from .forms import DirectMessageForm
from .models import User
from .services.messages import dialog_peers, dialog_messages, mark_dialog_read, send_direct_message


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def dialog(request, username):
    peer = get_object_or_404(User.objects.exclude(pk=request.user.pk), username=username, is_active=True)
    form = DirectMessageForm(request.POST or None, initial={"client_id": uuid.uuid4()})
    if request.method == "POST" and form.is_valid():
        try:
            send_direct_message(sender=request.user, recipient=peer, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("cabinet:dialog", username=peer.username)
    mark_dialog_read(request.user, peer)
    page = Paginator(dialog_messages(request.user, peer), 30).get_page(request.GET.get("page", 1))
    return render(request, "cabinet/dialog.html", {"peer": peer, "dialog_page": page, "message_form": form})


@login_required
@never_cache
@require_GET
def inbox(request):
    peers = dialog_peers(request.user)
    return render(request, "cabinet/inbox.html", {"inbox_page": Paginator(peers, 30).get_page(request.GET.get("page", 1))})
