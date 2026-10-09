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
The permissions of the models of `StatusyChildMixin` (their status is the status of the
parent): their lists, their objects in `included` and the filters through a relation into
them show only the objects the permissions allow; a transit of the parent validates the
children with their transit schema and needs no permission of theirs.
"""

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import ParentEntity
from translated_fields import to_attribute

from bazis.contrib.permit.models import GroupPermission, Permission, Role
from bazis.contrib.statusy.models import Status, StatusyContentType, Transit
from bazis.contrib.users import get_user_model
from bazis.core.routes_abstract.jsonapi import JsonapiRouteBase

from .factories import ChildEntityFactory, DependentEntityFactory, ParentEntityFactory


User = get_user_model()

URL_PARENT = '/api/v1/entity/parent_entity/'
URL_CHILD = '/api/v1/entity/child_entity/'


def user_with(name: str, *slugs: str) -> User:
    name_attr = to_attribute('name')
    group = GroupPermission.objects.create(slug=name, **{name_attr: name})
    for slug in slugs:
        group.permissions.add(Permission.objects.get_or_create(slug=slug)[0])
    role = Role.objects.create(slug=name, **{name_attr: name})
    role.groups_permission.add(group)
    user = User.objects.create_user(name, email=f'{name}@site.com', password='weak_password')
    user.roles.add(role)
    return user


def ids(response) -> list[str]:
    assert response.status_code == 200, response.content
    return sorted(it['id'] for it in response.json()['data'])


@pytest.fixture
def entities():
    """
    A user who sees every parent entity and his own child entities (the selector `author`),
    and a parent entity with his child entity and the child entity of another user.
    """
    user = user_with(
        'child_viewer',
        'entity.parent_entity.item.view.all.all',
        'entity.child_entity.item.view.author.all',
    )
    stranger = User.objects.create_user('stranger', email='stranger@site.com', password='weak_2')
    parent = ParentEntityFactory(name='parent')
    own = ChildEntityFactory(child_name='own', author=user)
    other = ChildEntityFactory(child_name='other', author=stranger)
    parent.child_entities.add(own, other)
    return user, parent, own, other


@pytest.mark.django_db(transaction=True)
def test_child_list(sample_app, entities):
    user, parent, own, other = entities
    client = get_api_client(sample_app, user.jwt_build())

    assert ids(client.get(URL_CHILD)) == [str(own.id)]
    assert client.get(f'{URL_CHILD}{own.id}/').status_code == 200
    assert client.get(f'{URL_CHILD}{other.id}/').status_code in (403, 404)


@pytest.mark.django_db(transaction=True)
def test_child_list_without_permission(sample_app, entities):
    user = user_with('parent_viewer', 'entity.parent_entity.item.view.all.all')
    assert get_api_client(sample_app, user.jwt_build()).get(URL_CHILD).status_code == 403


@pytest.mark.django_db(transaction=True)
def test_parent_with_included_children(sample_app, entities):
    user, parent, own, other = entities
    response = get_api_client(sample_app, user.jwt_build()).get(
        f'{URL_PARENT}{parent.id}/', params={'include': 'child_entities'}
    )
    assert response.status_code == 200, response.content
    assert [it['id'] for it in response.json()['included']] == [str(own.id)]


@pytest.mark.skipif(
    not hasattr(JsonapiRouteBase, 'query_scope'),
    reason='a filter through a relation reaches only the visible objects since Bazis 2.9',
)
@pytest.mark.django_db(transaction=True)
def test_filter_through_relation_into_children(sample_app, entities):
    user, parent, own, other = entities
    status = Status.get_status_initial()
    client = get_api_client(sample_app, user.jwt_build())

    def get(filter_str):
        return client.get(URL_PARENT, params={'filter': filter_str, 'meta': 'status_aggs'})

    response = get('child_entities__child_name=own')
    assert ids(response) == [str(parent.id)]
    assert response.json()['meta']['status_aggs'] == {status.id: 1}

    # the child entity of another user
    response = get('child_entities__child_name=other')
    assert ids(response) == []
    assert response.json()['meta']['status_aggs'] == {}


@pytest.fixture
def to_check():
    """The transit `to_check` of the parent entities from their initial status."""
    name_attr = to_attribute('name')
    StatusyContentType.objects.clear_cache()
    return Transit.objects.create(
        id='to_check',
        model=StatusyContentType.objects.get_for_model(ParentEntity),
        status_src=Status.get_status_initial(),
        status_dst=Status.objects.get_or_create(id='check', defaults={name_attr: 'Check'})[0],
        **{name_attr: 'To check'},
    )


#: the parent entities and their children: viewed, the parent changed and transited
TRANSITING = (
    'entity.parent_entity.item.view.all.all',
    'entity.parent_entity.item.change.all.all',
    'entity.parent_entity.item.transit.all.all.to_check',
    'entity.child_entity.item.view.all.all',
    'entity.dependent_entity.item.view.all.all',
    'entity.extended_entity.item.view.all.all',
)


@pytest.mark.django_db(transaction=True)
def test_transit_of_a_parent_needs_no_permission_of_the_children(sample_app, to_check):
    """
    The children of the transited item (a foreign key, a one-to-one and a many-to-many to
    it) are validated with their transit schema: the user transits the parent, he has no
    `transit` permission of the children.
    """
    user = user_with('transiting', *TRANSITING)
    parent = ParentEntityFactory(child_entities=True)
    assert parent.dependent_entities.exists() and parent.child_entities.exists()

    response = get_api_client(sample_app, user.jwt_build()).post(
        f'{URL_PARENT}{parent.id}/transit/', json_data={'transit': to_check.id}
    )
    assert response.status_code == 200, response.text
    assert response.json()['data']['relationships']['status']['data']['id'] == 'check'


PRICED = 'entity.dependent_entity.field.transit.all.all.dependent_price.notnull'


@pytest.mark.django_db(transaction=True)
def test_transit_validates_the_children(sample_app, to_check):
    """
    The field permissions of the user for the transits of a child model apply to its
    objects: a child that does not satisfy them stops the transit (422 with the error of
    its field), nothing changes.
    """
    user = user_with('transiting_priced', *TRANSITING, PRICED)
    parent = ParentEntityFactory()
    child = DependentEntityFactory(parent_entity=parent, dependent_price=None)
    status = parent.status_id

    response = get_api_client(sample_app, user.jwt_build()).post(
        f'{URL_PARENT}{parent.id}/transit/', json_data={'transit': to_check.id}
    )
    assert response.status_code == 422, response.text
    [error] = response.json()['errors']
    assert error['source'] == {
        'pointer': '/data/attributes/dependent_price',
        'id': str(child.id),
        'type': 'entity.dependent_entity',
    }
    parent.refresh_from_db()
    assert parent.status_id == status


@pytest.mark.django_db(transaction=True)
def test_invalid_children_the_user_does_not_view(sample_app, to_check):
    """
    A child the user does not view is validated too, but its errors do not disclose it:
    one error without the child and its fields. Those of the children he views come first.
    """
    viewing_no_dependent = [it for it in TRANSITING if not it.startswith('entity.dependent_')]
    user = user_with('transiting_blind', *viewing_no_dependent, PRICED)
    parent = ParentEntityFactory()
    hidden = DependentEntityFactory(parent_entity=parent, dependent_price=None)
    status = parent.status_id
    client = get_api_client(sample_app, user.jwt_build())
    assert client.get(f'/api/v1/entity/dependent_entity/{hidden.id}/').status_code in (403, 404)

    response = client.post(f'{URL_PARENT}{parent.id}/transit/', json_data={'transit': to_check.id})
    assert response.status_code == 422, response.text
    assert response.json()['errors'] == [
        {
            'status': 422,
            'title': 'Transition error',
            'code': 'ERR_TRANSIT_CHILDREN_INVALID',
            'detail': 'Some related items are not valid for this transit',
        }
    ]
    assert str(hidden.id) not in response.text and 'dependent' not in response.text
    parent.refresh_from_db()
    assert parent.status_id == status

    # a child he views that is invalid too: its own errors, not the hidden ones
    child_priced = 'entity.child_entity.field.transit.all.all.child_price.notnull'
    user.roles.first().groups_permission.first().permissions.add(
        Permission.objects.get_or_create(slug=child_priced)[0]
    )
    visible = ChildEntityFactory(child_price=None)
    parent.child_entities.add(visible)
    response = client.post(f'{URL_PARENT}{parent.id}/transit/', json_data={'transit': to_check.id})
    assert response.status_code == 422, response.text
    assert [it['source']['id'] for it in response.json()['errors']] == [str(visible.id)]
    assert str(hidden.id) not in response.text
    visible.delete()

    # valid, the transit is made
    hidden.dependent_price = 1
    hidden.save()
    response = client.post(f'{URL_PARENT}{parent.id}/transit/', json_data={'transit': to_check.id})
    assert response.status_code == 200, response.text
