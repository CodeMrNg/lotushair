from django.contrib import admin

from .models import AccountingWithdrawal, Announcement, Member, Notification, Payment, RistourneGroup, WigCatalog, WigChoice, WigImage


@admin.register(RistourneGroup)
class RistourneGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "contribution_amount", "payment_frequency_days", "cycle_days", "is_active")
    search_fields = ("name",)


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ("full_name", "group", "rank", "status", "is_active", "joined_at")
    list_filter = ("group", "status", "is_active")
    search_fields = ("full_name",)
    readonly_fields = ("code_hash",)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("member", "amount", "paid_on", "status")
    list_filter = ("status", "paid_on", "member__group")
    search_fields = ("member__full_name",)


@admin.register(AccountingWithdrawal)
class AccountingWithdrawalAdmin(admin.ModelAdmin):
    list_display = ("amount", "withdrawn_on", "group", "member")
    list_filter = ("withdrawn_on", "group", "member__group")
    search_fields = ("group__name", "member__full_name", "note")


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "is_active", "created_at")
    list_filter = ("is_active", "visible_to_groups")
    search_fields = ("title", "message", "visible_to_members__full_name", "visible_to_groups__name")
    filter_horizontal = ("visible_to_groups", "visible_to_members", "read_by")


@admin.register(WigCatalog)
class WigCatalogAdmin(admin.ModelAdmin):
    list_display = ("name", "colors", "sizes", "is_available", "created_at")
    list_filter = ("is_available", "visible_to_groups")
    search_fields = ("name", "description", "colors", "sizes")
    filter_horizontal = ("visible_to_groups",)


admin.site.register(WigChoice)
admin.site.register(WigImage)
admin.site.register(Notification)

# Register your models here.
