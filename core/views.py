import calendar
from datetime import date

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import AuthenticationForm
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .forms import AccountingWithdrawalForm, AnnouncementForm, CodeLoginForm, GroupForm, MemberForm, PaymentForm, WigForm, WigImageForm
from .models import AccountingWithdrawal, Announcement, Member, Payment, RistourneGroup, WigCatalog, WigChoice, WigImage, generate_member_code


@never_cache
def service_worker(request):
    response = render(request, "core/service_worker.js", content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response


def offline(request):
    return render(request, "offline.html")


def current_member(request):
    member_id = request.session.get("member_id")
    if not member_id:
        return None
    return Member.objects.filter(id=member_id, is_active=True).select_related("group").first()


def member_required(view_func):
    def wrapper(request, *args, **kwargs):
        member = current_member(request)
        if not member:
            return redirect("login")
        if not member.accepted_terms_at and request.resolver_match.url_name != "terms":
            return redirect("terms")
        request.member = member
        return view_func(request, *args, **kwargs)

    return wrapper


def has_received_wig_this_cycle(member):
    members = list(member.group.ordered_members())
    if member not in members:
        return False
    current_index = (member.group.current_cycle_number - 1) % len(members)
    member_index = members.index(member)
    if member_index < current_index:
        return True
    if member_index == current_index:
        return member.group.current_day >= member.group.cycle_days
    return False


def member_login(request):
    if request.user.is_authenticated:
        logout(request)
    if current_member(request):
        return redirect("member_dashboard")
    form = CodeLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        code = form.cleaned_data["code"]
        member = next((m for m in Member.objects.filter(is_active=True).select_related("group") if m.check_code(code)), None)
        if member:
            member.last_login_at = timezone.now()
            member.save(update_fields=["last_login_at"])
            request.session.flush()
            request.session["member_id"] = member.id
            return redirect("terms" if not member.accepted_terms_at else "member_dashboard")
        messages.error(request, "Code invalide ou compte inactif.")
    return render(request, "core/login.html", {"form": form})


@member_required
def terms(request):
    if request.method == "POST":
        request.member.accepted_terms_at = timezone.now()
        request.member.save(update_fields=["accepted_terms_at"])
        return redirect("member_dashboard")
    return render(request, "core/terms.html")


def member_logout(request):
    request.session.flush()
    return redirect("login")


@member_required
def member_dashboard(request):
    member = request.member
    group = member.group
    group_members = list(group.ordered_members().prefetch_related("payments"))
    contribution_amount = max(group.contribution_amount, 1)
    payments = list(member.payments.all()[:8])
    for payment in payments:
        payment.units_count = max(payment.amount // contribution_amount, 1)
    payments_completed_count = member.payments_done
    total_expected_payments = max(group.expected_payments * max(len(group_members), 1), 1)
    remaining_total_payments = max(total_expected_payments - payments_completed_count, 0)
    annotate_member_payment_position(member)
    cycle_starts_on = group.current_cycle_start
    cycle_ends_on = group.current_cycle_end
    today = timezone.localdate()
    selected_month = request.GET.get("calendar", "")
    try:
        calendar_year, calendar_month = [int(part) for part in selected_month.split("-", 1)]
        calendar_focus = date(calendar_year, calendar_month, 1)
    except (TypeError, ValueError):
        calendar_focus = today.replace(day=1)
    previous_month = (calendar_focus.replace(day=1) - timezone.timedelta(days=1)).replace(day=1)
    next_month = (
        calendar_focus.replace(day=calendar.monthrange(calendar_focus.year, calendar_focus.month)[1])
        + timezone.timedelta(days=1)
    ).replace(day=1)
    cycle_dates = {
        cycle_starts_on + timezone.timedelta(days=offset)
        for offset in range(max(group.cycle_days, 0))
    }
    payment_frequency_days = max(group.payment_frequency_days, 1)
    paid_dates = {
        group.starts_on + timezone.timedelta(days=payment_index * payment_frequency_days)
        for payment_index in range(payments_completed_count)
    }
    announcements = (
        Announcement.objects.filter(is_active=True)
        .filter(
            Q(visible_to_groups__isnull=True, visible_to_members__isnull=True)
            | Q(visible_to_groups=group)
            | Q(visible_to_members=member)
        )
        .distinct()[:5]
    )
    unread_announcement = (
        Announcement.objects.filter(is_active=True)
        .filter(
            Q(visible_to_groups__isnull=True, visible_to_members__isnull=True)
            | Q(visible_to_groups=group)
            | Q(visible_to_members=member)
        )
        .exclude(read_by=member)
        .distinct()
        .first()
    )
    next_beneficiary = group.next_beneficiary()
    delivery_dates = {}
    current_member_index = group_members.index(next_beneficiary) if next_beneficiary in group_members else 0
    total_cycle_days = max(len(group_members) * group.cycle_days, 1)
    elapsed_cycle_days = min((current_member_index * group.cycle_days) + group.current_day, total_cycle_days)
    progress = min(int((elapsed_cycle_days / total_cycle_days) * 100), 100)
    ristourne_days_remaining = max(total_cycle_days - elapsed_cycle_days, 0)
    ristourne_ends_on = cycle_starts_on + timezone.timedelta(days=ristourne_days_remaining)
    cycle_progress_markers = []
    for marker_index, group_member in enumerate(group_members):
        cycle_end_position = int(((marker_index + 1) / max(len(group_members), 1)) * 100)
        cycle_progress_markers.append(
            {
                "member": group_member,
                "position": cycle_end_position,
                "is_done": marker_index < current_member_index or (marker_index == current_member_index and group.current_day >= group.cycle_days),
            }
        )
    for member_index, group_member in enumerate(group_members):
        cycle_distance = member_index - current_member_index
        group_member.delivery_date = cycle_ends_on + timezone.timedelta(days=cycle_distance * group.cycle_days)
        delivery_dates[group_member.delivery_date] = group_member
        if next_beneficiary and group_member.id == next_beneficiary.id:
            group_member.delivery_status = "Prochain"
            group_member.delivery_date_label = "Recevra le"
        elif member_index < current_member_index:
            group_member.delivery_status = "Recu"
            group_member.delivery_date_label = "Recu le"
        else:
            group_member.delivery_status = "Attente"
            group_member.delivery_date_label = "Recevra le"
    member.delivery_status = next(
        (group_member.delivery_status for group_member in group_members if group_member.id == member.id),
        "Attente",
    )
    calendar_weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(calendar_focus.year, calendar_focus.month):
        calendar_week = []
        for day in week:
            delivery_member = delivery_dates.get(day)
            is_paid = day in paid_dates
            day_title_parts = []
            if delivery_member:
                day_title_parts.append(f"Reception : {delivery_member.full_name}")
            if is_paid:
                day_title_parts.append("Versement deja effectue")
            calendar_week.append(
                {
                    "date": day,
                    "day": day.day,
                    "in_month": day.month == calendar_focus.month,
                    "is_today": day == today,
                    "is_cycle": day in cycle_dates,
                    "is_delivery": bool(delivery_member),
                    "is_member_delivery": bool(delivery_member and delivery_member.id == member.id),
                    "is_paid": is_paid,
                    "delivery_name": delivery_member.full_name if delivery_member else "",
                    "title": " | ".join(day_title_parts),
                }
            )
        calendar_weeks.append(calendar_week)
    return render(
        request,
        "core/member_dashboard.html",
        {
            "member": member,
            "group": group,
            "group_members": group_members,
            "payments": payments,
            "payments_completed_count": payments_completed_count,
            "total_expected_payments": total_expected_payments,
            "remaining_total_payments": remaining_total_payments,
            "announcements": announcements,
            "unread_announcement": unread_announcement,
            "progress": progress,
            "cycle_progress_markers": cycle_progress_markers,
            "total_group_cycles": len(group_members),
            "current_group_cycle": current_member_index + 1 if group_members else 0,
            "ristourne_days_remaining": ristourne_days_remaining,
            "ristourne_ends_on": ristourne_ends_on,
            "cycle_starts_on": cycle_starts_on,
            "cycle_ends_on": cycle_ends_on,
            "next_beneficiary": next_beneficiary,
            "calendar_weeks": calendar_weeks,
            "calendar_focus": calendar_focus,
            "previous_calendar_month": previous_month,
            "next_calendar_month": next_month,
        },
    )


@member_required
def member_catalog(request):
    query = request.GET.get("q", "").strip()
    wigs = (
        WigCatalog.objects.filter(Q(visible_to_groups__isnull=True) | Q(visible_to_groups=request.member.group))
        .prefetch_related("gallery_images")
        .distinct()
    )
    if query:
        wigs = wigs.filter(Q(name__icontains=query) | Q(description__icontains=query) | Q(colors__icontains=query) | Q(sizes__icontains=query))
    return render(
        request,
        "core/member_catalog.html",
        {
            "member": request.member,
            "wigs": wigs,
            "selected": request.member.selected_wig,
            "selected_choice": request.member.selected_wig_choice,
            "has_received_wig": has_received_wig_this_cycle(request.member),
            "query": query,
        },
    )


@member_required
@require_POST
def mark_announcement_read(request, announcement_id):
    member = request.member
    announcement = get_object_or_404(
        Announcement.objects.filter(is_active=True).filter(
            Q(visible_to_groups__isnull=True, visible_to_members__isnull=True)
            | Q(visible_to_groups=member.group)
            | Q(visible_to_members=member)
        ).distinct(),
        id=announcement_id,
    )
    announcement.read_by.add(member)
    return redirect("member_dashboard")


@member_required
@require_POST
def choose_wig(request, wig_id):
    if has_received_wig_this_cycle(request.member):
        messages.error(request, "Vous avez deja recu votre perruque pour ce cycle. Le choix du catalogue est bloque.")
        return redirect("member_catalog")
    wig = get_object_or_404(
        WigCatalog.objects.filter(Q(visible_to_groups__isnull=True) | Q(visible_to_groups=request.member.group)).distinct(),
        id=wig_id,
        is_available=True,
    )
    selected_color = request.POST.get("color", "").strip()
    selected_size = request.POST.get("size", "").strip()
    available_colors = wig.available_colors
    available_sizes = wig.available_sizes
    if available_colors and selected_color not in available_colors:
        messages.error(request, "Veuillez choisir une couleur disponible pour ce modele.")
        return redirect("member_catalog")
    if available_sizes and selected_size not in available_sizes:
        messages.error(request, "Veuillez choisir une taille disponible pour ce modele.")
        return redirect("member_catalog")
    WigChoice.objects.create(member=request.member, wig=wig, color=selected_color, size=selected_size)
    color_suffix = f" en {selected_color}" if selected_color else ""
    size_suffix = f", taille {selected_size}" if selected_size else ""
    messages.success(request, f"{wig.name}{color_suffix}{size_suffix} est maintenant votre choix de perruque.")
    return redirect("member_catalog")


def staff_login(request):
    request.session.pop("member_id", None)
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("staff_dashboard")
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = get_user_model().objects.filter(username=username, is_staff=True).first()
        if user and user.check_password(password):
            login(request, user)
            return redirect("staff_dashboard")
        messages.error(request, "Acces reserve aux administrateurs.")
    return render(request, "core/staff_login.html", {"form": form})


def staff_logout(request):
    logout(request)
    return redirect("login")


def is_staff(user):
    return user.is_authenticated and user.is_staff


staff_required = user_passes_test(is_staff, login_url="staff_login")


def paginate_queryset(request, queryset, per_page=12, page_param="page"):
    paginator = Paginator(queryset, per_page)
    return paginator.get_page(request.GET.get(page_param))


def annotate_member_payment_position(member):
    cycle_quota = max(member.group.expected_payments, 1)
    total_cycles = max(member.group.members.filter(is_active=True).count(), 1)
    total_expected_payments = cycle_quota * total_cycles
    payments_done = member.payments_done
    payments_due = min(member.payments_due, total_expected_payments)
    current_cycle_number = min(max(member.group.current_cycle_number, 1), total_cycles)
    previous_cycles_required = min(max(current_cycle_number - 1, 0) * cycle_quota, total_expected_payments)
    current_cycle_required = min(current_cycle_number * cycle_quota, total_expected_payments)
    current_cycle_due = min(max(payments_due - previous_cycles_required, 0), cycle_quota)
    current_cycle_done = min(max(payments_done - previous_cycles_required, 0), cycle_quota)
    future_payments = max(payments_done - current_cycle_required, 0)
    extra_after_all_cycles = max(payments_done - total_expected_payments, 0)

    member.missing_payments = max(payments_due - payments_done, 0)
    member.late_amount = member.missing_payments * member.group.contribution_amount
    member.ahead_payments = max(payments_done - payments_due, 0)
    member.ahead_amount = member.ahead_payments * member.group.contribution_amount
    member.current_cycle_number = current_cycle_number
    member.current_cycle_due_payments = current_cycle_due
    member.current_cycle_done_payments = current_cycle_done
    member.current_cycle_missing_payments = max(current_cycle_due - current_cycle_done, 0)
    member.current_cycle_late_amount = member.current_cycle_missing_payments * member.group.contribution_amount
    member.current_cycle_ahead_payments = max(current_cycle_done - current_cycle_due, 0)
    member.current_cycle_ahead_amount = member.current_cycle_ahead_payments * member.group.contribution_amount
    member.extra_after_all_cycles = extra_after_all_cycles
    member.extra_after_all_cycles_amount = extra_after_all_cycles * member.group.contribution_amount
    member.no_next_cycle_with_advance = extra_after_all_cycles > 0

    next_cycle_number = current_cycle_number + 1
    if member.no_next_cycle_with_advance:
        member.ahead_note = (
            "Plus de prochain cycle : ce membre a encore "
            f"{member.extra_after_all_cycles_amount} FCFA en avance."
        )
    elif future_payments > 0 and next_cycle_number <= total_cycles:
        next_cycle_payments = min(future_payments, cycle_quota)
        member.ahead_note = (
            f"Avance completee dans le cycle {next_cycle_number} : "
            f"{next_cycle_payments}/{cycle_quota} versement(s)."
        )
    else:
        member.ahead_note = f"{member.ahead_payments} versement(s) en avance sur l'echeance actuelle."
    return member


def filtered_payment_positions(query):
    members = filtered_member_payment_positions(query)
    late_members = [member for member in members if member.missing_payments > 0]
    ahead_members = [member for member in members if member.missing_payments == 0 and member.ahead_payments > 0]
    return late_members, ahead_members


def filtered_member_payment_positions(query):
    payment_members = []
    normalized_query = query.lower()
    members = Member.objects.filter(is_active=True).select_related("group").prefetch_related("payments")
    for member in members:
        annotate_member_payment_position(member)
        if query and normalized_query not in member.full_name.lower() and normalized_query not in member.group.name.lower():
            continue
        payment_members.append(member)
    return payment_members


@staff_required
def staff_dashboard(request):
    query = request.GET.get("q", "").strip()
    total_payments = Payment.objects.filter(status=Payment.Status.CONFIRMED).aggregate(total=Sum("amount"))["total"] or 0
    groups = RistourneGroup.objects.annotate(member_count=Count("members"))
    recent_payments = Payment.objects.select_related("member", "member__group")
    payment_members = filtered_member_payment_positions(query)
    late_members = [member for member in payment_members if member.missing_payments > 0]
    ahead_members = [member for member in payment_members if member.missing_payments == 0 and member.ahead_payments > 0]
    if query:
        groups = groups.filter(Q(name__icontains=query) | Q(members__full_name__icontains=query)).distinct()
        recent_payments = recent_payments.filter(
            Q(member__full_name__icontains=query)
            | Q(member__group__name__icontains=query)
            | Q(status__icontains=query)
            | Q(note__icontains=query)
        )
    context = {
        "total_payments": total_payments,
        "groups_count": RistourneGroup.objects.filter(is_active=True).count(),
        "members_count": Member.objects.filter(is_active=True).count(),
        "late_members": late_members,
        "ahead_members": ahead_members,
        "payment_members": payment_members,
        "groups": groups[:8],
        "recent_payments": recent_payments[:8],
        "query": query,
    }
    return render(request, "core/staff_dashboard.html", context)


@staff_required
def manage_groups(request):
    query = request.GET.get("q", "").strip()
    form = GroupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Groupe enregistre.")
        return redirect("manage_groups")
    groups_queryset = RistourneGroup.objects.all()
    if query:
        groups_queryset = groups_queryset.filter(
            Q(name__icontains=query)
            | Q(members__full_name__icontains=query)
            | Q(cycle_days__icontains=query)
            | Q(contribution_amount__icontains=query)
        ).distinct()
    groups = paginate_queryset(request, groups_queryset, per_page=10)
    return render(request, "core/manage_groups.html", {"form": form, "groups": groups, "form_open": request.method == "POST", "query": query})


@staff_required
def group_detail(request, group_id):
    group = get_object_or_404(RistourneGroup, id=group_id)
    members_queryset = group.ordered_members().annotate(
        total_confirmed_payments=Sum("payments__amount", filter=Q(payments__status=Payment.Status.CONFIRMED))
    )
    members = paginate_queryset(request, members_queryset, per_page=10, page_param="members_page")
    total_group_payments = (
        Payment.objects.filter(member__group=group, member__is_active=True, status=Payment.Status.CONFIRMED).aggregate(total=Sum("amount"))["total"]
        or 0
    )
    return render(
        request,
        "core/detail_group.html",
        {
            "group": group,
            "form": GroupForm(instance=group),
            "members": members,
            "members_page_param": "members_page",
            "total_group_payments": total_group_payments,
        },
    )


@staff_required
def edit_group(request, group_id):
    group = get_object_or_404(RistourneGroup, id=group_id)
    form = GroupForm(request.POST or None, instance=group)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Groupe modifie.")
        return redirect("group_detail", group_id=group.id)
    members_queryset = group.ordered_members().annotate(
        total_confirmed_payments=Sum("payments__amount", filter=Q(payments__status=Payment.Status.CONFIRMED))
    )
    members = paginate_queryset(request, members_queryset, per_page=10, page_param="members_page")
    total_group_payments = (
        Payment.objects.filter(member__group=group, member__is_active=True, status=Payment.Status.CONFIRMED).aggregate(total=Sum("amount"))["total"]
        or 0
    )
    return render(
        request,
        "core/detail_group.html",
        {
            "group": group,
            "form": form,
            "members": members,
            "members_page_param": "members_page",
            "total_group_payments": total_group_payments,
            "edit_open": True,
        },
    )


@staff_required
def manage_members(request):
    query = request.GET.get("q", "").strip()
    form = MemberForm(request.POST or None)
    new_code = None
    if request.method == "POST" and form.is_valid():
        member = form.save(commit=False)
        new_code = generate_member_code()
        member.set_code(new_code)
        member.save()
        messages.success(request, f"Membre ajoute. Code de connexion : {new_code}")
        return redirect("manage_members")
    members_queryset = Member.objects.select_related("group")
    if query:
        members_queryset = members_queryset.filter(
            Q(full_name__icontains=query)
            | Q(group__name__icontains=query)
            | Q(rank__icontains=query)
            | Q(status__icontains=query)
        )
    members = paginate_queryset(request, members_queryset, per_page=12)
    return render(request, "core/manage_members.html", {"form": form, "members": members, "new_code": new_code, "form_open": request.method == "POST", "query": query})


@staff_required
def member_detail_admin(request, member_id):
    member = get_object_or_404(Member.objects.select_related("group"), id=member_id)
    payments = paginate_queryset(request, member.payments.all(), per_page=10, page_param="payments_page")
    total_member_payments = member.payments.filter(status=Payment.Status.CONFIRMED).aggregate(total=Sum("amount"))["total"] or 0
    selected_choice = member.selected_wig_choice
    selected_choice_image = None
    if selected_choice:
        selected_choice_image = selected_choice.wig.gallery_images.filter(color__iexact=selected_choice.color).first()
        if not selected_choice_image:
            selected_choice_image = selected_choice.wig.gallery_images.first()
    return render(
        request,
        "core/detail_member.html",
        {
            "member": member,
            "form": MemberForm(instance=member),
            "payments": payments,
            "payments_page_param": "payments_page",
            "total_member_payments": total_member_payments,
            "selected_choice": selected_choice,
            "selected_choice_image": selected_choice_image,
        },
    )


@staff_required
def edit_member(request, member_id):
    member = get_object_or_404(Member.objects.select_related("group"), id=member_id)
    from_group_id = request.GET.get("from_group")
    return_group = member.group if str(member.group_id) == str(from_group_id) else None
    form = MemberForm(request.POST or None, instance=member)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Membre modifie.")
        if return_group:
            return redirect("group_detail", group_id=return_group.id)
        return redirect("member_detail_admin", member_id=member.id)
    payments = paginate_queryset(request, member.payments.all(), per_page=10, page_param="payments_page")
    total_member_payments = member.payments.filter(status=Payment.Status.CONFIRMED).aggregate(total=Sum("amount"))["total"] or 0
    selected_choice = member.selected_wig_choice
    selected_choice_image = None
    if selected_choice:
        selected_choice_image = selected_choice.wig.gallery_images.filter(color__iexact=selected_choice.color).first()
        if not selected_choice_image:
            selected_choice_image = selected_choice.wig.gallery_images.first()
    return render(
        request,
        "core/detail_member.html",
        {
            "member": member,
            "form": form,
            "payments": payments,
            "payments_page_param": "payments_page",
            "total_member_payments": total_member_payments,
            "selected_choice": selected_choice,
            "selected_choice_image": selected_choice_image,
            "edit_open": True,
            "return_group": return_group,
        },
    )


@staff_required
@require_POST
def regenerate_code(request, member_id):
    member = get_object_or_404(Member, id=member_id)
    new_code = generate_member_code()
    member.set_code(new_code)
    member.save(update_fields=["code_hash"])
    messages.success(request, f"Nouveau code pour {member.full_name} : {new_code}")
    return redirect("manage_members")


@staff_required
def manage_payments(request):
    query = request.GET.get("q", "").strip()
    initial = {"amount": RistourneGroup.objects.first().contribution_amount if RistourneGroup.objects.exists() else 1250}
    form = PaymentForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Paiement enregistre.")
        if request.headers.get("HX-Request"):
            form = PaymentForm(initial=initial)
            payments = paginate_queryset(request, Payment.objects.select_related("member", "member__group"), per_page=12)
            response = render(request, "core/partials/payment_table.html", {"payments": payments, "form": form})
            response["HX-Trigger"] = "paymentSaved"
            return response
        return redirect("manage_payments")
    payments_queryset = Payment.objects.select_related("member", "member__group")
    if query:
        payments_queryset = payments_queryset.filter(
            Q(member__full_name__icontains=query)
            | Q(member__group__name__icontains=query)
            | Q(status__icontains=query)
            | Q(note__icontains=query)
            | Q(amount__icontains=query)
            | Q(paid_on__icontains=query)
        )
    payments = paginate_queryset(request, payments_queryset, per_page=12)
    late_members, ahead_members = filtered_payment_positions(query)
    return render(
        request,
        "core/manage_payments.html",
        {
            "form": form,
            "payments": payments,
            "late_members": late_members,
            "ahead_members": ahead_members,
            "form_open": request.method == "POST",
            "query": query,
        },
    )


@staff_required
def accounting(request):
    form = AccountingWithdrawalForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Retrait enregistre.")
        return redirect("accounting")

    total_payments = Payment.objects.filter(status=Payment.Status.CONFIRMED).aggregate(total=Sum("amount"))["total"] or 0
    total_withdrawals = AccountingWithdrawal.objects.aggregate(total=Sum("amount"))["total"] or 0
    current_balance = total_payments - total_withdrawals

    group_stats = []
    for group in RistourneGroup.objects.all():
        payments_total = Payment.objects.filter(member__group=group, status=Payment.Status.CONFIRMED).aggregate(total=Sum("amount"))["total"] or 0
        withdrawals_total = AccountingWithdrawal.objects.filter(group=group).aggregate(total=Sum("amount"))["total"] or 0
        group_stats.append(
            {
                "group": group,
                "member_count": group.members.filter(is_active=True).count(),
                "payments_total": payments_total,
                "withdrawals_total": withdrawals_total,
                "balance": payments_total - withdrawals_total,
            }
        )

    member_stats = []
    for member in Member.objects.select_related("group"):
        payments_total = member.payments.filter(status=Payment.Status.CONFIRMED).aggregate(total=Sum("amount"))["total"] or 0
        withdrawals_total = member.withdrawals.aggregate(total=Sum("amount"))["total"] or 0
        member_stats.append(
            {
                "member": member,
                "payments_total": payments_total,
                "withdrawals_total": withdrawals_total,
                "balance": payments_total - withdrawals_total,
            }
        )

    cycle_stats = []
    for group in RistourneGroup.objects.all():
        cycle_days = max(group.cycle_days, 1)
        cycle_map = {}
        payments = Payment.objects.filter(member__group=group, status=Payment.Status.CONFIRMED).select_related("member")
        for payment in payments:
            elapsed_days = (payment.paid_on - group.starts_on).days
            cycle_number = max(1, (elapsed_days // cycle_days) + 1)
            cycle_start = group.starts_on + timezone.timedelta(days=(cycle_number - 1) * cycle_days)
            cycle = cycle_map.setdefault(
                cycle_number,
                {
                    "group": group,
                    "cycle_number": cycle_number,
                    "starts_on": cycle_start,
                    "ends_on": cycle_start + timezone.timedelta(days=cycle_days - 1),
                    "payments_total": 0,
                    "withdrawals_total": 0,
                },
            )
            cycle["payments_total"] += payment.amount

        withdrawals = AccountingWithdrawal.objects.filter(group=group)
        for withdrawal in withdrawals:
            elapsed_days = (withdrawal.withdrawn_on - group.starts_on).days
            cycle_number = max(1, (elapsed_days // cycle_days) + 1)
            cycle_start = group.starts_on + timezone.timedelta(days=(cycle_number - 1) * cycle_days)
            cycle = cycle_map.setdefault(
                cycle_number,
                {
                    "group": group,
                    "cycle_number": cycle_number,
                    "starts_on": cycle_start,
                    "ends_on": cycle_start + timezone.timedelta(days=cycle_days - 1),
                    "payments_total": 0,
                    "withdrawals_total": 0,
                },
            )
            cycle["withdrawals_total"] += withdrawal.amount

        for cycle in cycle_map.values():
            cycle["balance"] = cycle["payments_total"] - cycle["withdrawals_total"]
            cycle_stats.append(cycle)

    cycle_stats.sort(key=lambda item: (item["group"].name, item["cycle_number"]))
    group_stats = paginate_queryset(request, group_stats, per_page=10, page_param="groups_page")
    cycle_stats = paginate_queryset(request, cycle_stats, per_page=10, page_param="cycles_page")
    member_stats = paginate_queryset(request, member_stats, per_page=10, page_param="members_page")
    withdrawals = paginate_queryset(
        request,
        AccountingWithdrawal.objects.select_related("group", "member", "member__group"),
        per_page=10,
        page_param="withdrawals_page",
    )

    return render(
        request,
        "core/accounting.html",
        {
            "form": form,
            "form_open": request.method == "POST",
            "total_payments": total_payments,
            "total_withdrawals": total_withdrawals,
            "current_balance": current_balance,
            "group_stats": group_stats,
            "groups_page_param": "groups_page",
            "member_stats": member_stats,
            "members_page_param": "members_page",
            "cycle_stats": cycle_stats,
            "cycles_page_param": "cycles_page",
            "withdrawals": withdrawals,
            "withdrawals_page_param": "withdrawals_page",
        },
    )


@staff_required
def manage_announcements(request):
    query = request.GET.get("q", "").strip()
    form = AnnouncementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Annonce enregistree.")
        return redirect("manage_announcements")
    announcements_queryset = Announcement.objects.prefetch_related("visible_to_groups", "visible_to_members")
    if query:
        announcements_queryset = announcements_queryset.filter(
            Q(title__icontains=query)
            | Q(message__icontains=query)
            | Q(visible_to_groups__name__icontains=query)
            | Q(visible_to_members__full_name__icontains=query)
        ).distinct()
    announcements = paginate_queryset(request, announcements_queryset, per_page=10)
    return render(
        request,
        "core/manage_announcements.html",
        {
            "form": form,
            "announcements": announcements,
            "form_open": request.method == "POST",
            "query": query,
        },
    )


@staff_required
def edit_announcement(request, announcement_id):
    announcement = get_object_or_404(
        Announcement.objects.prefetch_related("visible_to_groups", "visible_to_members"),
        id=announcement_id,
    )
    form = AnnouncementForm(request.POST or None, instance=announcement)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Annonce modifiee.")
        return redirect("manage_announcements")
    announcements = paginate_queryset(
        request,
        Announcement.objects.prefetch_related("visible_to_groups", "visible_to_members"),
        per_page=10,
    )
    return render(
        request,
        "core/manage_announcements.html",
        {
            "form": AnnouncementForm(),
            "announcements": announcements,
            "edit_form": form,
            "edit_announcement": announcement,
            "edit_open": True,
            "query": request.GET.get("q", "").strip(),
        },
    )


@staff_required
def payment_detail(request, payment_id):
    payment = get_object_or_404(Payment.objects.select_related("member", "member__group"), id=payment_id)
    return render(request, "core/detail_payment.html", {"payment": payment, "form": PaymentForm(instance=payment)})


@staff_required
def edit_payment(request, payment_id):
    payment = get_object_or_404(Payment.objects.select_related("member", "member__group"), id=payment_id)
    form = PaymentForm(request.POST or None, instance=payment)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Paiement modifie.")
        return redirect("payment_detail", payment_id=payment.id)
    return render(request, "core/detail_payment.html", {"payment": payment, "form": form, "edit_open": True})


@staff_required
def manage_catalog(request):
    query = request.GET.get("q", "").strip()
    form = WigForm()
    image_form = WigImageForm()
    form_open = None
    if request.method == "POST" and request.POST.get("form_type") == "image":
        form_open = "image"
        image_form = WigImageForm(request.POST, request.FILES)
        if image_form.is_valid():
            image_form.save()
            messages.success(request, "Image ajoutee au modele.")
            return redirect("manage_catalog")
    elif request.method == "POST":
        form_open = "model"
        form = WigForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Modele ajoute au catalogue.")
            return redirect("manage_catalog")
    wigs_queryset = WigCatalog.objects.prefetch_related("gallery_images")
    if query:
        wigs_queryset = wigs_queryset.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(colors__icontains=query)
            | Q(sizes__icontains=query)
            | Q(gallery_images__color__icontains=query)
        ).distinct()
    return render(
        request,
        "core/manage_catalog.html",
        {
            "form": form,
            "image_form": image_form,
            "wigs": paginate_queryset(request, wigs_queryset, per_page=10),
            "gallery_images": WigImage.objects.select_related("wig")[:30],
            "form_open": form_open,
            "query": query,
        },
    )


@staff_required
def catalog_detail(request, wig_id):
    wig = get_object_or_404(WigCatalog.objects.prefetch_related("gallery_images"), id=wig_id)
    images = paginate_queryset(request, wig.gallery_images.all(), per_page=12, page_param="images_page")
    return render(request, "core/detail_catalog.html", {"wig": wig, "form": WigForm(instance=wig), "image_form": WigImageForm(initial={"wig": wig}), "images": images, "images_page_param": "images_page"})


@staff_required
def edit_catalog(request, wig_id):
    wig = get_object_or_404(WigCatalog.objects.prefetch_related("gallery_images"), id=wig_id)
    form = WigForm(request.POST or None, request.FILES or None, instance=wig)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Modele modifie.")
        return redirect("catalog_detail", wig_id=wig.id)
    images = paginate_queryset(request, wig.gallery_images.all(), per_page=12, page_param="images_page")
    return render(request, "core/detail_catalog.html", {"wig": wig, "form": form, "image_form": WigImageForm(initial={"wig": wig}), "images": images, "images_page_param": "images_page", "edit_open": True})


@staff_required
@require_POST
def edit_wig_image(request, image_id):
    wig_image = get_object_or_404(WigImage.objects.select_related("wig"), id=image_id)
    form = WigImageForm(request.POST, request.FILES, instance=wig_image)
    if form.is_valid():
        form.save()
        messages.success(request, "Image couleur modifiee.")
    else:
        messages.error(request, "Impossible de modifier cette image couleur.")
    return redirect("catalog_detail", wig_id=wig_image.wig_id)

# Create your views here.
