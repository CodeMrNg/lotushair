import calendar
from datetime import date

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import AuthenticationForm
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import CodeLoginForm, GroupForm, MemberForm, PaymentForm, WigForm, WigImageForm
from .models import Member, Payment, RistourneGroup, WigCatalog, WigChoice, WigImage, generate_member_code


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
    payments = member.payments.all()[:8]
    total_paid = member.payments.filter(status=Payment.Status.CONFIRMED).aggregate(total=Sum("amount"))["total"] or 0
    progress = min(int((group.current_day / group.cycle_days) * 100), 100) if group.cycle_days else 0
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
    next_beneficiary = group.next_beneficiary()
    delivery_dates = {}
    current_member_index = group_members.index(next_beneficiary) if next_beneficiary in group_members else 0
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
            calendar_week.append(
                {
                    "date": day,
                    "day": day.day,
                    "in_month": day.month == calendar_focus.month,
                    "is_today": day == today,
                    "is_cycle": day in cycle_dates,
                    "is_delivery": bool(delivery_member),
                    "is_member_delivery": bool(delivery_member and delivery_member.id == member.id),
                    "delivery_name": delivery_member.full_name if delivery_member else "",
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
            "total_paid": total_paid,
            "progress": progress,
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
    wigs = WigCatalog.objects.prefetch_related("gallery_images")
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
def choose_wig(request, wig_id):
    if has_received_wig_this_cycle(request.member):
        messages.error(request, "Vous avez deja recu votre perruque pour ce cycle. Le choix du catalogue est bloque.")
        return redirect("member_catalog")
    wig = get_object_or_404(WigCatalog, id=wig_id, is_available=True)
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
    if request.method == "POST" and form.is_valid():
        user = authenticate(username=form.cleaned_data["username"], password=form.cleaned_data["password"])
        if user and user.is_staff:
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


@staff_required
def staff_dashboard(request):
    total_payments = Payment.objects.filter(status=Payment.Status.CONFIRMED).aggregate(total=Sum("amount"))["total"] or 0
    context = {
        "total_payments": total_payments,
        "groups_count": RistourneGroup.objects.filter(is_active=True).count(),
        "members_count": Member.objects.filter(is_active=True).count(),
        "late_members": [member for member in Member.objects.filter(is_active=True).select_related("group") if member.is_late],
        "groups": RistourneGroup.objects.annotate(member_count=Count("members")),
        "recent_payments": Payment.objects.select_related("member", "member__group")[:8],
    }
    return render(request, "core/staff_dashboard.html", context)


@staff_required
def manage_groups(request):
    form = GroupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Groupe enregistre.")
        return redirect("manage_groups")
    groups = paginate_queryset(request, RistourneGroup.objects.all(), per_page=10)
    return render(request, "core/manage_groups.html", {"form": form, "groups": groups, "form_open": request.method == "POST"})


@staff_required
def group_detail(request, group_id):
    group = get_object_or_404(RistourneGroup, id=group_id)
    members = paginate_queryset(request, group.ordered_members(), per_page=10, page_param="members_page")
    return render(request, "core/detail_group.html", {"group": group, "form": GroupForm(instance=group), "members": members, "members_page_param": "members_page"})


@staff_required
def edit_group(request, group_id):
    group = get_object_or_404(RistourneGroup, id=group_id)
    form = GroupForm(request.POST or None, instance=group)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Groupe modifie.")
        return redirect("group_detail", group_id=group.id)
    members = paginate_queryset(request, group.ordered_members(), per_page=10, page_param="members_page")
    return render(request, "core/detail_group.html", {"group": group, "form": form, "members": members, "members_page_param": "members_page", "edit_open": True})


@staff_required
def manage_members(request):
    form = MemberForm(request.POST or None)
    new_code = None
    if request.method == "POST" and form.is_valid():
        member = form.save(commit=False)
        new_code = generate_member_code()
        member.set_code(new_code)
        member.save()
        messages.success(request, f"Membre ajoute. Code de connexion : {new_code}")
        return redirect("manage_members")
    members = paginate_queryset(request, Member.objects.select_related("group"), per_page=12)
    return render(request, "core/manage_members.html", {"form": form, "members": members, "new_code": new_code, "form_open": request.method == "POST"})


@staff_required
def member_detail_admin(request, member_id):
    member = get_object_or_404(Member.objects.select_related("group"), id=member_id)
    payments = paginate_queryset(request, member.payments.all(), per_page=10, page_param="payments_page")
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
            "selected_choice": selected_choice,
            "selected_choice_image": selected_choice_image,
        },
    )


@staff_required
def edit_member(request, member_id):
    member = get_object_or_404(Member.objects.select_related("group"), id=member_id)
    form = MemberForm(request.POST or None, instance=member)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Membre modifie.")
        return redirect("member_detail_admin", member_id=member.id)
    payments = paginate_queryset(request, member.payments.all(), per_page=10, page_param="payments_page")
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
            "selected_choice": selected_choice,
            "selected_choice_image": selected_choice_image,
            "edit_open": True,
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
    payments = paginate_queryset(request, Payment.objects.select_related("member", "member__group"), per_page=12)
    return render(request, "core/manage_payments.html", {"form": form, "payments": payments, "form_open": request.method == "POST"})


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
    return render(
        request,
        "core/manage_catalog.html",
        {
            "form": form,
            "image_form": image_form,
            "wigs": paginate_queryset(request, WigCatalog.objects.prefetch_related("gallery_images"), per_page=10),
            "gallery_images": WigImage.objects.select_related("wig")[:30],
            "form_open": form_open,
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
