import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class IntelligenceConfig(AppConfig):
    name = "apps.intelligence"
    label = "intelligence"
    default_auto_field = "django.db.models.BigAutoField"
