from rest_framework.permissions import SAFE_METHODS, BasePermission


PASSWORD_CHANGE_ALLOWED_ACTIONS = {"change_password", "me"}


def _passes_password_change_gate(request, view):
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return True
    if not getattr(user, "must_change_password", False):
        return True
    return getattr(view, "action", None) in PASSWORD_CHANGE_ALLOWED_ACTIONS


class MustChangePasswordPermission(BasePermission):
    message = "Password change required before using this endpoint."

    def has_permission(self, request, view):
        return _passes_password_change_gate(request, view)

    def has_object_permission(self, request, view, obj):
        return _passes_password_change_gate(request, view)


class IsStaffOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if not _passes_password_change_gate(request, view):
            return False
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return bool(request.user and request.user.is_staff)


class IsStaffUser(BasePermission):
    def has_permission(self, request, view):
        if not _passes_password_change_gate(request, view):
            return False
        return bool(request.user and request.user.is_staff)


class IsStaffOrSelf(BasePermission):
    def has_object_permission(self, request, view, obj):
        if not _passes_password_change_gate(request, view):
            return False
        return bool(
            request.user and (request.user.is_staff or obj.pk == request.user.pk)
        )

    def has_permission(self, request, view):
        if not _passes_password_change_gate(request, view):
            return False
        return bool(request.user and request.user.is_authenticated)
