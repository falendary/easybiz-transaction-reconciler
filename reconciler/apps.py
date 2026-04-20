from django.apps import AppConfig


class ReconcilerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reconciler"

    def ready(self) -> None:
        import reconciler.signals  # noqa: F401 — registers signal handlers
