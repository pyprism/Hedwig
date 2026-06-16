from django_filters.rest_framework import DjangoFilterBackend


class SchemaDjangoFilterBackend(DjangoFilterBackend):
    """django-filter backend with DRF OpenAPI schema compatibility."""

    def get_schema_operation_parameters(self, view):
        filterset_class = self.get_filterset_class(view, None)
        if filterset_class is None:
            return []

        return [
            {
                "name": name,
                "required": False,
                "in": "query",
                "description": f"Filter by {name}.",
                "schema": {"type": "string"},
            }
            for name in filterset_class.get_filters()
        ]
