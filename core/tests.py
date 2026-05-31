from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Member, RistourneGroup, WigCatalog, WigChoice, WigImage


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
        self.member.refresh_from_db()
        self.assertIsNotNone(self.member.last_login_at)
        self.assertTrue(self.member.is_online)

    def test_admin_member_list_displays_presence_badge(self):
        self.member.last_seen_at = timezone.now()
        self.member.save(update_fields=["last_seen_at"])
        self.client.login(username="admin", password="admin1234")

        response = self.client.get(reverse("manage_members"))

        self.assertContains(response, "En ligne")

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
        self.group.starts_on = timezone.localdate() - timezone.timedelta(days=self.group.cycle_days - 1)
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

    def test_member_choose_wig_records_color(self):
        self.member.accepted_terms_at = timezone.now()
        self.member.save()
        wig = WigCatalog.objects.create(name="Lisse", description="Modele test", colors="Noir, Marron", sizes="S, M, L")

        session = self.client.session
        session["member_id"] = self.member.id
        session.save()

        response = self.client.post(reverse("choose_wig", args=[wig.id]), {"color": "Marron", "size": "M"})

        self.assertRedirects(response, reverse("member_catalog"))
        choice = WigChoice.objects.get(member=self.member, wig=wig)
        self.assertEqual(choice.color, "Marron")
        self.assertEqual(choice.size, "M")

    def test_member_cannot_choose_unavailable_size(self):
        self.member.accepted_terms_at = timezone.now()
        self.member.save()
        wig = WigCatalog.objects.create(name="Lisse", description="Modele test", colors="Noir, Marron", sizes="S, M")

        session = self.client.session
        session["member_id"] = self.member.id
        session.save()

        response = self.client.post(reverse("choose_wig", args=[wig.id]), {"color": "Marron", "size": "XL"})

        self.assertRedirects(response, reverse("member_catalog"))
        self.assertFalse(WigChoice.objects.filter(member=self.member, wig=wig).exists())

    def test_member_cannot_choose_unavailable_color(self):
        self.member.accepted_terms_at = timezone.now()
        self.member.save()
        wig = WigCatalog.objects.create(name="Lisse", description="Modele test", colors="Noir, Marron")

        session = self.client.session
        session["member_id"] = self.member.id
        session.save()

        response = self.client.post(reverse("choose_wig", args=[wig.id]), {"color": "Blond"})

        self.assertRedirects(response, reverse("member_catalog"))
        self.assertFalse(WigChoice.objects.filter(member=self.member, wig=wig).exists())

    def test_staff_can_upload_catalog_image(self):
        self.client.login(username="admin", password="admin1234")
        image = SimpleUploadedFile(
            "wig.gif",
            b"GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00ccc,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            content_type="image/gif",
        )

        response = self.client.post(
            reverse("manage_catalog"),
            {
                "name": "Carre court",
                "description": "Modele avec image",
                "colors": "Noir, Blond",
                "is_available": "on",
                "image": image,
            },
        )

        self.assertRedirects(response, reverse("manage_catalog"))
        wig = WigCatalog.objects.get(name="Carre court")
        self.assertTrue(wig.image.name.startswith("catalogue/"))

    def test_staff_can_add_catalog_image_by_color(self):
        self.client.login(username="admin", password="admin1234")
        wig = WigCatalog.objects.create(name="Lisse", description="Modele test", colors="Noir, Marron")
        image = SimpleUploadedFile(
            "black.gif",
            b"GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00ccc,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            content_type="image/gif",
        )

        response = self.client.post(
            reverse("manage_catalog"),
            {
                "form_type": "image",
                "wig": wig.id,
                "color": "Noir",
                "order": 1,
                "image": image,
            },
        )

        self.assertRedirects(response, reverse("manage_catalog"))
        gallery_image = WigImage.objects.get(wig=wig, color="Noir")
        self.assertTrue(gallery_image.image.name.startswith("catalogue/couleurs/"))

    def test_member_catalog_renders_color_carousel_images(self):
        self.member.accepted_terms_at = timezone.now()
        self.member.save()
        wig = WigCatalog.objects.create(name="Lisse", description="Modele test", colors="Noir, Marron")
        WigImage.objects.create(
            wig=wig,
            color="Noir",
            image=SimpleUploadedFile(
                "black.gif",
                b"GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00ccc,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
                content_type="image/gif",
            ),
        )

        session = self.client.session
        session["member_id"] = self.member.id
        session.save()

        response = self.client.get(reverse("member_catalog"))

        self.assertContains(response, 'data-wig-carousel')
        self.assertContains(response, 'data-color="Noir"')
        self.assertContains(response, 'data-color-select')

    def test_member_dashboard_calendar_can_navigate_months(self):
        self.member.accepted_terms_at = timezone.now()
        self.member.save()

        session = self.client.session
        session["member_id"] = self.member.id
        session.save()

        response = self.client.get(reverse("member_dashboard"), {"calendar": "2026-06"})

        self.assertContains(response, "juin 2026")
        self.assertContains(response, "?calendar=2026-05&panel=cycle")
        self.assertContains(response, "?calendar=2026-07&panel=cycle")

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

    def test_member_delivery_dates_are_cycle_end_dates(self):
        self.group.cycle_days = 15
        self.group.starts_on = timezone.localdate() - timezone.timedelta(days=16)
        self.group.save()
        self.member.accepted_terms_at = timezone.now()
        self.member.save()
        second = Member.objects.create(full_name="Berenice Test", group=self.group, rank=2)
        second.set_code("DEF456")
        second.save()
        third = Member.objects.create(full_name="Carine Test", group=self.group, rank=3)
        third.set_code("GHI789")
        third.save()

        session = self.client.session
        session["member_id"] = self.member.id
        session.save()

        response = self.client.get(reverse("member_dashboard"))
        members = list(response.context["group_members"])

        self.assertEqual(members[0].delivery_status, "Recu")
        self.assertEqual(members[0].delivery_date, self.group.current_cycle_end - timezone.timedelta(days=15))
        self.assertEqual(members[1].delivery_status, "Prochain")
        self.assertEqual(members[1].delivery_date, self.group.current_cycle_end)
        self.assertEqual(members[2].delivery_status, "Attente")
        self.assertEqual(members[2].delivery_date, self.group.current_cycle_end + timezone.timedelta(days=15))

# Create your tests here.
