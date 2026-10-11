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
The history of the transits of an item in the API: the calculated field `status_history`
of `StatusyMixin`, added to a route with `include` (the sample route of the parent
entities). It is a field of the item: whoever views the item reads it, nobody else.
"""

from datetime import UTC, datetime

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import ParentEntity
from translated_fields import to_attribute

from bazis.contrib.permit.models import GroupPermission, Permission, Role
from bazis.contrib.statusy.models import Status, StatusyContentType, Transit
from bazis.contrib.users import get_user_model


URL = '/api/v1/entity/parent_entity/'


@pytest.fixture
def setup(db):
    name = to_attribute('name')
    Status.get_status_initial()
    StatusyContentType.objects.clear_cache()
    draft = Status.objects.get_or_create(id='draft', defaults={name: 'Draft'})[0]
    active = Status.objects.get_or_create(id='active', defaults={name: 'Active'})[0]
    content_type = StatusyContentType.objects.get_for_model(ParentEntity)
    transits = {
        transit_id: Transit.objects.create(
            id=transit_id, model=content_type, status_src=src, status_dst=dst, **{name: transit_id}
        )
        for transit_id, src, dst in (('activate', draft, active), ('back', active, draft))
    }
    group = GroupPermission.objects.create(slug='authors', **{name: 'Authors'})
    for slug in (
        'entity.parent_entity.item.view.author.all',
        'entity.parent_entity.item.transit.author.draft.activate',
    ):
        group.permissions.add(Permission.objects.get_or_create(slug=slug)[0])
    role = Role.objects.create(slug='authors', **{name: 'Authors'})
    role.groups_permission.add(group)

    users = []
    for username in ('author', 'other'):
        user = get_user_model().objects.create_user(username, email=f'{username}@site.com')
        user.roles.add(role)
        user.refresh_from_db()
        users.append(user)
    return transits, *users


@pytest.mark.django_db(transaction=True)
def test_status_history(sample_app, setup):
    transits, author, other = setup
    item = ParentEntity.objects.create(
        name='Entity', author=author, dt_approved=datetime(2026, 1, 1, tzinfo=UTC)
    )
    client = get_api_client(sample_app, author.jwt_build())

    response = client.get(f'{URL}{item.pk}/')
    assert response.status_code == 200, response.text
    assert response.json()['data']['attributes']['status_history'] == []

    # a transit of the user (the endpoint answers with the history), then one of the system
    response = client.post(f'{URL}{item.pk}/transit/', json_data={'transit': 'activate'})
    assert response.status_code == 200, response.text
    history = response.json()['data']['attributes']['status_history']
    assert [(it['transit'], it['status'], it['author']) for it in history] == [
        ('activate', 'active', str(author.pk))
    ]
    ParentEntity.objects.get(pk=item.pk).transit_apply(transits['back'], None)

    expected = [('activate', 'active', str(author.pk)), ('back', 'draft', None)]
    for response in (client.get(f'{URL}{item.pk}/'), client.get(URL)):
        assert response.status_code == 200, response.text
        data = response.json()['data']
        history = (data if isinstance(data, dict) else data[0])['attributes']['status_history']
        assert [(it['transit'], it['status'], it['author']) for it in history] == expected
        records = item.statusy_transits.order_by('dt')
        assert [datetime.fromisoformat(it['dt']) for it in history] == [r.dt for r in records]

    schema = client.get(f'{URL}{item.pk}/schema_retrieve/').json()
    found = [
        props['status_history']
        for it in schema['$defs'].values()
        if 'status_history' in (props := it.get('properties', {}))
    ]
    assert found and all(it.get('readOnly') and it['type'] == 'array' for it in found)

    # the history of an item the user does not view is not readable
    client = get_api_client(sample_app, other.jwt_build())
    assert client.get(f'{URL}{item.pk}/').status_code == 404
    assert client.get(URL).json()['data'] == []
