# apps/composer/tests/test_schedule_now.py
import pytest
from apps.composer.models import Post
from apps.composer.views import schedule_now


@pytest.mark.django_db
def test_schedule_now_sets_effective_now(workspace):
    post = Post.objects.create(workspace=workspace, title="P", caption="c",
        review_state="approved")
    assert post.scheduled_at is None
    schedule_now(post)
    post.refresh_from_db()
    assert post.scheduled_at is not None
