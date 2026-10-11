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

    # a route class defined here becomes the default route of the model: restore the route
    # of the sample for the other tests
    monkeypatch.setattr(ParentEntity, '_default_route', ParentEntity._default_route)

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


@pytest.mark.django_db(transaction=True)
def test_catalog_routes_are_public(sample_app):
    """
    The routes of `bazis.contrib.statusy.router` (registered by the sample) are a public
    catalog: `permit.W002` does not report them, an anonymous user reads them, and a transit
    shows its names, hints, model and statuses, not how it runs (its methods, its link in
    the code, its validation, its related transits).
    """
    from bazis_test_utils.utils import get_api_client
    from entity.models import ParentEntity
    from translated_fields import to_attribute

    from bazis.contrib.permit.checks import check_routes_permit
    from bazis.contrib.statusy.models import Status, StatusyContentType, Transit

    warnings = {it.obj.__qualname__ for it in check_routes_permit(None)}
    assert not warnings & {'StatusRoute', 'TransitRoute'}

    name = to_attribute('name')
    StatusyContentType.objects.clear_cache()
    draft = Status.objects.get_or_create(id='draft', defaults={name: 'Draft'})[0]
    check = Status.objects.get_or_create(id='check', defaults={name: 'Check'})[0]
    Transit.objects.create(
        id='catalog_check',
        model=StatusyContentType.objects.get_for_model(ParentEntity),
        status_src=draft,
        status_dst=check,
        validators=['secret_validator'],
        actions_before=['secret_before'],
        source_link='entity.workflow',
        hint_action='Check it',
        **{name: 'To check'},
    )
    client = get_api_client(sample_app)
    response = client.get('/api/v1/statusy/status/draft/')
    assert response.status_code == 200, response.content
    assert set(response.json()['data']['attributes']) == {'name'}
    response = client.get('/api/v1/statusy/transit/catalog_check/')
    assert response.status_code == 200, response.content
    data = response.json()['data']
    assert set(data['attributes']) == {'name', 'hint', 'hint_title', 'hint_action'}
    assert set(data['relationships']) == {'model', 'status_src', 'status_dst'}
    assert 'secret' not in response.text and 'entity.workflow' not in response.text
    assert client.get('/api/v1/statusy/transit/').status_code == 200
