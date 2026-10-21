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
from typing import Annotated, Optional

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

from pydantic import BaseModel

import pytest
from entity.models import ChildEntity, ParentEntity
from translated_fields import to_attribute

from bazis.contrib.statusy import TransitError
from bazis.contrib.statusy.models import Status, StatusyContentType, Transit
from bazis.contrib.statusy.schemas import NOT_IN_HISTORY, fields_not_in_history
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


def test_payload_as_a_dict_or_a_model_instance(transits):
    """
    The payload of `transit_apply` is the dict of the body of the transit endpoint or an
    instance of a payload model, validated as its data with the payload type of the transit
    (a model inheriting the payload models of all its methods): an instance of one of them
    lacks the fields of the others (422).
    """
    from entity.schemas import ParentEntityBeforeSchema, ParentEntityValidatedSchema

    approved = datetime(2026, 2, 1, tzinfo=UTC)
    activate = transits['activate']
    activate.actions_before = ['before_dt_approved']
    activate.save()

    entity = ParentEntity.objects.create(name='Entity')
    entity = entity.transit_apply(activate, None, ParentEntityBeforeSchema(dt_approved=approved))
    assert (entity.status_id, entity.dt_approved) == ('active', approved)

    entity = entity.transit_apply(transits['back'], None)
    entity = entity.transit_apply(activate, None, {'dt_approved': approved.isoformat()})
    assert entity.status_id == 'active'

    entity = entity.transit_apply(transits['back'], None)
    activate.validators = ['validator_must_active']
    activate.save()
    with pytest.raises(JsonApiBazisException) as e:
        entity.transit_apply(activate, None, ParentEntityValidatedSchema(must_active=True))
    assert e.value.status == 422
    assert [err.loc for err in e.value.errors] == [('payload', 'dt_approved')]

    payload = entity.transit_payload_type(activate)(must_active=True, dt_approved=approved)
    assert entity.transit_apply(activate, None, payload).status_id == 'active'


class SecretOrNone(BaseModel):
    secret: Annotated[str, NOT_IN_HISTORY] | None = None
    note: str | None = None


class SecretOptional(BaseModel):
    secret: Optional[Annotated[str, NOT_IN_HISTORY]] = None  # noqa: UP045 (the form tested)
    note: str | None = None


class SecretMarkedOptional(BaseModel):
    secret: Annotated[str | None, NOT_IN_HISTORY] = None
    note: str | None = None


class Nested(BaseModel):
    secret: Annotated[str, NOT_IN_HISTORY]


class SecretInAList(BaseModel):
    secrets: list[Annotated[str, NOT_IN_HISTORY]] = []


class SecretInANestedModel(BaseModel):
    nested: Nested | None = None


def payload_transit(transits, monkeypatch, payload_model, received):
    def before_payload(self, statusy_transit, payload: payload_model):
        received.append(payload)

    monkeypatch.setattr(ParentEntity, 'before_payload', before_payload, raising=False)
    activate = transits['activate']
    activate.actions_before = ['before_payload']
    activate.save()
    return activate


@pytest.mark.parametrize('payload_model', [SecretOrNone, SecretOptional, SecretMarkedOptional])
def test_a_field_not_in_history_is_given_to_the_actions(transits, monkeypatch, payload_model):
    """
    A field of a payload model marked `NOT_IN_HISTORY`, in its annotation or in a member of
    its `Optional`, is validated and the actions receive it, from a dict and from a payload
    model instance; the history record does not keep it, it keeps the other fields.
    """
    received = []
    activate = payload_transit(transits, monkeypatch, payload_model, received)
    assert fields_not_in_history(ParentEntity.get_transit_payload_type(activate)) == {'secret'}

    entity = ParentEntity.objects.create(name='Entity', dt_approved=datetime(2026, 1, 1, tzinfo=UTC))
    entity = entity.transit_apply(activate, None, {'secret': 'from a dict', 'note': 'kept'})
    entity = entity.transit_apply(transits['back'], None)
    entity.transit_apply(activate, None, payload_model(secret='from a model', note='kept'))

    assert [it.secret for it in received] == ['from a dict', 'from a model']
    stored = {'status_src': 'draft', 'payload': {'note': 'kept'}}
    assert [
        it.extra for it in entity.statusy_transits.filter(transit=activate).order_by('dt')
    ] == [stored, stored]


@pytest.mark.parametrize(
    'payload_model, path',
    [
        (SecretInAList, 'SecretInAList.secrets'),
        (SecretInANestedModel, 'SecretInANestedModel.nested.secret'),
    ],
)
def test_a_mark_the_history_would_not_honor_fails(transits, monkeypatch, payload_model, path):
    """
    A `NOT_IN_HISTORY` mark elsewhere than on a field of the payload model or its
    `Optional` (an item of a list, a field of a nested model) would keep the value in the
    history: the payload type of the transit is not built, nothing is written.
    """
    activate = payload_transit(transits, monkeypatch, payload_model, [])
    entity = ParentEntity.objects.create(name='Entity')

    with pytest.raises(ImproperlyConfigured) as raised:
        entity.transit_apply(activate, None, {})
    assert str(raised.value) == (
        f'NOT_IN_HISTORY must mark a field of the payload model (or its Optional): {path}'
    )
    assert not entity.statusy_transits.exists()


def test_a_failed_transit_keeps_no_record(transits, monkeypatch):
    """
    An action after that fails rolls the transit back with its history record and payload.
    """
    activate = transits['activate']
    activate.actions_before = ['before_dt_approved']
    activate.actions_after = ['after_fail']
    activate.save()

    def after_fail(self, statusy_transit, payload):
        raise TransitError('The action after failed')

    monkeypatch.setattr(ParentEntity, 'after_fail', after_fail, raising=False)
    entity = ParentEntity.objects.create(name='Entity')

    with pytest.raises(TransitError), transaction.atomic():
        entity.transit_apply(activate, None, {'dt_approved': '2026-02-01T00:00:00Z'})

    entity = ParentEntity.objects.get(pk=entity.pk)
    assert entity.status_id == 'draft'
    assert not entity.statusy_transits.exists()
