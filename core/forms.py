from django import forms

from .models import AccountingWithdrawal, Announcement, Member, Payment, RistourneGroup, WigCatalog, WigImage


class CodeLoginForm(forms.Form):
    code = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code", "placeholder": "A4F92C"}),
    )

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()


class GroupForm(forms.ModelForm):
    class Meta:
        model = RistourneGroup
        fields = ["name", "cycle_days", "contribution_amount", "payment_frequency_days", "starts_on", "is_active"]
        widgets = {"starts_on": forms.DateInput(attrs={"type": "date"})}


class MemberForm(forms.ModelForm):
    class Meta:
        model = Member
        fields = ["full_name", "group", "rank", "status", "joined_at", "is_active"]
        widgets = {"joined_at": forms.DateInput(attrs={"type": "date"})}


class PaymentForm(forms.ModelForm):
    member = forms.ModelChoiceField(
        label="Membre",
        queryset=Member.objects.select_related("group").filter(is_active=True),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["member"].label_from_instance = lambda member: f"{member.full_name} ({member.group.name})"

    class Meta:
        model = Payment
        fields = ["member", "amount", "paid_on", "status", "note"]
        widgets = {"paid_on": forms.DateInput(attrs={"type": "date"})}


class AccountingWithdrawalForm(forms.ModelForm):
    class Meta:
        model = AccountingWithdrawal
        fields = ["amount", "withdrawn_on", "group", "member", "note"]
        widgets = {"withdrawn_on": forms.DateInput(attrs={"type": "date"})}


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ["title", "message", "visible_to_groups", "visible_to_members", "is_active"]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Ex. Reunion importante, changement de date..."}),
            "message": forms.Textarea(attrs={"rows": 4, "placeholder": "Ecrivez le message qui sera affiche aux membres concernes."}),
            "visible_to_groups": forms.CheckboxSelectMultiple(attrs={"class": "announcement-checkboxes"}),
            "visible_to_members": forms.CheckboxSelectMultiple(attrs={"class": "announcement-checkboxes"}),
        }


class WigForm(forms.ModelForm):
    class Meta:
        model = WigCatalog
        fields = ["name", "description", "image", "colors", "sizes", "visible_to_groups", "is_available"]
        widgets = {
            "colors": forms.TextInput(attrs={"placeholder": "Noir, Marron, Blond, Bordeaux"}),
            "sizes": forms.TextInput(attrs={"placeholder": "S, M, L, XL ou 10 pouces, 12 pouces, 14 pouces"}),
            "visible_to_groups": forms.CheckboxSelectMultiple(),
        }


class WigImageForm(forms.ModelForm):
    class Meta:
        model = WigImage
        fields = ["wig", "color", "image", "order"]
        widgets = {
            "color": forms.TextInput(attrs={"placeholder": "Noir"}),
        }
