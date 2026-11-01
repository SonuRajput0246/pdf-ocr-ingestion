from __future__ import annotations

import pytest

from app.api import create_app
from tests.helpers import make_service


@pytest.fixture
def api(tmp_path):
    settings, service, engine = make_service(tmp_path)
    app = create_app(settings=settings, service=service)
    app.config.update(TESTING=True)
    with app.test_client() as client:
        yield client, service, engine
