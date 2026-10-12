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
The status segment of the item permissions of `add` (bazis-permit 2.11): the CREATE schema
of a `StatusyRouteSetBase` route accepts an initial `status`, and the created item is
checked against the `item.add` permissions of the user, its status literally:
`item.add.all.draft` creates only in `draft` (a create without `status` gets the initial
status), `item.add.all.all` in any status. `bazis_doctor` warns of a role that cannot
create without `status` (statusy.W005) and of one that creates in any status a route
accepts (statusy.W006).
"""

from types import SimpleNamespace

from django.core.cache import cache

import pytest
from bazis_test_utils.utils import get_api_client
from entity.models import DependentEntity, ParentEntity
from entity.routes import ParentEntityRouteSet
from translated_fields import to_attribute

from bazis.contrib.permit.declare import Group, Role
from bazis.contrib.permit.models import GroupPermission, Permission
from bazis.contrib.permit.models import Role as RoleModel
from bazis.contrib.statusy import checks, declare
from bazis.contrib.statusy.models import Status
from bazis.contrib.users import get_user_model
from bazis.core.schemas import CrudApiAction


URL = '/api/v1/entity/parent_entity/'
URL_DEPENDENT = '/api/v1/entity/dependent_entity/'
VIEW = ('entity.parent_entity.item.view.all.all', 'entity.dependent_entity.item.view.all.all')


def role_with(slug: str, *slugs: str) -> RoleModel:
    name = to_attribute('name')
    group = GroupPermission.objects.create(slug=slug, **{name: slug})
    for it in slugs:
        group.permissions.add(Permission.objects.get_or_create(slug=it)[0])
    role = RoleModel.objects.create(slug=slug, **{name: slug})
    role.groups_permission.add(group)
    return role


def client_with(sample_app, slug: str, *slugs: str):
    user = get_user_model().objects.create_user(slug, password='weak_password_8')
    user.roles.add(role_with(slug, *VIEW, *slugs))
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


def create(client, status: str | None = None):
    data = {'type': 'entity.parent_entity', 'bs:action': 'add', 'attributes': {'name': 'New'}}
    if status:
        data['relationships'] = {'status': {'data': {'type': 'statusy.status', 'id': status}}}
    return client.post(URL, json_data={'data': data})


def assert_created(response, status: str):
    assert response.status_code == 201, response.content
    assert ParentEntity.objects.get(id=response.json()['data']['id']).status_id == status


def assert_refused(response):
    assert response.status_code == 403, response.content
    assert response.json()['errors'][0]['code'] == 'ERR_FORBIDDEN'


@pytest.mark.django_db(transaction=True)
def test_add_of_the_initial_status(sample_app, statuses):
    """`item.add.all.draft`: a create without `status` (draft) is allowed, one in open not."""
    client = client_with(sample_app, 'drafter', 'entity.parent_entity.item.add.all.draft')
    assert_refused(create(client, 'open'))
    assert not ParentEntity.objects.exists()
    assert_created(create(client), 'draft')
    assert_created(create(client, 'draft'), 'draft')


@pytest.mark.django_db(transaction=True)
def test_add_of_another_status(sample_app, statuses):
    """`item.add.all.open`: only a create that sends `open`; without `status` it is draft."""
    client = client_with(sample_app, 'opener', 'entity.parent_entity.item.add.all.open')
    assert_refused(create(client))
    assert not ParentEntity.objects.exists()
    assert_created(create(client, 'open'), 'open')


@pytest.mark.django_db(transaction=True)
def test_add_of_all_statuses(sample_app, statuses):
    """`item.add.all.all`: any status, as before (the role skips the transits)."""
    client = client_with(sample_app, 'anyone', 'entity.parent_entity.item.add.all.all')
    assert_created(create(client), 'draft')
    assert_created(create(client, 'open'), 'open')


@pytest.mark.django_db(transaction=True)
def test_add_of_several_statuses(sample_app, statuses):
    """The status of the item matches one of the add permissions of the user."""
    client = client_with(
        sample_app,
        'both',
        'entity.parent_entity.item.add.all.draft',
        'entity.parent_entity.item.add.all.open',
    )
    assert_created(create(client), 'draft')
    assert_created(create(client, 'open'), 'open')


@pytest.mark.django_db(transaction=True)
def test_add_is_checked_before_an_automatic_transit(sample_app, statuses, monkeypatch):
    """
    The status of creation is checked before the effects of `hook_after_create` of the route
    (its override calls `super()` first): a status the server sets afterwards is not the
    user's.
    """

    def hook_after_create(self, item):
        super(ParentEntityRouteSet, self).hook_after_create(item)
        ParentEntity.objects.filter(pk=item.pk).update(status=statuses['open'])

    monkeypatch.setattr(ParentEntityRouteSet, 'hook_after_create', hook_after_create, raising=False)
    client = client_with(sample_app, 'drafter', 'entity.parent_entity.item.add.all.draft')
    assert_created(create(client), 'open')
    assert_refused(create(client, 'open'))
    assert ParentEntity.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_add_of_a_child_by_the_status_of_its_parent(sample_app, statuses):
    """
    A child model (`StatusyChildMixin`): the status of `add` is the one of the parent, as for
    the other operations.
    """
    client = client_with(sample_app, 'child', 'entity.dependent_entity.item.add.all.draft')
    draft = ParentEntity.objects.create(name='Draft', status=statuses['draft'])
    opened = ParentEntity.objects.create(name='Open', status=statuses['open'])

    def create_child(parent):
        return client.post(
            URL_DEPENDENT,
            json_data={
                'data': {
                    'type': 'entity.dependent_entity',
                    'bs:action': 'add',
                    'attributes': {'dependent_name': 'Child'},
                    'relationships': {
                        'parent_entity': {
                            'data': {'type': 'entity.parent_entity', 'id': str(parent.id)}
                        }
                    },
                }
            },
        )

    assert_refused(create_child(opened))
    assert not DependentEntity.objects.exists()
    response = create_child(draft)
    assert response.status_code == 201, response.content
    assert DependentEntity.objects.get().parent_entity == draft


def codes(messages) -> list[tuple[str, str]]:
    return [(it.id, it.msg.split(' ', 3)[2]) for it in messages]


def test_w005_a_role_that_names_no_initial_status(sample_app):
    """
    statusy.W005: the add permissions of a role on a model with statuses name neither its
    initial status nor `all`. Not reported: a role that names it, `all`, another model, a
    child model (its status is the parent's).
    """
    add = 'entity.parent_entity.item.add'
    messages = checks.add_status_messages({'opener': {f'{add}.all.open', f'{add}.author.closed'}}, 'roles.py')
    assert codes(messages) == [('statusy.W005', 'opener')]
    assert 'not in its initial status draft' in messages[0].msg
    assert f'{add}.all.open' in messages[0].msg
    assert 'entity.parent_entity.item.add.<selector>.draft' in messages[0].hint

    for slugs in (
        {f'{add}.all.open', f'{add}.author.draft'},
        {f'{add}.all.draft'},
        {'entity.dependent_entity.item.add.all.open'},
        {'entity.parent_entity.item.view.all.open'},
    ):
        assert checks.add_status_messages({'role': slugs}, 'roles.py') == [], slugs


def test_w005_follows_the_declared_initial_status(sample_app, monkeypatch):
    """The initial status declared by the workflow of the model (`Workflow(initial=...)`)."""
    monkeypatch.setattr(declare, 'initial_status', lambda model: 'open')
    add = 'entity.parent_entity.item.add'
    assert checks.add_status_messages({'role': {f'{add}.all.open'}}, 'roles.py') == []
    messages = checks.add_status_messages({'role': {f'{add}.all.draft'}}, 'roles.py')
    assert codes(messages) == [('statusy.W005', 'role')]
    assert 'not in its initial status open' in messages[0].msg


def test_w006_a_role_that_creates_in_any_status(sample_app, monkeypatch):
    """
    statusy.W006: `item.add.<selector>.all` while a route of the model accepts `status` on a
    create (`ParentEntityRouteSet`, not the guest route without a create). Not reported: a
    named status, a route whose create schema excludes `status`.
    """
    slug = 'entity.parent_entity.item.add.author.all'
    messages = checks.add_status_messages({'role': {slug}}, 'roles.py')
    assert [it.id for it in messages] == ['statusy.W006']
    assert messages[0].msg.startswith(f'The permission {slug} of the role role (roles.py)')
    assert 'entity.routes.ParentEntityRouteSet accepts `status`' in messages[0].msg
    assert 'Guest' not in messages[0].msg
    assert 'entity.parent_entity.field.add.all.all.status.disable' in messages[0].hint

    assert checks.add_status_messages(
        {'role': {'entity.parent_entity.item.add.all.draft'}}, 'roles.py'
    ) == []
    monkeypatch.setitem(
        ParentEntityRouteSet.schema_factories, CrudApiAction.CREATE, SimpleNamespace(fields_list=[])
    )
    assert checks.add_status_messages({'role': {slug}}, 'roles.py') == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('restriction', ['disable', 'readonly'])
def test_a_role_without_the_status_on_create(sample_app, statuses, restriction):
    """
    `field.add.all.all.status.disable` hides the status from the create schema of the role
    (a create with it is 422), `readonly` makes a create ignore it: the role creates in the
    initial status only, whatever `item.add.all.all`, and statusy.W006 does not report it.
    """
    status_field = f'entity.parent_entity.field.add.all.all.status.{restriction}'
    client = client_with(
        sample_app, restriction, 'entity.parent_entity.item.add.all.all', status_field
    )
    response = client.get(f'{URL}schema_create/')
    relationships = {
        field: schema
        for name, schema in response.json()['$defs'].items()
        if name.endswith('__Relationships')
        for field, schema in (schema.get('properties') or {}).items()
    }
    response = create(client, 'open')
    if restriction == 'disable':
        assert 'status' not in relationships
        assert response.status_code == 422, response.content
    else:
        assert relationships['status'].get('readOnly') is True
        assert_created(response, 'draft')
    assert_created(create(client), 'draft')

    slug = 'entity.parent_entity.item.add.all.all'
    assert checks.add_status_messages({'role': {slug, status_field}}, 'roles.py') == []
    # enabled again by its own permission: reported
    assert [it.id for it in checks.add_status_messages(
        {'role': {slug, 'entity.parent_entity.field.add.all.all.__all__.disable',
                  'entity.parent_entity.field.add.all.all.status.enable'}}, 'roles.py'
    )] == ['statusy.W006']
    # hidden with every field
    assert checks.add_status_messages(
        {'role': {slug, 'entity.parent_entity.field.add.all.all.__all__.readonly'}}, 'roles.py'
    ) == []
    # a field permission of another model, of change or with a condition: reported
    for other in (
        'entity.dependent_entity.field.add.all.all.status.disable',
        'entity.parent_entity.field.change.all.all.status.disable',
        'entity.parent_entity.field.add.author.all.status.disable',
    ):
        assert [it.id for it in checks.add_status_messages({'role': {slug, other}}, 'roles.py')] == [
            'statusy.W006'
        ], other


def test_the_declared_roles(sample_app, monkeypatch):
    """The checks of the roles of `roles.py` (the sample declares none)."""
    from bazis.contrib.permit import declare as permit_declare

    assert checks.check_add_statuses(None) == []
    groups = [Group('openers', 'Openers', ['entity.parent_entity.item.add.all.open'])]
    monkeypatch.setattr(
        permit_declare,
        'declarations',
        lambda: ([('roles', groups[0])], [('roles', Role('opener', 'Opener', groups))]),
    )
    messages = checks.check_add_statuses(None)
    assert codes(messages) == [('statusy.W005', 'opener')]
    assert '(roles.py)' in messages[0].msg


@pytest.mark.django_db
def test_the_roles_of_the_database(sample_app, monkeypatch):
    """
    The roles of the database that are not declared (the admin, the API), with the
    permissions of their groups; a declared role is checked by its declaration.
    """
    from bazis.contrib.permit import declare as permit_declare

    assert checks.check_add_statuses_applied(None, databases=['default']) == []
    role_with('opener', 'entity.parent_entity.item.add.all.open')
    role_with('drafter', 'entity.parent_entity.item.add.all.draft')
    messages = checks.check_add_statuses_applied(None, databases=['default'])
    assert codes(messages) == [('statusy.W005', 'opener')]
    assert '(the database)' in messages[0].msg

    # the permissions the declaration of the role gives are reported by check_add_statuses
    openers = Group('openers', 'Openers', ['entity.parent_entity.item.add.all.open'])
    monkeypatch.setattr(
        permit_declare,
        'declarations',
        lambda: ([('roles', openers)], [('roles', Role('opener', 'Opener', [openers]))]),
    )
    assert checks.check_add_statuses_applied(None, databases=['default']) == []
    # a permission the admin attached to a declared role is the database's
    role_with('opener_extra', 'entity.parent_entity.item.add.author.all')
    RoleModel.objects.get(slug='opener').groups_permission.add(
        GroupPermission.objects.get(slug='opener_extra')
    )
    messages = checks.check_add_statuses_applied(None, databases=['default'])
    assert [(it.id, it.msg.split()[6]) for it in messages] == [
        ('statusy.W006', 'opener'),
        ('statusy.W006', 'opener_extra'),
    ]


@pytest.mark.django_db(transaction=True)
def test_add_of_a_status_that_does_not_exist(sample_app, statuses):
    """
    A status that does not exist is 422 at its identifier (bazis 2.16: the statuses are a
    catalog whose route restricts nothing, so the core looks the related object up); it was
    an integrity error at the commit, a 500.
    """
    client = client_with(sample_app, 'anyone', 'entity.parent_entity.item.add.all.all')
    response = create(client, 'nowhere')
    assert response.status_code == 422, response.content
    assert [(it['code'], it['source']) for it in response.json()['errors']] == [
        ('ERR_VALIDATE', {'pointer': '/data/relationships/status/data/id'})
    ]
    assert not ParentEntity.objects.exists()
