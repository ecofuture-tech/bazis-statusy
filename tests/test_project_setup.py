# Copyright 2026 EcoFuture Technology Services LLC and contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import subprocess
import sys
from pathlib import Path


SAMPLE = Path(__file__).resolve().parent.parent / 'sample'


def test_project_loads_without_its_database():
    """
    The routes of a model with a status are built and the checks run before the database
    of the project is created: the default status comes from the settings then.
    """
    env = {**os.environ, 'BS_DATABASES__DEFAULT__NAME': 'statusy_no_such_database'}
    done = subprocess.run(
        [sys.executable, 'manage.py', 'bazis_doctor', '--json'],
        cwd=SAMPLE, env=env, capture_output=True, text=True, timeout=300,
    )

    assert done.returncode == 0, done.stderr[-3000:]
    messages = json.loads(done.stdout[done.stdout.index('['):])
    assert [m['id'] for m in messages if m['level'] in ('error', 'critical')] == []


def test_migrations_do_not_depend_on_the_languages_of_the_project():
    """
    The translated fields of the package have the columns of its migrations whatever the
    languages of the project: makemigrations must not write a migration into the package.
    """
    env = {
        **os.environ,
        'BS_DATABASES__DEFAULT__NAME': 'statusy_no_such_database',
        'BS_LANGUAGES': '[["en", "English"]]',
    }
    done = subprocess.run(
        [sys.executable, 'manage.py', 'makemigrations', 'statusy', 'permit', '--check', '--dry-run'],
        cwd=SAMPLE, env=env, capture_output=True, text=True, timeout=300,
    )

    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]


def test_a_language_without_a_column():
    """
    In a language the fields have no column for, the names are read and written in the
    fallback language, also the name of the default status.
    """
    from django.utils import translation

    from bazis.contrib.statusy.models import Status, Transit
    from bazis.contrib.statusy.models_abstract import LANGUAGES, name_column

    fallback = LANGUAGES[0]
    with translation.override('de'):
        assert name_column() == f'name_{fallback}'
        status, transit = Status(id='new'), Transit()
        status.name, transit.name, transit.hint_title = 'New', 'Pay', 'Payment'
        assert status.name == 'New'
    assert getattr(status, f'name_{fallback}') == 'New'
    assert getattr(transit, f'name_{fallback}') == 'Pay'
    assert getattr(transit, f'hint_title_{fallback}') == 'Payment'
    assert name_column('hint_title', 'ru') == 'hint_title_ru'
    assert name_column(language='en-us') == 'name_en'
