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

from uuid import uuid4

from django.apps import apps

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import ParentEntity
from translated_fields import to_attribute

from bazis.contrib.permit.models import GroupPermission, Permission, Role
from bazis.contrib.statusy.models import Status, StatusyContentType, Transit
from bazis.contrib.users import get_user_model


User = get_user_model()


GROUPS = {
    'parent_entity': [
        # everyone is able to add records
        'entity.parent_entity.item.add.all.all',
        # everyone is able to view any records
        'entity.parent_entity.item.view.all.all',
        # only the author can modify a record
        'entity.parent_entity.item.change.author.all',
        # the author can move a record to another status
        'entity.parent_entity.item.transit.author.all.to_check',
        # the author can move a record to another status
        'entity.parent_entity.item.transit.author.all.to_active',
    ],
    'child_entity': [
        # everyone is able to add records
        'entity.child_entity.item.add.all.all',
        # everyone is able to view any records
        'entity.child_entity.item.view.all.all',
        # only the author can modify a record
        'entity.child_entity.item.change.author.all',
        # the parent’s author can also modify a record
        'entity.child_entity.item.change.author_parent.all',
        # only the author can delete a record
        'entity.child_entity.item.delete.author.all',
    ],
}


@pytest.mark.django_db(transaction=True)
def test_transit(sample_app):
    name_attr = to_attribute('name')

    # create roles and groups
    groups = {}
    for group_name, permissions in GROUPS.items():
        group = GroupPermission.objects.create(
            slug=group_name,
            **{name_attr: group_name}
        )
        for it in permissions:
            group.permissions.add(Permission.objects.create(slug=it))
        groups[group_name] = group

    def role_create(name: str, groups_names: list[str]):
        role = Role.objects.create(slug=name, **{name_attr: name})
        for group_name in groups_names:
            role.groups_permission.add(groups[group_name])
        return role

    user_1 = User.objects.create_user('user1', email='user1@site.com', password='weak_password_1')
    user_2 = User.objects.create_user('user2', email='user2@site.com', password='weak_password_2')

    # assign role_user1 to user_1,
    # which has access to the parent_entity and child_entity groups
    user_1.roles.add(role_create('role_user1', ['parent_entity', 'child_entity']))
    user_2.roles.add(role_create('role_user2', ['parent_entity', 'child_entity']))

    apps.get_model('statusy.Status').get_status_initial()
    StatusyContentType.objects.clear_cache()
    status_draft = Status.objects.get_or_create(id='draft', defaults={name_attr: 'Draft'})[0]
    status_check = Status.objects.get_or_create(id='check', defaults={name_attr: 'Check'})[0]
    status_active = Status.objects.get_or_create(id='active', defaults={name_attr: 'Active'})[0]

    transit_to_check = Transit.objects.get_or_create(
        id='to_check',
        defaults={
            name_attr: 'To check',
            'model': StatusyContentType.objects.get_for_model(ParentEntity),
            'status_src': status_draft,
            'status_dst': status_check,
        },
    )[0]

    transit_to_active = Transit.objects.get_or_create(
        id='to_active',
        defaults={
            name_attr: 'To active',
            'model': StatusyContentType.objects.get_for_model(ParentEntity),
            'status_src': status_check,
            'status_dst': status_active,
            'validators': ['validator_must_active'],
            'actions_before': ['before_dt_approved'],
            'actions_after': ['after_child_entities'],
        },
    )[0]

    parent_entity_id = str(uuid4())

    # user_1 creates a record
    response = get_api_client(sample_app, user_1.jwt_build()).post(
        '/api/v1/entity/parent_entity/',
        json_data={
            'data': {
                'id': parent_entity_id,
                'type': 'entity.parent_entity',
                'bs:action': 'add',
                'attributes': {
                    'name': 'Test name',
                    'description': 'Test description',
                    'is_active': False,
                    'price': '100.49',
                },
                'included': [
                    {
                        'type': 'entity.child_entity',
                        'bs:action': 'add',
                        'attributes': {
                            'child_name': 'Child test name 1',
                            'child_description': 'Child test description 1',
                            'child_is_active': True,
                            'child_price': '421.74',
                            'child_dt_approved': '2024-01-09T03:51:12Z',
                        },
                        'relationships': {
                            'parent_entities': {
                                'data': [
                                    {
                                        'id': parent_entity_id,
                                        'type': 'entity.parent_entity',
                                    }
                                ],
                            },
                        },
                    },
                    {
                        'type': 'entity.child_entity',
                        'bs:action': 'add',
                        'attributes': {
                            'child_name': 'Child test name 2',
                            'child_description': 'Child test description 2',
                            'child_is_active': False,
                            'child_price': '25.19',
                            'child_dt_approved': '2024-01-13T16:54:12Z',
                        },
                        'relationships': {
                            'parent_entities': {
                                'data': [
                                    {
                                        'id': parent_entity_id,
                                        'type': 'entity.parent_entity',
                                    }
                                ],
                            },
                        },
                    },
                ],
            },
        },
    )
    assert response.status_code == 201

    # simple status change
    response = get_api_client(sample_app, user_1.jwt_build()).post(
        f'/api/v1/entity/parent_entity/{parent_entity_id}/transit/',
        json_data={
            'transit': transit_to_check.id,
        },
    )
    assert response.status_code == 200

    assert response.json()['data']['relationships']['status']['data']['id'] == status_check.id

    # the transition cannot be performed again because the source status has already changed
    response = get_api_client(sample_app, user_1.jwt_build()).post(
        f'/api/v1/entity/parent_entity/{parent_entity_id}/transit/',
        json_data={
            'transit': transit_to_check.id,
        },
    )
    assert response.status_code == 403

    # the correct transition is not available because the payload is not specified
    response = get_api_client(sample_app, user_1.jwt_build()).post(
        f'/api/v1/entity/parent_entity/{parent_entity_id}/transit/',
        json_data={
            'transit': transit_to_active.id,
        },
    )
    assert response.status_code == 400

    # the correct transition is not available because validation for is_active == True fails
    response = get_api_client(sample_app, user_1.jwt_build()).post(
        f'/api/v1/entity/parent_entity/{parent_entity_id}/transit/',
        json_data={
            'transit': transit_to_active.id,
            'payload': {
                'must_active': True,
                'dt_approved': '2024-03-12T16:54:12Z',
            },
        },
    )
    assert response.status_code == 422
    assert response.json()['errors'][0] == {
        'status': 422,
        'title': 'Transition error',
        'code': 'ERR_TRANSIT',
        'detail': 'This entity must be active',
    }

    response = get_api_client(sample_app, user_1.jwt_build()).patch(
        f'/api/v1/entity/parent_entity/{parent_entity_id}/',
        json_data={
            'data': {
                'id': parent_entity_id,
                'type': 'entity.parent_entity',
                'bs:action': 'change',
                'attributes': {
                    'is_active': True,
                },
            },
        },
    )
    assert response.status_code == 200

    # the correct transition is not available because validation for is_active == True fails
    response = get_api_client(sample_app, user_1.jwt_build()).post(
        f'/api/v1/entity/parent_entity/{parent_entity_id}/transit/',
        json_data={
            'transit': transit_to_active.id,
            'payload': {
                'must_active': True,
                'dt_approved': '2024-03-12T16:54:12Z',
            },
        },
    )
    assert response.status_code == 200

    parent_entity = (
        ParentEntity.objects.select_related('status').filter(pk=parent_entity_id).first()
    )
    assert parent_entity.is_active is True
    assert parent_entity.dt_approved.strftime('%Y-%m-%dT%H:%M:%SZ') == '2024-03-12T16:54:12Z'
    assert parent_entity.status == status_active
    assert all(
        child_entity.child_dt_approved.strftime('%Y-%m-%dT%H:%M:%SZ') == '2024-03-12T16:54:12Z'
        for child_entity in parent_entity.child_entities.all()
    )
    assert all(
        child_entity.child_is_active is True for child_entity in parent_entity.child_entities.all()
    )
