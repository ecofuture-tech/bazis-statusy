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
The status segment of the field permissions of `add` (bazis-permit 2.11): the create schema
is built before the object exists, and the CREATE schema accepts an initial `status`, so the
status of a new object is not known. `field.add.all.all.<field>` applies to every create;
`field.add.<selector>.<status>.<field>` with a status (the initial one too) or a selector
other than `all` never applies: `roles.py` refuses it (permit.E006; a warning for `enable`),
`bazis_doctor` reports one of the database (permit.W010). The field permissions of `change`
and `view` keep their status; the item permissions of `add` restrict the status a role
creates in (`test_add_status.py`).
"""

from django.core.cache import cache

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import ParentEntity
from translated_fields import to_attribute

from bazis.contrib.permit.declare import Group, declaration_messages
from bazis.contrib.permit.models import GroupPermission, Permission, Role
from bazis.contrib.statusy.models import Status
from bazis.contrib.users import get_user_model


URL = '/api/v1/entity/parent_entity/'
ITEM = (
    'entity.parent_entity.item.add.all.draft',
    'entity.parent_entity.item.view.all.all',
    'entity.parent_entity.item.change.all.all',
)


def client_with(sample_app, slug: str, *slugs: str):
    name = to_attribute('name')
    group = GroupPermission.objects.create(slug=slug, **{name: slug})
    for it in (*ITEM, *slugs):
        group.permissions.add(Permission.objects.get_or_create(slug=it)[0])
    role = Role.objects.create(slug=slug, **{name: slug})
    role.groups_permission.add(group)
    user = get_user_model().objects.create_user(slug, password='weak_password_8')
    user.roles.add(role)
    user.refresh_from_db()
    return get_api_client(sample_app, user.jwt_build())


@pytest.fixture
def statuses(db):
    name = to_attribute('name')
    cache.delete_pattern('bazis:throttle:*')
    return {
        it: Status.objects.get_or_create(id=it, defaults={name: it.title()})[0]
        for it in ('draft', 'open')
    }


def create_attributes(client) -> set[str]:
    response = client.get(f'{URL}schema_create/')
    assert response.status_code == 200, response.content
    return {
        field
        for name, schema in response.json()['$defs'].items()
        if name.endswith('__Attributes')
        for field in schema.get('properties') or ()
    }


def create(client, status: str | None = None, **attributes):
    data = {'type': 'entity.parent_entity', 'bs:action': 'add', 'attributes': {'name': 'New', **attributes}}
    if status:
        data['relationships'] = {'status': {'data': {'type': 'statusy.status', 'id': status}}}
    return client.post(URL, json_data={'data': data})


@pytest.mark.parametrize(
    ('slug', 'fixed'),
    [
        # the initial status (BAZIS_STATUS_INITIAL) and another one
        (
            'entity.parent_entity.field.add.all.draft.price.disable',
            'entity.parent_entity.field.add.all.all.price.disable',
        ),
        (
            'entity.parent_entity.field.add.all.open.price.readonly',
            'entity.parent_entity.field.add.all.all.price.readonly',
        ),
        (
            'entity.parent_entity.field.add.author.all.__all__.disable',
            'entity.parent_entity.field.add.all.all.__all__.disable',
        ),
    ],
)
def test_add_field_permission_with_a_status_is_refused(slug, fixed):
    messages = [
        it
        for it in declaration_messages([('app.roles', Group('decl', 'Decl', [slug]))], [])
        if it.is_serious()
    ]
    assert [it.id for it in messages] == ['permit.E006']
    assert messages[0].hint == f'Write {fixed}: it restricts the field on every create of the role.'


def test_add_field_permission_with_a_status_that_shows_is_a_warning():
    """`enable` with a status never applies either: the create stays stricter (a warning)."""
    slug = 'entity.parent_entity.field.add.author.draft.price.enable'
    messages = declaration_messages([('app.roles', Group('decl', 'Decl', [slug]))], [])
    assert [(it.id, it.is_serious()) for it in messages] == [('permit.E006', False)]
    assert messages[0].hint.startswith(
        'Remove it, or write entity.parent_entity.field.add.all.all.price.enable only if'
    )


@pytest.mark.parametrize(
    'slug',
    [
        'entity.parent_entity.field.add.all.all.price.disable',
        'entity.parent_entity.field.change.all.draft.price.readonly',
        'entity.parent_entity.field.view.author.draft.price.disable',
        'entity.parent_entity.item.add.all.draft',
    ],
)
def test_other_permissions_by_status_are_valid(slug):
    assert declaration_messages([('app.roles', Group('decl', 'Decl', [slug]))], []) == []


@pytest.mark.django_db(transaction=True)
def test_add_field_permission_of_all_statuses_hides_the_field(sample_app, statuses):
    """`field.add.all.all.price.disable`: no create writes the price, whatever its status."""
    client = client_with(sample_app, 'adder', 'entity.parent_entity.field.add.all.all.price.disable')
    assert 'price' not in create_attributes(client)
    for status in (None, 'open'):
        response = create(client, status, price='5.00')
        assert response.status_code == 422, response.content
        assert response.json()['errors'][0]['source']['pointer'] == '/data/attributes/price'
    response = create(client)
    assert response.status_code == 201, response.content
    assert ParentEntity.objects.get(id=response.json()['data']['id']).price is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('status', ['draft', 'open'])
def test_add_field_permission_of_a_status_never_applies(sample_app, statuses, status):
    """
    With a status, the initial one (`draft`) or another, the field permission of add never
    applies (the status of a new object is not known): the price is written.
    """
    client = client_with(
        sample_app, f'adder_{status}', f'entity.parent_entity.field.add.all.{status}.price.disable'
    )
    assert 'price' in create_attributes(client)
    response = create(client, price='5.00')
    assert response.status_code == 201, response.content
    assert ParentEntity.objects.get(id=response.json()['data']['id']).price == 5


@pytest.mark.django_db(transaction=True)
def test_change_and_view_field_permissions_keep_their_status(sample_app, statuses):
    """`readonly` on change and `disable` on view of `draft` apply to the drafts only."""
    client = client_with(
        sample_app,
        'editor',
        'entity.parent_entity.field.change.all.draft.price.readonly',
        'entity.parent_entity.field.view.all.draft.description.disable',
    )
    for status, kept in (('draft', True), ('open', False)):
        item = ParentEntity.objects.create(name=status, price=1, description='Notes', status=statuses[status])
        url = f'{URL}{item.id}/'
        assert ('description' in client.get(url).json()['data']['attributes']) is not kept
        response = client.patch(
            url,
            json_data={
                'data': {
                    'id': str(item.id),
                    'type': 'entity.parent_entity',
                    'bs:action': 'change',
                    'attributes': {'price': '7.00'},
                }
            },
        )
        assert response.status_code == 200, response.content
        item.refresh_from_db()
        assert item.price == (1 if kept else 7)
