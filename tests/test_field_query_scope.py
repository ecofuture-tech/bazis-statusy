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
The field permissions limited to a status (`field.view.<selector>.<status>.<field>`): the
filter, the sorting and the search of a request reach a field only if the permissions show
it in every status (`PermitRouteBase.query_fields` of bazis-permit 2.11), also when the
objects of the other statuses are hidden from the user.
"""

from django.core.cache import cache

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import ParentEntity
from translated_fields import to_attribute

from bazis.contrib.permit.models import GroupPermission, Permission, Role
from bazis.contrib.statusy.models import Status
from bazis.contrib.users import get_user_model


URL = '/api/v1/entity/parent_entity/'


def role_with(slug: str, *slugs: str, **kwargs) -> Role:
    name = to_attribute('name')
    group = GroupPermission.objects.create(slug=slug, **{name: slug})
    for it in slugs:
        group.permissions.add(Permission.objects.get_or_create(slug=it)[0])
    role = Role.objects.create(slug=slug, **{name: slug}, **kwargs)
    role.groups_permission.add(group)
    return role


def ids(response) -> list[str]:
    assert response.status_code == 200, response.content
    return sorted(it['id'] for it in response.json()['data'])


def assert_invalid(response, pointer: str):
    assert response.status_code == 400, response.content
    error = response.json()['errors'][0]
    assert (error['code'], error['source']['pointer']) == ('ERR_FILTER', pointer)


@pytest.fixture
def entities(db):
    name = to_attribute('name')
    cache.delete_pattern('bazis:throttle:*')
    open_ = Status.objects.get_or_create(id='open', defaults={name: 'Open'})[0]
    draft = Status.objects.get_or_create(id='draft', defaults={name: 'Draft'})[0]
    return (
        ParentEntity.objects.create(name='High', status=open_, price=900),
        ParentEntity.objects.create(name='Low', status=open_, price=100),
        ParentEntity.objects.create(name='Draft', status=draft, price=5),
    )


@pytest.mark.django_db(transaction=True)
def test_anonymous_field_hidden_in_the_status_he_sees(sample_app, entities):
    """
    A role for anonymous users sees the open objects without their price; the drafts, which
    no field permission matches, are hidden from it. The price of an open object cannot be
    found by trial with a filter or a sorting.
    """
    high, low, __ = entities
    role_with(
        'career',
        'entity.parent_entity.item.view.all.open',
        'entity.parent_entity.field.view.all.open.__all__.disable',
        'entity.parent_entity.field.view.all.open.name.enable',
        for_anonymous=True,
    )
    client = get_api_client(sample_app)

    assert ids(client.get(URL)) == sorted([str(high.id), str(low.id)])
    assert set(client.get(f'{URL}{high.id}/').json()['data']['attributes']) == {'name'}

    for key in ('price__gte=500', 'price=900', 'price__lt=300'):
        assert_invalid(client.get(URL, params={'filter': key}), '/query/filter')
    assert_invalid(client.get(URL, params={'sort': '-price'}), '/query/sort')
    assert ids(client.get(URL, params={'filter': 'name=High'})) == [str(high.id)]


@pytest.mark.django_db(transaction=True)
def test_field_hidden_in_one_status(sample_app, entities):
    """
    A field hidden only in the objects of one status is reachable in none of them, a field
    shown in every status is.
    """
    high, low, draft = entities
    role = role_with(
        'reader',
        'entity.parent_entity.item.view.all.all',
        'entity.parent_entity.field.view.all.draft.price.disable',
    )
    user = get_user_model().objects.create_user('reader', password='weak_password_5')
    user.roles.add(role)
    user.refresh_from_db()
    client = get_api_client(sample_app, user.jwt_build())

    assert 'price' not in client.get(f'{URL}{draft.id}/').json()['data']['attributes']
    assert client.get(f'{URL}{high.id}/').json()['data']['attributes']['price'] == '900.00'
    assert_invalid(client.get(URL, params={'filter': 'price__lt=10'}), '/query/filter')
    assert_invalid(client.get(URL, params={'sort': 'price'}), '/query/sort')
    assert ids(client.get(URL, params={'filter': 'name=Draft'})) == [str(draft.id)]
