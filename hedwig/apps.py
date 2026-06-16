from django.apps import AppConfig


class HedwigConfig(AppConfig):
    name = "hedwig"

    def ready(self):
        from hedwig import signals  # noqa: F401
