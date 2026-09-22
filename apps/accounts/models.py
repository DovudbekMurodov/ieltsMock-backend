from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

from .managers import UserManager


class User(AbstractUser):
    """Email-authenticated user.

    AUTH_USER_MODEL points here from the very first migration; swapping it out
    afterwards is one of the genuinely painful operations in Django.
    """

    username = None
    email = models.EmailField(_("email address"), unique=True)

    target_band = models.DecimalField(max_digits=2, decimal_places=1, null=True, blank=True)
    exam_date = models.DateField(null=True, blank=True)
    country = models.CharField(max_length=2, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    locale = models.CharField(max_length=10, default="en")

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def __str__(self):
        return self.email
