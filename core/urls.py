from django.urls import path

from . import views

urlpatterns = [
    path("", views.member_login, name="login"),
    path("conditions/", views.terms, name="terms"),
    path("deconnexion/", views.member_logout, name="logout"),
    path("membre/", views.member_dashboard, name="member_dashboard"),
    path("membre/catalogue/", views.member_catalog, name="member_catalog"),
    path("membre/catalogue/<int:wig_id>/choisir/", views.choose_wig, name="choose_wig"),
    path("gestion/connexion/", views.staff_login, name="staff_login"),
    path("gestion/deconnexion/", views.staff_logout, name="staff_logout"),
    path("gestion/", views.staff_dashboard, name="staff_dashboard"),
    path("gestion/groupes/", views.manage_groups, name="manage_groups"),
    path("gestion/groupes/<int:group_id>/", views.group_detail, name="group_detail"),
    path("gestion/groupes/<int:group_id>/modifier/", views.edit_group, name="edit_group"),
    path("gestion/membres/", views.manage_members, name="manage_members"),
    path("gestion/membres/<int:member_id>/", views.member_detail_admin, name="member_detail_admin"),
    path("gestion/membres/<int:member_id>/modifier/", views.edit_member, name="edit_member"),
    path("gestion/membres/<int:member_id>/code/", views.regenerate_code, name="regenerate_code"),
    path("gestion/paiements/", views.manage_payments, name="manage_payments"),
    path("gestion/paiements/<int:payment_id>/", views.payment_detail, name="payment_detail"),
    path("gestion/paiements/<int:payment_id>/modifier/", views.edit_payment, name="edit_payment"),
    path("gestion/catalogue/", views.manage_catalog, name="manage_catalog"),
    path("gestion/catalogue/<int:wig_id>/", views.catalog_detail, name="catalog_detail"),
    path("gestion/catalogue/<int:wig_id>/modifier/", views.edit_catalog, name="edit_catalog"),
    path("gestion/catalogue/images/<int:image_id>/modifier/", views.edit_wig_image, name="edit_wig_image"),
]
