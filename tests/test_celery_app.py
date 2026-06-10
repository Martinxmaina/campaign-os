def test_celery_app_imports_and_names():
    from config.celery import app
    assert app.main == "campaign_os"


def test_celery_broker_derives_from_redis_url(settings):
    settings.REDIS_URL = "redis://localhost:6379/0"
    from config.celery import build_broker_url
    assert build_broker_url("redis://localhost:6379/0") == "redis://localhost:6379/1"


def test_celery_app_is_eager_in_tests(settings):
    assert settings.CELERY_TASK_ALWAYS_EAGER is True
