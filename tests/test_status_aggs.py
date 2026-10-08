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
from bazis_test_utils.utils import get_api_client
from translated_fields import to_attribute

from bazis.contrib.permit.models import GroupPermission, Permission, Role
from bazis.contrib.statusy.models import Status
from bazis.contrib.users import get_user_model
from bazis.core.routes_abstract.jsonapi import JsonapiRouteBase

from .factories import ChildEntityFactory, ParentEntityFactory


User = get_user_model()

URL = '/api/v1/entity/parent_entity/'


@pytest.mark.skipif(
    not hasattr(JsonapiRouteBase, 'query_scope'),
    reason='the filter and the search reach only what the route shows since Bazis 2.9',
)
@pytest.mark.django_db(transaction=True)
def test_status_aggs_reach_only_what_the_route_shows(sample_app):
    """
    `status_aggs` counts the objects with the filter and the search of the request as the
    list does: a filter through a relation reaches only the related objects the user can
    see, `$search` only the search fields of the route, a field out of the route is 400.
    """
    name_attr = to_attribute('name')
    group = GroupPermission.objects.create(slug='aggs', **{name_attr: 'aggs'})
    # the user sees every parent entity and no child entity
    group.permissions.add(Permission.objects.create(slug='entity.parent_entity.item.view.all.all'))
    role = Role.objects.create(slug='aggs', **{name_attr: 'aggs'})
    role.groups_permission.add(group)

    user = User.objects.create_user('aggs_user', email='aggs_user@site.com', password='weak_1')
    user.roles.add(role)

    status = Status.get_status_initial()
    ParentEntityFactory(name='parent one', description='plain').child_entities.add(
        ChildEntityFactory(child_name='hidden')
    )
    ParentEntityFactory(name='parent two', description='plain')
    ParentEntityFactory(name='parent three', description='needle')

    def get(filter_str):
        return get_api_client(sample_app, user.jwt_build()).get(
            URL, params={'filter': filter_str, 'meta': 'status_aggs'}
        )

    # a relation into the objects the user cannot see
    response = get('child_entities__child_name=hidden')
    assert response.status_code == 200
    assert response.json()['data'] == []
    assert response.json()['meta']['status_aggs'] == {}

    # the search of the filter searches the search fields of the route (`name`)
    response = get('$search=three')
    assert response.status_code == 200
    assert len(response.json()['data']) == 1
    assert response.json()['meta']['status_aggs'] == {status.id: 1}

    response = get('$search=needle')
    assert response.status_code == 200
    assert response.json()['data'] == []
    assert response.json()['meta']['status_aggs'] == {}

    # the status is left out of the counts, the other keys are kept
    response = get('status=other&name=parent two')
    assert response.status_code == 200
    assert response.json()['data'] == []
    assert response.json()['meta']['status_aggs'] == {status.id: 1}

    # a field out of the LIST schema of the route, a field of a related model without a route
    for filter_str in ('statusy_transits__transit=to_check', 'author__username=aggs_user'):
        response = get(filter_str)
        assert response.status_code == 400
        assert response.json()['errors'][0]['code'] == 'ERR_FILTER'
