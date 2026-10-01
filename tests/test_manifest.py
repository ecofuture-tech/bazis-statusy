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

import pytest

from bazis.contrib.statusy.checks import check_routes_statusy
from bazis.core.introspect import validate_manifest


def test_manifest_is_valid():
    assert validate_manifest('bazis.contrib.statusy') == []


@pytest.mark.django_db
def test_routes_without_transits(sample_app, monkeypatch):
    from entity.models import ParentEntity
    from entity.routes import ParentEntityRouteSet

    from bazis.contrib.permit.routes_abstract import PermitRouteBase
    from bazis.core import introspect

    # the routes of the sample support transitions
    assert check_routes_statusy(None) == []

    class PlainParentRoute(PermitRouteBase):
        model = ParentEntity

    class ReadOnlyParentRoute(PermitRouteBase):
        model = ParentEntity

    update = [{'path': '/x/{item_id}/', 'methods': ['PATCH'], 'action': 'action_update'}]
    read = [{'path': '/x/', 'methods': ['GET'], 'action': 'action_list'}]
    monkeypatch.setattr(
        introspect,
        'route_sets',
        lambda app: {
            ParentEntityRouteSet: update,
            PlainParentRoute: update,
            ReadOnlyParentRoute: read,
        },
    )
    # a read-only route needs no transitions
    assert [(it.id, it.obj) for it in check_routes_statusy(None)] == [
        ('statusy.W001', PlainParentRoute)
    ]
