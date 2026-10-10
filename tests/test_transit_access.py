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
The transit is an action of bazis-permit: closed to anonymous users (403) even with a
transit permission of the roles for anonymous users, unless a route overrides it with
`public=True` (sample `ParentEntityGuestRouteSet`); `schema_transit` is a schema route.
"""

from django.core.cache import cache

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import ParentEntity
from translated_fields import to_attribute

from bazis.contrib.permit.models import GroupPermission, Permission, Role
from bazis.contrib.statusy.models import Status, StatusyContentType, Transit
from bazis.core.routes_abstract.initial import OPENAPI_EXTENSION


@pytest.fixture
def guest_transit(db):
    """A parent entity in `draft`, the transit `to_check`, a role for anonymous users with it."""
    name = to_attribute('name')
    cache.delete_pattern('bazis:throttle:*')
    StatusyContentType.objects.clear_cache()
    draft = Status.objects.get_or_create(id='draft', defaults={name: 'Draft'})[0]
    check = Status.objects.get_or_create(id='check', defaults={name: 'Check'})[0]
    Transit.objects.get_or_create(
        id='to_check',
        defaults={
            name: 'To check',
            'model': StatusyContentType.objects.get_for_model(ParentEntity),
            'status_src': draft,
            'status_dst': check,
        },
    )
    group = GroupPermission.objects.create(slug='guest', **{name: 'Guest'})
    for slug in (
        'entity.parent_entity.item.view.all.all',
        'entity.parent_entity.item.transit.all.all.to_check',
    ):
        group.permissions.add(Permission.objects.get_or_create(slug=slug)[0])
    role = Role.objects.create(slug='guest', for_anonymous=True, **{name: 'Guest'})
    role.groups_permission.add(group)
    item = ParentEntity.objects.create(name='Request', status=draft)
    yield item
    cache.delete_pattern('bazis:throttle:*')


@pytest.mark.django_db(transaction=True)
def test_anonymous_transit(sample_app, guest_transit):
    client = get_api_client(sample_app)
    response = client.post(
        f'/api/v1/entity/parent_entity/{guest_transit.pk}/transit/', json_data={'transit': 'to_check'}
    )
    assert response.status_code == 403, response.content
    assert ParentEntity.objects.get(pk=guest_transit.pk).status_id == 'draft'

    response = client.post(
        f'/api/v1/entity/parent_entity_guest/{guest_transit.pk}/transit/',
        json_data={'transit': 'to_check'},
    )
    assert response.status_code == 200, response.content
    assert ParentEntity.objects.get(pk=guest_transit.pk).status_id == 'check'

    # the public transit still requires the transit permission of the role
    response = client.post(
        f'/api/v1/entity/parent_entity_guest/{guest_transit.pk}/transit/',
        json_data={'transit': 'to_check'},
    )
    assert response.status_code == 403


def test_openapi(sample_app):
    paths = sample_app.openapi()['paths']
    schema = paths['/api/v1/entity/parent_entity/{item_id}/schema_transit/']['get'][OPENAPI_EXTENSION]
    assert schema['kind'] == 'schema'
    transit = paths['/api/v1/entity/parent_entity/{item_id}/transit/']['post'][OPENAPI_EXTENSION]
    assert transit['kind'] == 'other' and 'public' not in transit
    guest = paths['/api/v1/entity/parent_entity_guest/{item_id}/transit/']['post'][OPENAPI_EXTENSION]
    assert guest['public'] is True
