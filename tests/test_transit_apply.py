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
`transit_apply` in code makes only a transit of the model of the item that starts from its
current status, as the transit endpoint does: another one fails with `ERR_TRANSIT` and
changes nothing.
"""

from datetime import UTC, datetime

from django.contrib.contenttypes.models import ContentType

import pytest
from entity.models import ChildEntity, ParentEntity
from translated_fields import to_attribute

from bazis.contrib.statusy.models import Status, StatusyContentType, Transit
from bazis.core.errors import JsonApiBazisException


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


def assert_not_from_the_status(entity, transit):
    with pytest.raises(JsonApiBazisException) as e:
        entity.transit_apply(transit, None)
    (error,) = e.value.errors
    assert (e.value.status, error.code, error.item) == (400, 'ERR_TRANSIT', entity)


def test_transit_from_another_status_fails(transits):
    entity = ParentEntity.objects.create(name='Entity', dt_approved=datetime(2026, 1, 1, tzinfo=UTC))
    assert entity.status_id == 'draft'

    assert_not_from_the_status(entity, transits['back'])
    entity = ParentEntity.objects.get(pk=entity.pk)
    assert entity.status_id == 'draft'
    assert not entity.statusy_transits.exists()

    # a transit of the system (no user) from the current status
    entity = entity.transit_apply(transits['activate'], None)
    assert entity.status_id == 'active'

    assert_not_from_the_status(entity, transits['activate'])
    entity = ParentEntity.objects.get(pk=entity.pk)
    assert entity.status_id == 'active'
    assert [it.transit_id for it in entity.statusy_transits.all()] == ['activate']

    entity = entity.transit_apply(transits['back'], None)
    assert entity.status_id == 'draft'


def test_transit_of_another_model_fails(transits):
    """
    A transit of another model, even from the current status, is not a transit of the item
    (the content type of the transit is the model of the item, not a parent of it).
    """
    name_attr = to_attribute('name')
    foreign = Transit.objects.create(
        id='child_activate',
        model_id=ContentType.objects.get_for_model(ChildEntity).pk,
        status_src=transits['activate'].status_src,
        status_dst=transits['activate'].status_dst,
        **{name_attr: 'child_activate'},
    )
    entity = ParentEntity.objects.create(name='Entity', dt_approved=datetime(2026, 1, 1, tzinfo=UTC))

    assert_not_from_the_status(entity, foreign)
    entity = ParentEntity.objects.get(pk=entity.pk)
    assert entity.status_id == 'draft'
    assert not entity.statusy_transits.exists()
