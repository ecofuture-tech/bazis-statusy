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
A transit made in code (`get_transit`, `transit_apply`): the statements of the guide
(bazis/contrib/statusy/AGENTS.md) about its author, its history, the permissions and a
transit in a write of a route.
"""

from datetime import UTC, datetime

import pytest
from entity.models import ParentEntity
from translated_fields import to_attribute

from bazis.contrib.statusy.models import Status, StatusyContentType, Transit
from bazis.contrib.users import get_user_model
from bazis.core.item_validation import defer_validate_item


APPROVED = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def calls():
    ParentEntity.validate_calls.clear()
    yield ParentEntity.validate_calls
    ParentEntity.validate_calls.clear()


@pytest.fixture
def transits(db):
    name_attr = to_attribute('name')
    Status.get_status_initial()
    StatusyContentType.objects.clear_cache()
    draft = Status.objects.get_or_create(id='draft', defaults={name_attr: 'Draft'})[0]
    active = Status.objects.get_or_create(id='active', defaults={name_attr: 'Active'})[0]
    content_type = StatusyContentType.objects.get_for_model(ParentEntity)

    def transit(transit_id, src, dst):
        return Transit.objects.create(
            id=transit_id,
            model=content_type,
            status_src=src,
            status_dst=dst,
            **{name_attr: transit_id},
        )

    return {'activate': transit('activate', draft, active), 'back': transit('back', active, draft)}


@pytest.fixture
def user(db):
    # a user without roles: no permission at all
    return get_user_model().objects.create_user('user1', email='user1@site.com')


def entity_create(**kwargs):
    return ParentEntity.objects.create(name='Entity', dt_approved=APPROVED, **kwargs)


def test_get_transit_of_the_current_status(transits):
    entity = entity_create()

    assert entity.get_transit('activate') == transits['activate']
    assert entity.get_transit('back') is None
    assert entity.get_transit('missing') is None


def test_transit_of_the_system(transits, calls):
    """A transit without a user: the history has no author, nor the status."""
    entity = entity_create()
    calls.clear()

    entity = entity.transit_apply(entity.get_transit('activate'), None)

    assert (entity.status_id, entity.status_author) == ('active', None)
    record = entity.statusy_transits.get()
    assert (record.transit_id, record.status_id, record.author, record.extra) == (
        'activate',
        'active',
        None,
        {},
    )
    assert [(changes.source, changes.user) for _, changes in calls] == [('transit', None)]


def test_transit_records_the_user_without_checking_permissions(transits, user):
    entity = entity_create()

    entity = entity.transit_apply(entity.get_transit('activate'), user)
    entity = entity.transit_apply(entity.get_transit('back'), None)

    assert entity.status_id == 'draft'
    assert [(it.transit_id, it.author) for it in entity.statusy_transits.order_by('dt')] == [
        ('activate', user),
        ('back', None),
    ]


def test_transit_in_a_write_of_a_route(transits, calls, user):
    """
    In a write (a route marks the item, here as `hook_after_create` sees it) the transit is
    validated with the write, once, as the write and with its user; `scope.validate()`
    before it validates the write first.
    """
    with defer_validate_item(user=user) as scope:
        entity = entity_create()
        scope.mark(entity, 'create', user=user)
        entity.transit_apply(entity.get_transit('activate'), None)
    assert [(changes.source, changes.user) for _, changes in calls] == [('create', user)]

    calls.clear()
    with defer_validate_item(user=user) as scope:
        entity = entity_create()
        scope.mark(entity, 'create', user=user)
        scope.validate()
        assert [changes.source for _, changes in calls] == ['create']
        entity.transit_apply(entity.get_transit('activate'), None)
    assert [(changes.source, changes.user) for _, changes in calls] == [
        ('create', user),
        ('transit', user),
    ]


def test_status_fields_of_the_route():
    """
    StatusyRouteSetBase leaves the status fields out of the writes: `status_dt` and
    `status_author` of the create, all three of the update; with the `fields` of the route
    (the sample adds relations) the exclusions add up. Only an initial `status` is
    accepted on a create.
    """
    from entity.routes import ParentEntityRouteSet

    from bazis.core.schemas import CrudApiAction, SchemaFields

    create = ParentEntityRouteSet.build_schema_attrs(CrudApiAction.CREATE, 'fields', SchemaFields)
    update = ParentEntityRouteSet.build_schema_attrs(CrudApiAction.UPDATE, 'fields', SchemaFields)

    assert {'status_dt', 'status_author'} <= set(create.exclude)
    assert 'status' in create.include and 'status' not in create.exclude
    assert {'status', 'status_dt', 'status_author'} <= set(update.exclude)
    assert {'extended_entity', 'dependent_entities'} <= set(create.include)
