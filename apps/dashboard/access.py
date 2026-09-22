"""Staff gate.

Non-staff get a 404 rather than a 403: a 403 confirms the dashboard exists at
that URL, which is free reconnaissance.
"""

from functools import wraps

from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse


def staff_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('dashboard:login')}?next={request.path}")
        if not request.user.is_staff:
            raise Http404
        return view(request, *args, **kwargs)

    return wrapper
