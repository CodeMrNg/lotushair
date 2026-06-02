import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.db.models import Sum
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
        if not self.cycle_days:
            return 1
        elapsed = (timezone.localdate() - self.starts_on).days
        if elapsed < 0:
            return 1
        return (elapsed % self.cycle_days) + 1

    @property
    def current_cycle_number(self):
        if not self.cycle_days:
            return 1
        elapsed = (timezone.localdate() - self.starts_on).days
        if elapsed < 0:
            return 1
        return (elapsed // self.cycle_days) + 1

    @property
    def current_cycle_start(self):
        if not self.cycle_days:
            return self.starts_on
        elapsed = (timezone.localdate() - self.starts_on).days
        if elapsed < 0:
            return self.starts_on
        return self.starts_on + timezone.timedelta(days=(elapsed // self.cycle_days) * self.cycle_days)

    @property
    def current_cycle_end(self):
        return self.current_cycle_start + timezone.timedelta(days=max(self.cycle_days - 1, 0))

    def ordered_members(self):
        return self.members.filter(is_active=True).order_by("rank", "full_name")

    def next_beneficiary(self):
        members = list(self.ordered_members())
        if not members:
            return None
        index = (self.current_cycle_number - 1) % len(members)
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
    last_login_at = models.DateTimeField("derniere connexion", null=True, blank=True)
    last_seen_at = models.DateTimeField("derniere activite", null=True, blank=True)
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
        contribution_amount = max(self.group.contribution_amount, 1)
        total_paid = self.payments.filter(status=Payment.Status.CONFIRMED).aggregate(total=Sum("amount"))["total"] or 0
        return total_paid // contribution_amount

    @property
    def payments_due(self):
        frequency_days = max(self.group.payment_frequency_days, 1)
        elapsed_days = (timezone.localdate() - self.group.starts_on).days
        return max(0, elapsed_days // frequency_days)

    @property
    def payments_ahead(self):
        return max(self.payments_done - self.payments_due, 0)

    @property
    def days_remaining(self):
        return max(self.group.expected_payments - self.payments_done, 0)

    @property
    def is_late(self):
        return self.payments_done < self.payments_due

    @property
    def regularity_badge(self):
        if self.is_late:
            return "A regulariser"
        if self.payments_ahead:
            return "En avance"
        if self.payments_done >= self.group.expected_payments:
            return "Paiement exemplaire"
        return "Membre regulier"

    @property
    def selected_wig(self):
        choice = self.selected_wig_choice
        return choice.wig if choice else None

    @property
    def selected_wig_choice(self):
        return self.wig_choices.select_related("wig").order_by("-selected_at").first()

    @property
    def is_online(self):
        if not self.last_seen_at:
            return False
        return self.last_seen_at >= timezone.now() - timezone.timedelta(minutes=5)


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


class AccountingWithdrawal(models.Model):
    amount = models.PositiveIntegerField("montant")
    withdrawn_on = models.DateField("date de retrait", default=timezone.localdate)
    group = models.ForeignKey(
        RistourneGroup,
        on_delete=models.SET_NULL,
        related_name="withdrawals",
        verbose_name="groupe",
        null=True,
        blank=True,
    )
    member = models.ForeignKey(
        Member,
        on_delete=models.SET_NULL,
        related_name="withdrawals",
        verbose_name="membre",
        null=True,
        blank=True,
    )
    note = models.CharField("note", max_length=220, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-withdrawn_on", "-created_at"]
        verbose_name = "retrait comptable"
        verbose_name_plural = "retraits comptables"

    def __str__(self):
        target = self.member or self.group or "Solde general"
        return f"{target} - {self.amount} FCFA"


class WigCatalog(models.Model):
    name = models.CharField("nom du modele", max_length=140)
    description = models.TextField("description")
    image = models.ImageField("image", upload_to="catalogue/", blank=True)
    image_url = models.URLField("image", blank=True)
    colors = models.CharField("couleurs disponibles", max_length=255, blank=True, help_text="Separez les couleurs par des virgules.")
    sizes = models.CharField("tailles disponibles", max_length=255, blank=True, help_text="Separez les tailles par des virgules.")
    visible_to_groups = models.ManyToManyField(
        RistourneGroup,
        blank=True,
        related_name="visible_wigs",
        verbose_name="groupes autorises",
        help_text="Laissez vide pour rendre ce modele visible a tous les groupes.",
    )
    is_available = models.BooleanField("disponible", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "perruque"
        verbose_name_plural = "catalogue des perruques"

    def __str__(self):
        return self.name

    @property
    def available_colors(self):
        return [color.strip() for color in self.colors.split(",") if color.strip()]

    @property
    def available_sizes(self):
        return [size.strip() for size in self.sizes.split(",") if size.strip()]

    @property
    def display_image_url(self):
        if self.image:
            return self.image.url
        first_gallery_image = self.gallery_images.first()
        if first_gallery_image:
            return first_gallery_image.image.url
        return self.image_url


class WigImage(models.Model):
    wig = models.ForeignKey(WigCatalog, on_delete=models.CASCADE, related_name="gallery_images", verbose_name="modele")
    color = models.CharField("couleur", max_length=80)
    image = models.ImageField("image", upload_to="catalogue/couleurs/")
    order = models.PositiveIntegerField("ordre", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["wig__name", "color", "order", "id"]
        verbose_name = "image de perruque"
        verbose_name_plural = "images de perruques"

    def __str__(self):
        return f"{self.wig.name} - {self.color}"


class WigChoice(models.Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="wig_choices")
    wig = models.ForeignKey(WigCatalog, on_delete=models.CASCADE, related_name="choices")
    color = models.CharField("couleur choisie", max_length=80, blank=True)
    size = models.CharField("taille choisie", max_length=80, blank=True)
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
