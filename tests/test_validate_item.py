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
A transit validates the item (`JsonApiMixin.validate_item`) once, with the source
`transit` and the changes of all the saves of the transit (the status, its time and
author, the fields its actions set); a failure rolls the transit back.
"""

from datetime import UTC, datetime

from django.db import transaction

import pytest
from entity.models import ParentEntity
from translated_fields import to_attribute

from bazis.contrib.statusy.models import Status, StatusyContentType, Transit
from bazis.contrib.users import get_user_model
from bazis.core.errors import JsonApiItemInvalidException


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

    def transit(transit_id, **kwargs):
        return Transit.objects.create(
            id=transit_id,
            model=content_type,
            status_src=draft,
            status_dst=active,
            **{name_attr: transit_id},
            **kwargs,
        )

    return {
        # the action before the status sets dt_approved: the active entity is valid
        'approve': transit('approve', actions_before=['before_dt_approved']),
        'activate': transit('activate'),
    }


def test_transit_validates_once(transits, calls):
    user = get_user_model().objects.create_user('user1', email='user1@site.com')
    entity = ParentEntity.objects.create(name='Entity', author=user)
    calls.clear()

    entity = entity.transit_apply(
        transits['approve'], user, {'dt_approved': datetime(2026, 1, 1, tzinfo=UTC)}
    )

    assert len(calls) == 1, calls
    pk, changes = calls[0]
    assert pk == entity.pk
    assert (changes.source, changes.is_new, changes.user) == ('transit', False, user)
    assert changes.fields == {'status', 'status_dt', 'status_author', 'dt_approved'}
    assert changes.relations == set()
    assert entity.status_id == 'active'


def test_invalid_transit_is_rolled_back(transits, calls):
    user = get_user_model().objects.create_user('user1', email='user1@site.com')
    entity = ParentEntity.objects.create(name='Entity', author=user)
    calls.clear()

    # the transit has no savepoint of its own: the block of the caller is rolled back
    with pytest.raises(JsonApiItemInvalidException) as e, transaction.atomic():
        entity.transit_apply(transits['activate'], user)

    assert e.value.error.message_dict == {'dt_approved': ['An active entity is approved']}
    assert [changes.source for _, changes in calls] == ['transit']
    entity = ParentEntity.objects.get(pk=entity.pk)
    assert entity.status_id == 'draft'
    assert not entity.statusy_transits.exists()
