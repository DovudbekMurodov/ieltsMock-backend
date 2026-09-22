"""Audio library and section attachment."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.content.audio import AudioRejected, inspect, store
from apps.content.enums import TranscriptVisibility
from apps.content.models import AudioAsset, Section

from .access import staff_required
from .editor import saved
from .nav import page_context


@staff_required
def audio_library(request):
    assets = AudioAsset.objects.annotate(uses=Count("sections")).order_by("-created_at")
    return render(
        request,
        "dashboard/audio_library.html",
        page_context(request, assets=assets),
    )


@staff_required
@require_POST
def audio_upload(request):
    upload = request.FILES.get("file")
    if upload is None:
        messages.error(request, "Choose a file to upload.")
        return redirect("dashboard:audio-library")

    try:
        meta = inspect(upload)
    except (AudioRejected, ValidationError) as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("dashboard:audio-library")

    existing = AudioAsset.objects.filter(checksum_sha256=meta["checksum_sha256"]).first()
    if existing:
        # Content addressing makes dedupe free; say so rather than storing a
        # second copy under a different name.
        messages.success(
            request, f"That file is already in the library as “{existing.original_filename}”."
        )
        return redirect("dashboard:audio-library")

    extension = meta.pop("extension")
    asset = AudioAsset(uploaded_by=request.user, **meta)
    store(asset, upload, extension)
    asset.save()

    messages.success(
        request, f"Uploaded {asset.original_filename} ({asset.duration_seconds}s)."
    )
    return redirect("dashboard:audio-library")


@staff_required
@require_POST
def audio_delete(request, pk):
    asset = get_object_or_404(AudioAsset.objects.annotate(uses=Count("sections")), pk=pk)
    if asset.uses:
        messages.error(
            request,
            f"{asset.original_filename} is used by {asset.uses} section(s). Detach it first.",
        )
        return redirect("dashboard:audio-library")

    asset.file.delete(save=False)
    asset.delete()
    messages.success(request, "Removed from the library.")
    return redirect("dashboard:audio-library")


@staff_required
@require_POST
def section_audio_attach(request, pk):
    """Attach or detach audio, and keep the transcript setting honest.

    Showing the transcript while the audio plays turns a listening test into a
    reading test, so attaching audio moves the section to 'after_submit' unless
    someone has already made a deliberate choice.
    """
    section = get_object_or_404(Section.objects.select_related("test"), pk=pk)
    asset_id = request.POST.get("assetId") or None

    if asset_id:
        section.audio = get_object_or_404(AudioAsset, pk=asset_id)
        if section.transcript_visibility == TranscriptVisibility.DURING_TEST:
            section.transcript_visibility = TranscriptVisibility.AFTER_SUBMIT
    else:
        section.audio = None

    start = request.POST.get("audio_start_ms")
    end = request.POST.get("audio_end_ms")
    section.audio_start_ms = int(start) if start else None
    section.audio_end_ms = int(end) if end else None

    try:
        section.full_clean(exclude=["title"])
    except ValidationError as exc:
        return HttpResponse("; ".join(exc.messages), status=400)

    section.save()
    return render(
        request,
        "dashboard/partials/section_audio.html",
        {
            "section": section,
            "assets": AudioAsset.objects.order_by("-created_at"),
            "visibility_choices": TranscriptVisibility.choices,
        },
    )


@staff_required
@require_POST
def section_transcript_visibility(request, pk):
    section = get_object_or_404(Section, pk=pk)
    value = request.POST.get("transcript_visibility")
    if value not in TranscriptVisibility.values:
        return HttpResponse("Unknown setting.", status=400)

    section.transcript_visibility = value
    section.save(update_fields=["transcript_visibility"])
    return saved()
