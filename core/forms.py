from django import forms

from .models import Member, Payment, RistourneGroup, WigCatalog, WigImage


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
    class Meta:
        model = Payment
        fields = ["member", "amount", "paid_on", "status", "note"]
        widgets = {"paid_on": forms.DateInput(attrs={"type": "date"})}


class WigForm(forms.ModelForm):
    class Meta:
        model = WigCatalog
        fields = ["name", "description", "image", "colors", "sizes", "is_available"]
        widgets = {
            "colors": forms.TextInput(attrs={"placeholder": "Noir, Marron, Blond, Bordeaux"}),
            "sizes": forms.TextInput(attrs={"placeholder": "S, M, L, XL ou 10 pouces, 12 pouces, 14 pouces"}),
        }


class WigImageForm(forms.ModelForm):
    class Meta:
        model = WigImage
        fields = ["wig", "color", "image", "order"]
        widgets = {
            "color": forms.TextInput(attrs={"placeholder": "Noir"}),
        }
