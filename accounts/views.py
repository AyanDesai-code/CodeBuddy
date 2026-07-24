from django.shortcuts import render

# Create your views here.
from django.contrib.auth import login
from django.contrib.auth.forms import (
    UserCreationForm,
)
from django.shortcuts import redirect, render


def signup(request):
    if request.user.is_authenticated:
        return redirect("project_list")

    if request.method == "POST":
        form = UserCreationForm(
            request.POST
        )

        if form.is_valid():
            user = form.save()

            login(
                request,
                user,
            )

            return redirect(
                "project_list"
            )

    else:
        form = UserCreationForm()

    return render(
        request,
        "accounts/signup.html",
        {
            "form": form,
        },
    )