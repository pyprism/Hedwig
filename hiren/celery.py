import os

from celery import Celery
from celery.signals import task_prerun


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hiren.settings")

app = Celery("hedwig")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@task_prerun.connect
def _bind_task_request_id(task_id=None, **kwargs):
    """Tag log records emitted during a task with its Celery task id."""
    from utils.logging import set_request_id

    set_request_id(task_id)
