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
The history of the transits of an item, `GET /{item_id}/status_history/`: the transit with
its name, the statuses, the time, the author and the payload the transit was made with
(`extra['payload']` of the history record). It needs the `history` permission of the item,
and the item must be visible.
"""

from datetime import UTC, datetime

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import ParentEntity
from translated_fields import to_attribute

from bazis.contrib.permit.models import GroupPermission, Permission, Role
from bazis.contrib.statusy.models import Status, StatusyContentType, Transit
from bazis.contrib.users import get_user_model
from bazis.core.routes_abstract.initial import OPENAPI_EXTENSION


URL = '/api/v1/entity/parent_entity/'
PAYLOAD = {'dt_approved': '2026-03-01T10:00:00Z'}


@pytest.fixture
def setup(db):
    name = to_attribute('name')
    Status.get_status_initial()
    StatusyContentType.objects.clear_cache()
    draft = Status.objects.get_or_create(id='draft', defaults={name: 'Draft'})[0]
    active = Status.objects.get_or_create(id='active', defaults={name: 'Active'})[0]
    content_type = StatusyContentType.objects.get_for_model(ParentEntity)
    transits = {
        # the payload type of the sample model: the action before of `dt_approved`
        'activate': Transit.objects.create(
            id='activate',
            model=content_type,
            status_src=draft,
            status_dst=active,
            actions_before=['before_dt_approved'],
            **{name: 'Activate'},
        ),
        'back': Transit.objects.create(
            id='back', model=content_type, status_src=active, status_dst=draft, **{name: 'Back'}
        ),
    }
    group = GroupPermission.objects.create(slug='authors', **{name: 'Authors'})
    for slug in (
        'entity.parent_entity.item.view.author.all',
        'entity.parent_entity.item.history.author.all',
        'entity.parent_entity.item.transit.author.draft.activate',
    ):
        group.permissions.add(Permission.objects.get_or_create(slug=slug)[0])
    role = Role.objects.create(slug='authors', **{name: 'Authors'})
    role.groups_permission.add(group)

    # views the items, reads no history
    viewer_group = GroupPermission.objects.create(slug='viewers', **{name: 'Viewers'})
    viewer_group.permissions.add(
        Permission.objects.get_or_create(slug='entity.parent_entity.item.view.all.all')[0]
    )
    viewer_role = Role.objects.create(slug='viewers', **{name: 'Viewers'})
    viewer_role.groups_permission.add(viewer_group)

    users = []
    for username in ('author', 'other', 'viewer'):
        user = get_user_model().objects.create_user(username, email=f'{username}@site.com')
        user.roles.add(viewer_role if username == 'viewer' else role)
        user.refresh_from_db()
        users.append(user)
    return transits, *users


@pytest.mark.django_db(transaction=True)
def test_status_history_route(sample_app, setup):
    transits, author, other, viewer = setup
    item = ParentEntity.objects.create(
        name='Entity', author=author, dt_approved=datetime(2026, 1, 1, tzinfo=UTC)
    )
    client = get_api_client(sample_app, author.jwt_build())
    url = f'{URL}{item.pk}/status_history/'

    response = client.get(url)
    assert response.status_code == 200, response.text
    assert response.json() == {'data': []}

    # a transit of the user with a payload (a field the payload type excludes is not kept),
    # then one of the system without one
    response = client.post(
        f'{URL}{item.pk}/transit/',
        json_data={'transit': 'activate', 'payload': PAYLOAD | {'secret': 'token'}},
    )
    assert response.status_code == 200, response.text
    ParentEntity.objects.get(pk=item.pk).transit_apply(transits['back'], None)

    response = client.get(url)
    assert response.status_code == 200, response.text
    first, second = response.json()['data']
    assert first['transit'] == {'id': 'activate', 'name': 'Activate'}
    assert (first['status_src'], first['status_dst']) == ('draft', 'active')
    assert first['author'] == {'id': str(author.pk), 'type': 'users.user'}
    assert first['payload'] == {'dt_approved': '2026-03-01T10:00:00Z'}
    assert second['transit'] == {'id': 'back', 'name': 'Back'}
    assert (second['status_src'], second['status_dst']) == ('active', 'draft')
    assert (second['author'], second['payload']) == (None, None)
    records = list(item.statusy_transits.order_by('dt'))
    assert [datetime.fromisoformat(it['dt']) for it in (first, second)] == [r.dt for r in records]
    assert records[0].extra == {'payload': {'dt_approved': '2026-03-01T10:00:00Z'}}
    assert records[1].extra == {}

    # a transit of the code keeps its payload the same way
    ParentEntity.objects.get(pk=item.pk).transit_apply(transits['activate'], None, PAYLOAD)
    last = client.get(url).json()['data'][-1]
    assert last['payload'] == {'dt_approved': '2026-03-01T10:00:00Z'}

    # the permission to view the item is not the one to read its history
    viewer_client = get_api_client(sample_app, viewer.jwt_build())
    assert viewer_client.get(f'{URL}{item.pk}/').status_code == 200
    assert viewer_client.get(url).status_code == 403

    # an item the user does not view is not found, as at its retrieve
    assert get_api_client(sample_app, other.jwt_build()).get(url).status_code == 404
    anonymous = get_api_client(sample_app, None)
    assert anonymous.get(url).status_code == anonymous.get(f'{URL}{item.pk}/').status_code


def test_status_history_openapi(sample_app):
    paths = sample_app.openapi()['paths']
    history = paths[f'{URL}{{item_id}}/status_history/']['get'][OPENAPI_EXTENSION]
    assert (history['kind'], history['public'], history['access_action']) == (
        'other',
        False,
        'history',
    )
    # a route set that lists its actions without it does not give it
    assert '/api/v1/entity/parent_entity_guest/{item_id}/status_history/' not in paths
