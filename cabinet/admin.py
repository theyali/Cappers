from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AnalystFollow, AnalystProfile, User


@admin.register(User)
class CabinetUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Профиль", {"fields": ("role",)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Профиль", {"fields": ("role",)}),
    )
    list_display = ("username", "email", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active")


@admin.register(AnalystProfile)
class AnalystProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "display_name",
        "is_verified",
        "is_public",
        "created_at",
    )
    list_filter = ("is_verified", "is_public", "created_at")
    search_fields = ("user__username", "user__email", "display_name")
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(AnalystFollow)
class AnalystFollowAdmin(admin.ModelAdmin):
    list_display = ("follower", "analyst", "created_at")
    search_fields = ("follower__username", "analyst__username")
    autocomplete_fields = ("follower", "analyst")
    readonly_fields = ("created_at",)
