import os
import tempfile

from django.core.management import call_command

import pytest


@pytest.fixture(scope='session')
def django_db_setup(django_db_setup, django_db_blocker) -> None:
    with django_db_blocker.unblock():
        call_command('pgtrigger', 'install')


@pytest.fixture(scope='function')
def sample_app():
    from sample.main import app

    return app


@pytest.fixture(scope='session')
def temp_file():
    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        tmp_file.write(b"Hello, this is a test file.")
        tmp_file_path = tmp_file.name

    yield tmp_file_path

    os.remove(tmp_file_path)
