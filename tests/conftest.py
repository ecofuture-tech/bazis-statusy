from django.core.management import call_command

import pytest


@pytest.fixture(scope='session')
def django_db_setup(django_db_setup, django_db_blocker) -> None:
    with django_db_blocker.unblock():
        call_command('pgtrigger', 'install')


@pytest.fixture(scope='function')
def sample_app():
    from sample.main import app

    yield app
