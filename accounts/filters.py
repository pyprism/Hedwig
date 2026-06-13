import django_filters

from accounts.models import User


class UserFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(method="filter_search")

    class Meta:
        model = User
        fields = ["is_active", "is_staff", "must_change_password"]

    def filter_search(self, queryset, name, value):
        return queryset.search(value)
