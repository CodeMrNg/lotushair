import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone


def generate_member_code():
    return secrets.token_hex(3).upper()


class RistourneGroup(models.Model):
    name = models.CharField("nom", max_length=120)
    cycle_days = models.PositiveIntegerField("duree du cycle", default=15)
    contribution_amount = models.PositiveIntegerField("montant de versement", default=1250)
    payment_frequency_days = models.PositiveIntegerField("rythme en jours", default=1)
    starts_on = models.DateField("debut du cycle", default=timezone.localdate)
    is_active = models.BooleanField("actif", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "groupe"
        verbose_name_plural = "groupes"

    def __str__(self):
        return self.name

    @property
    def expected_payments(self):
        return max(1, self.cycle_days // self.payment_frequency_days)

    @property
    def current_day(self):
        elapsed = (timezone.localdate() - self.starts_on).days + 1
        return min(max(elapsed, 1), self.cycle_days)

    def ordered_members(self):
        return self.members.filter(is_active=True).order_by("rank", "full_name")

    def next_beneficiary(self):
        members = list(self.ordered_members())
        if not members:
            return None
        index = (self.current_day - 1) % len(members)
        return members[index]


class Member(models.Model):
    full_name = models.CharField("nom complet", max_length=160)
    group = models.ForeignKey(
        RistourneGroup,
        on_delete=models.CASCADE,
        related_name="members",
        verbose_name="groupe",
    )
    rank = models.PositiveIntegerField("rang")
    code_hash = models.CharField("code chiffre", max_length=256)
    status = models.CharField("statut", max_length=40, default="actif")
    joined_at = models.DateField("date d'inscription", default=timezone.localdate)
    accepted_terms_at = models.DateTimeField("conditions acceptees le", null=True, blank=True)
    is_active = models.BooleanField("actif", default=True)

    class Meta:
        ordering = ["group__name", "rank", "full_name"]
        unique_together = [("group", "rank")]
        verbose_name = "membre"
        verbose_name_plural = "membres"

    def __str__(self):
        return self.full_name

    def set_code(self, raw_code):
        self.code_hash = make_password(raw_code)

    def check_code(self, raw_code):
        return check_password(raw_code.upper(), self.code_hash)

    @property
    def payments_done(self):
        return self.payments.filter(status=Payment.Status.CONFIRMED).count()

    @property
    def days_remaining(self):
        return max(self.group.expected_payments - self.payments_done, 0)

    @property
    def is_late(self):
        return self.payments_done < max(0, self.group.current_day // self.group.payment_frequency_days)

    @property
    def regularity_badge(self):
        if self.is_late:
            return "A regulariser"
        if self.payments_done >= self.group.expected_payments:
            return "Paiement exemplaire"
        return "Membre regulier"

    @property
    def selected_wig(self):
        choice = self.wig_choices.select_related("wig").order_by("-selected_at").first()
        return choice.wig if choice else None


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        CONFIRMED = "confirmed", "Confirme"
        LATE = "late", "En retard"

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="payments")
    amount = models.PositiveIntegerField("montant")
    paid_on = models.DateField("date de paiement", default=timezone.localdate)
    status = models.CharField("statut", max_length=20, choices=Status.choices, default=Status.CONFIRMED)
    note = models.CharField("note", max_length=220, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_on", "-created_at"]
        verbose_name = "paiement"
        verbose_name_plural = "paiements"

    def __str__(self):
        return f"{self.member} - {self.amount} FCFA"


class WigCatalog(models.Model):
    name = models.CharField("nom du modele", max_length=140)
    description = models.TextField("description")
    image_url = models.URLField("image", blank=True)
    is_available = models.BooleanField("disponible", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "perruque"
        verbose_name_plural = "catalogue des perruques"

    def __str__(self):
        return self.name


class WigChoice(models.Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="wig_choices")
    wig = models.ForeignKey(WigCatalog, on_delete=models.CASCADE, related_name="choices")
    selected_at = models.DateTimeField(default=timezone.now)
    is_final = models.BooleanField("choix final", default=False)

    class Meta:
        ordering = ["-selected_at"]
        verbose_name = "choix de perruque"
        verbose_name_plural = "choix de perruques"


class Notification(models.Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="notifications", null=True, blank=True)
    title = models.CharField(max_length=140)
    message = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

# Create your models here.
