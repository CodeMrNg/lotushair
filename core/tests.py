from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Member, RistourneGroup, WigCatalog, WigChoice


class LotusHairFlowTests(TestCase):
    def setUp(self):
        self.group = RistourneGroup.objects.create(name="Test", contribution_amount=1250)
        self.member = Member.objects.create(full_name="Amina Test", group=self.group, rank=1)
        self.member.set_code("ABC123")
        self.member.save()
        self.admin = get_user_model().objects.create_user(username="admin", password="admin1234", is_staff=True)

    def test_member_login_redirects_to_terms(self):
        response = self.client.post(reverse("login"), {"code": "ABC123"})
        self.assertRedirects(response, reverse("terms"))

    def test_member_without_terms_cannot_access_private_pages(self):
        session = self.client.session
        session["member_id"] = self.member.id
        session.save()

        dashboard_response = self.client.get(reverse("member_dashboard"))
        catalog_response = self.client.get(reverse("member_catalog"))

        self.assertRedirects(dashboard_response, reverse("terms"))
        self.assertRedirects(catalog_response, reverse("terms"))

    def test_staff_dashboard_requires_staff_login(self):
        response = self.client.get(reverse("staff_dashboard"))
        self.assertRedirects(response, f"{reverse('staff_login')}?next={reverse('staff_dashboard')}")
        self.client.login(username="admin", password="admin1234")
        response = self.client.get(reverse("staff_dashboard"))
        self.assertContains(response, "Tableau de bord")

    def test_member_cannot_choose_wig_after_receiving_in_current_cycle(self):
        self.group.starts_on = timezone.localdate() - timezone.timedelta(days=1)
        self.group.save()
        self.member.accepted_terms_at = timezone.now()
        self.member.save()
        wig = WigCatalog.objects.create(name="Lisse", description="Modele test")

        session = self.client.session
        session["member_id"] = self.member.id
        session.save()

        response = self.client.post(reverse("choose_wig", args=[wig.id]))
        self.assertRedirects(response, reverse("member_catalog"))
        self.assertFalse(WigChoice.objects.filter(member=self.member, wig=wig).exists())

    def test_member_catalog_search_filters_models(self):
        self.member.accepted_terms_at = timezone.now()
        self.member.save()
        WigCatalog.objects.create(name="Lisse cuivre", description="Modele long")
        WigCatalog.objects.create(name="Boucles volume", description="Modele boucle")

        session = self.client.session
        session["member_id"] = self.member.id
        session.save()

        response = self.client.get(reverse("member_catalog"), {"q": "cuivre"})
        self.assertContains(response, "Lisse cuivre")
        self.assertNotContains(response, "Boucles volume")

    def test_member_dashboard_calendar_can_navigate_months(self):
        self.member.accepted_terms_at = timezone.now()
        self.member.save()

        session = self.client.session
        session["member_id"] = self.member.id
        session.save()

        response = self.client.get(reverse("member_dashboard"), {"calendar": "2026-06"})

        self.assertContains(response, "juin 2026")
        self.assertContains(response, "?calendar=2026-05")
        self.assertContains(response, "?calendar=2026-07")

    def test_member_dates_use_current_group_cycle(self):
        self.group.cycle_days = 15
        self.group.starts_on = timezone.localdate() - timezone.timedelta(days=16)
        self.group.save()
        self.member.accepted_terms_at = timezone.now()
        self.member.save()

        session = self.client.session
        session["member_id"] = self.member.id
        session.save()

        response = self.client.get(reverse("member_dashboard"))

        self.assertEqual(response.context["cycle_starts_on"], self.group.current_cycle_start)
        self.assertEqual(response.context["cycle_ends_on"], self.group.current_cycle_end)
        self.assertContains(response, self.group.current_cycle_start.strftime("%Y-%m-%d"))

# Create your tests here.
