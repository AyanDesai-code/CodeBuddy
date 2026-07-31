from django import forms
from django.contrib.auth import (
    get_user_model,
)
from django.contrib.auth.forms import (
    UserCreationForm,
)


User = get_user_model()


class SignUpForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
    )

    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "password1",
            "password2",
        )

    def clean_email(self):
        email = (
            self.cleaned_data["email"]
            .strip()
            .lower()
        )

        if User.objects.filter(
            email__iexact=email,
        ).exists():
            raise forms.ValidationError(
                (
                    "An account already uses "
                    "this email address."
                )
            )

        return email