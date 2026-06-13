from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AccountingWithdrawal, Announcement, Member, Payment, RistourneGroup, WigCatalog, WigChoice, WigImage


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
        self.assertIsNone(self.member.last_seen_at)

    def test_admin_member_list_displays_login_status(self):
        self.client.login(username="admin", password="admin1234")

        response = self.client.get(reverse("manage_members"))

        self.assertContains(response, "Jamais connecte")
        self.assertContains(response, "Inscrit le")
        self.assertNotContains(response, "Suivi de presence desactive")

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

    def test_manage_payments_displays_late_members(self):
        self.group.starts_on = timezone.localdate() - timezone.timedelta(days=1)
        self.group.save()
        self.client.login(username="admin", password="admin1234")

        response = self.client.get(reverse("manage_payments"))

        self.assertContains(response, "Membres en retard de cotisation")
        self.assertContains(response, self.member.full_name)
        self.assertContains(response, "En retard")

        Payment.objects.create(member=self.member, amount=self.group.contribution_amount, status=Payment.Status.CONFIRMED)
        response = self.client.get(reverse("manage_payments"))

        self.assertContains(response, "Aucun membre en retard de cotisation.")

    def test_manage_payments_displays_members_ahead_in_next_cycle(self):
        second = Member.objects.create(full_name="Berenice Test", group=self.group, rank=2)
        second.set_code("DEF456")
        second.save()
        Payment.objects.create(
            member=self.member,
            amount=self.group.contribution_amount * (self.group.expected_payments + 1),
            status=Payment.Status.CONFIRMED,
        )
        self.client.login(username="admin", password="admin1234")

        response = self.client.get(reverse("manage_payments"))

        self.assertContains(response, "Membres en avance de paiement")
        self.assertContains(response, self.member.full_name)
        self.assertContains(response, "Avance completee dans le cycle 2")
        self.assertContains(response, "En avance")

    def test_manage_payments_flags_ahead_money_when_no_next_cycle_exists(self):
        Payment.objects.create(
            member=self.member,
            amount=self.group.contribution_amount * (self.group.expected_payments + 1),
            status=Payment.Status.CONFIRMED,
        )
        self.client.login(username="admin", password="admin1234")

        response = self.client.get(reverse("manage_payments"))

        self.assertContains(response, "Plus de prochain cycle")
        self.assertContains(response, "Plus de cycle")
        self.assertContains(response, "a encore 1250 FCFA en avance")

    def test_member_is_not_late_before_or_on_group_start_date(self):
        self.group.starts_on = timezone.localdate() + timezone.timedelta(days=1)
        self.group.save()

        self.assertEqual(self.member.payments_due, 0)
        self.assertFalse(self.member.is_late)

        self.group.starts_on = timezone.localdate()
        self.group.save()

        self.assertEqual(self.member.payments_due, 0)
        self.assertFalse(self.member.is_late)

    def test_group_detail_displays_group_and_member_payment_totals(self):
        second = Member.objects.create(full_name="Berenice Test", group=self.group, rank=2)
        second.set_code("DEF456")
        second.save()
        Payment.objects.create(member=self.member, amount=1250, status=Payment.Status.CONFIRMED)
        Payment.objects.create(member=self.member, amount=2500, status=Payment.Status.CONFIRMED)
        Payment.objects.create(member=self.member, amount=7000, status=Payment.Status.PENDING)
        Payment.objects.create(member=second, amount=1250, status=Payment.Status.CONFIRMED)
        self.client.login(username="admin", password="admin1234")

        response = self.client.get(reverse("group_detail", args=[self.group.id]))

        self.assertContains(response, "Total versements")
        self.assertContains(response, "5000 FCFA")
        self.assertContains(response, "Total : 3750 FCFA")
        self.assertContains(response, "Total : 1250 FCFA")
        self.assertNotContains(response, "10750 FCFA")

    def test_group_detail_allows_editing_members_in_group(self):
        self.client.login(username="admin", password="admin1234")

        response = self.client.get(reverse("group_detail", args=[self.group.id]))

        self.assertContains(response, f'{reverse("edit_member", args=[self.member.id])}?from_group={self.group.id}')
        self.assertContains(response, "Modifier")

    def test_edit_member_from_group_returns_to_group_detail(self):
        self.client.login(username="admin", password="admin1234")

        response = self.client.post(
            f'{reverse("edit_member", args=[self.member.id])}?from_group={self.group.id}',
            {
                "full_name": "Amina Modifiee",
                "group": self.group.id,
                "rank": self.member.rank,
                "status": self.member.status,
                "joined_at": self.member.joined_at.strftime("%Y-%m-%d"),
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("group_detail", args=[self.group.id]))
        self.member.refresh_from_db()
        self.assertEqual(self.member.full_name, "Amina Modifiee")

    def test_member_detail_displays_total_confirmed_payments(self):
        Payment.objects.create(member=self.member, amount=1250, status=Payment.Status.CONFIRMED)
        Payment.objects.create(member=self.member, amount=2500, status=Payment.Status.CONFIRMED)
        Payment.objects.create(member=self.member, amount=7000, status=Payment.Status.PENDING)
        self.client.login(username="admin", password="admin1234")

        response = self.client.get(reverse("member_detail_admin", args=[self.member.id]))

        self.assertContains(response, "Total versements")
        self.assertContains(response, "3750 FCFA")
        self.assertNotContains(response, "10750 FCFA")

    def test_accounting_displays_balance_and_stats(self):
        Payment.objects.create(member=self.member, amount=5000, status=Payment.Status.CONFIRMED)
        Payment.objects.create(member=self.member, amount=9000, status=Payment.Status.PENDING)
        AccountingWithdrawal.objects.create(amount=1250, group=self.group, member=self.member, note="Retrait test")
        self.client.login(username="admin", password="admin1234")

        response = self.client.get(reverse("accounting"))

        self.assertContains(response, "Compta")
        self.assertContains(response, "Solde actuel")
        self.assertContains(response, "3750 FCFA")
        self.assertContains(response, "Total retraits")
        self.assertContains(response, "Retrait test")
        self.assertContains(response, "Cycle 1")
        self.assertNotContains(response, "14000 FCFA")

    def test_accounting_can_create_withdrawal(self):
        self.client.login(username="admin", password="admin1234")

        response = self.client.post(
            reverse("accounting"),
            {
                "amount": 2500,
                "withdrawn_on": timezone.localdate(),
                "group": self.group.id,
                "member": self.member.id,
                "note": "Achat fournitures",
            },
        )

        self.assertRedirects(response, reverse("accounting"))
        self.assertTrue(AccountingWithdrawal.objects.filter(amount=2500, note="Achat fournitures").exists())

    def test_accounting_group_stats_are_paginated_by_ten(self):
        for index in range(12):
            RistourneGroup.objects.create(name=f"Groupe compta {index:02d}")
        self.client.login(username="admin", password="admin1234")

        response = self.client.get(reverse("accounting"))

        self.assertEqual(len(response.context["group_stats"]), 10)
        self.assertContains(response, "Page 1 / 2")

    def test_large_payment_counts_as_multiple_daily_payments(self):
        self.group.starts_on = timezone.localdate() - timezone.timedelta(days=1)
        self.group.save()

        Payment.objects.create(member=self.member, amount=5000, status=Payment.Status.CONFIRMED)

        self.assertEqual(self.member.payments_done, 4)
        self.assertFalse(self.member.is_late)
        self.assertEqual(self.member.payments_ahead, 3)
        self.assertEqual(self.member.regularity_badge, "En avance")

    def test_member_dashboard_shows_payment_counts_not_amounts(self):
        self.member.accepted_terms_at = timezone.now()
        self.member.save()
        Payment.objects.create(member=self.member, amount=self.group.contribution_amount * 2, status=Payment.Status.CONFIRMED)

        session = self.client.session
        session["member_id"] = self.member.id
        session.save()

        response = self.client.get(reverse("member_dashboard"))

        self.assertEqual(response.context["payments_completed_count"], 2)
        self.assertEqual(response.context["total_expected_payments"], self.group.expected_payments)
        self.assertContains(response, "2 versement(s)")
        self.assertNotContains(response, f"{self.group.contribution_amount * 2} FCFA")

    def test_member_dashboard_marks_paid_calendar_days_including_advance_cycle(self):
        self.group.cycle_days = 2
        self.group.payment_frequency_days = 1
        self.group.starts_on = timezone.localdate().replace(day=1)
        self.group.save()
        self.member.accepted_terms_at = timezone.now()
        self.member.save()
        second = Member.objects.create(full_name="Berenice Test", group=self.group, rank=2)
        second.set_code("DEF456")
        second.save()
        Payment.objects.create(member=self.member, amount=self.group.contribution_amount * 3, status=Payment.Status.CONFIRMED)
        advance_paid_date = self.group.starts_on + timezone.timedelta(days=2)

        session = self.client.session
        session["member_id"] = self.member.id
        session.save()

        response = self.client.get(reverse("member_dashboard"), {"calendar": self.group.starts_on.strftime("%Y-%m")})
        paid_days = [
            day
            for week in response.context["calendar_weeks"]
            for day in week
            if day["date"] == advance_paid_date
        ]

        self.assertTrue(paid_days[0]["is_paid"])
        self.assertContains(response, "paid-day")
        self.assertContains(response, "Versement effectué")

    def test_staff_can_create_announcement_from_announcements_tab(self):
        self.client.login(username="admin", password="admin1234")

        response = self.client.post(
            reverse("manage_announcements"),
            {
                "title": "Reunion importante",
                "message": "Presence obligatoire samedi.",
                "visible_to_groups": [self.group.id],
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("manage_announcements"))
        announcement = Announcement.objects.get(title="Reunion importante")
        self.assertTrue(announcement.is_active)
        self.assertEqual(list(announcement.visible_to_groups.all()), [self.group])

    def test_member_dashboard_shows_only_targeted_active_announcements(self):
        self.member.accepted_terms_at = timezone.now()
        self.member.save()
        other_group = RistourneGroup.objects.create(name="Autre groupe")
        group_announcement = Announcement.objects.create(title="Annonce groupe", message="Visible groupe")
        group_announcement.visible_to_groups.add(self.group)
        member_announcement = Announcement.objects.create(title="Annonce membre", message="Visible membre")
        member_announcement.visible_to_members.add(self.member)
        other_announcement = Announcement.objects.create(title="Annonce autre", message="Invisible")
        other_announcement.visible_to_groups.add(other_group)
        Announcement.objects.create(title="Annonce masquee", message="Inactive", is_active=False)

        session = self.client.session
        session["member_id"] = self.member.id
        session.save()

        response = self.client.get(reverse("member_dashboard"))

        self.assertContains(response, "Annonce groupe")
        self.assertContains(response, "Annonce membre")
        self.assertNotContains(response, "Annonce autre")
        self.assertNotContains(response, "Annonce masquee")

    def test_member_reads_announcement_modal_once(self):
        self.member.accepted_terms_at = timezone.now()
        self.member.save()
        announcement = Announcement.objects.create(title="Nouvelle information", message="A lire avant samedi.")
        announcement.visible_to_groups.add(self.group)

        session = self.client.session
        session["member_id"] = self.member.id
        session.save()

        response = self.client.get(reverse("member_dashboard"))

        self.assertContains(response, "Nouvelle annonce")
        self.assertContains(response, "Nouvelle information")
        self.assertContains(response, "J'ai lu")

        response = self.client.post(reverse("mark_announcement_read", args=[announcement.id]))

        self.assertRedirects(response, reverse("member_dashboard"))
        self.assertTrue(announcement.read_by.filter(id=self.member.id).exists())

        response = self.client.get(reverse("member_dashboard"))

        self.assertNotContains(response, "Nouvelle annonce")
        self.assertContains(response, "Nouvelle information")

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

    def test_member_catalog_only_shows_wigs_visible_to_member_group(self):
        other_group = RistourneGroup.objects.create(name="Autre groupe")
        public_wig = WigCatalog.objects.create(name="Modele public", description="Visible pour tous")
        private_wig = WigCatalog.objects.create(name="Modele du groupe", description="Visible pour le groupe")
        hidden_wig = WigCatalog.objects.create(name="Modele cache", description="Visible ailleurs")
        private_wig.visible_to_groups.add(self.group)
        hidden_wig.visible_to_groups.add(other_group)
        self.member.accepted_terms_at = timezone.now()
        self.member.save()

        session = self.client.session
        session["member_id"] = self.member.id
        session.save()

        response = self.client.get(reverse("member_catalog"))

        self.assertContains(response, public_wig.name)
        self.assertContains(response, private_wig.name)
        self.assertNotContains(response, hidden_wig.name)

    def test_member_cannot_choose_wig_hidden_from_member_group(self):
        other_group = RistourneGroup.objects.create(name="Autre groupe")
        hidden_wig = WigCatalog.objects.create(name="Modele cache", description="Visible ailleurs")
        hidden_wig.visible_to_groups.add(other_group)
        self.member.accepted_terms_at = timezone.now()
        self.member.save()

        session = self.client.session
        session["member_id"] = self.member.id
        session.save()

        response = self.client.post(reverse("choose_wig", args=[hidden_wig.id]))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(WigChoice.objects.filter(member=self.member, wig=hidden_wig).exists())

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

    def test_member_global_progress_uses_all_group_cycles(self):
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

        self.assertEqual(response.context["total_group_cycles"], 3)
        self.assertEqual(response.context["current_group_cycle"], 2)
        self.assertEqual(response.context["progress"], 37)
        self.assertEqual(len(response.context["cycle_progress_markers"]), 3)
        self.assertTrue(response.context["cycle_progress_markers"][0]["is_done"])

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
