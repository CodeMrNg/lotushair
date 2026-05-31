from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Member, Payment, RistourneGroup, WigCatalog


class Command(BaseCommand):
    help = "Cree des donnees de demonstration Lotus Hair."

    def handle(self, *args, **options):
        User = get_user_model()
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={"is_staff": True, "is_superuser": True, "email": "admin@lotushair.local"},
        )
        if created:
            admin.set_password("admin1234")
            admin.save()

        group, _ = RistourneGroup.objects.get_or_create(
            name="Groupe Lotus A",
            defaults={
                "cycle_days": 15,
                "contribution_amount": 1250,
                "payment_frequency_days": 1,
                "starts_on": timezone.localdate(),
            },
        )

        members = [
            ("Amina Kodia", 1, "A4F92C"),
            ("Berenice Mavoungou", 2, "9B11EF"),
            ("Carine Okemba", 3, "FF09DA"),
            ("Diane Milandou", 4, "C0A112"),
        ]
        for full_name, rank, code in members:
            member, member_created = Member.objects.get_or_create(
                group=group,
                rank=rank,
                defaults={"full_name": full_name, "status": "actif"},
            )
            if member_created or not member.code_hash:
                member.set_code(code)
                member.save()

        for member in Member.objects.filter(group=group):
            for offset in range(max(1, min(member.rank + 1, 5))):
                Payment.objects.get_or_create(
                    member=member,
                    paid_on=timezone.localdate() - timezone.timedelta(days=offset),
                    defaults={"amount": group.contribution_amount, "status": Payment.Status.CONFIRMED},
                )

        wigs = [
            ("Lisse cuivre", "Perruque lisse, teinte cuivre douce, finition naturelle.", "https://images.unsplash.com/photo-1522337660859-02fbefca4702?auto=format&fit=crop&w=900&q=80"),
            ("Boucles volume", "Boucles definies pour un rendu dense et elegant.", "https://images.unsplash.com/photo-1519699047748-de8e457a634e?auto=format&fit=crop&w=900&q=80"),
            ("Carre soyeux", "Coupe courte facile a porter, brillance naturelle.", "https://images.unsplash.com/photo-1487412947147-5cebf100ffc2?auto=format&fit=crop&w=900&q=80"),
        ]
        for name, description, image_url in wigs:
            WigCatalog.objects.get_or_create(name=name, defaults={"description": description, "image_url": image_url})

        self.stdout.write(self.style.SUCCESS("Donnees creees. Admin: admin / admin1234. Codes membres: A4F92C, 9B11EF, FF09DA, C0A112."))
