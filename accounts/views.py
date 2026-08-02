from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import redirect, render

from .forms import SignUpForm
from .security import (
    record_successful_signup,
    signup_is_rate_limited,
    too_many_successful_signups,
)
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from projects.analytics import capture_event

User = get_user_model()


def signup(request):
    if request.user.is_authenticated:
        return redirect("project_list")

    if request.method == "POST":
        if signup_is_rate_limited(request):
            messages.error(
                request,
                (
                    "Too many signup attempts came "
                    "from this network. Please try "
                    "again later."
                ),
            )

            return redirect("signup")

        form = SignUpForm(request.POST)

        if form.is_valid():
            email = (
                form.cleaned_data.get("email")
                or ""
            ).strip().lower()

            if User.objects.filter(
                email__iexact=email,
            ).exists():
                form.add_error(
                    "email",
                    (
                        "An account already uses "
                        "this email address."
                    ),
                )

            elif too_many_successful_signups(
                request
            ):
                messages.error(
                    request,
                    (
                        "Too many accounts have "
                        "already been created from "
                        "this network today."
                    ),
                )

                return redirect("signup")

            else:
                user = form.save(
                    commit=False
                )

                user.email = email

                # Turn this on once email
                # verification is implemented.
                user.is_active = True

                user.save()
    

                record_successful_signup(
                    request
                )
                capture_event(
                    distinct_id=f"user_{user.pk}",
                    event="account_created",
                    properties={
                        "signup_method": "email",
                    },
)

                messages.success(
                    request,
                    (
                        "Your account was created "
                        "successfully."
                    ),
                )

                return redirect("login")

    else:
        form = SignUpForm()

    return render(
        request,
        "accounts/signup.html",
        {
            "form": form,
        },
    )


def cache_debug(request):
    cache.set(
        "redis-test",
        "working",
        300,
    )

    return JsonResponse(
        {
            "backend": (
                settings.CACHES[
                    "default"
                ][
                    "BACKEND"
                ]
            ),
            "cache_value": cache.get(
                "redis-test"
            ),
        }
    )