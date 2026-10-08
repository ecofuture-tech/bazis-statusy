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

"""
The ru catalog of the package translates the msgids it shares with the other Bazis packages
as they do: when two catalogs translate the same msgid, the first one in LOCALE_PATHS wins,
so the title of a field would depend on the packages a project installs.
"""

import gettext
from pathlib import Path

import bazis.contrib.statusy


LOCALE = Path(bazis.contrib.statusy.__file__).parent / 'locale'


def test_shared_terms():
    catalog = gettext.translation('django', LOCALE, languages=['ru'])

    assert catalog.gettext('Name') == 'Название'
