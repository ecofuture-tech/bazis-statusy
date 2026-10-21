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
The payload type of a transit strips its texts before their constraints are checked. The JSON
schemas of the payload of a transit: the lazy titles of its fields
(`Field(title=_('...'))`) are strings of the language active when a schema is generated (the
contract of bazis-front, the `state_actions` of a request), as the titles of the schemas of
the core are: the payload type and the body of the transit endpoint are
`TranslatedSchemaModel` of the core.
"""

import json
import warnings

from django.contrib.contenttypes.models import ContentType
from django.utils import translation

from pydantic import BaseModel, Field, create_model

import pytest
from entity.models import ParentEntity

from bazis.contrib.statusy.models import Transit
from bazis.contrib.statusy.schemas import (
    StateActionEndpointSchema,
    TransitActionEndpointBodySchema,
    TransitActionSchema,
    payload_validate_none,
)
from bazis.core.errors import JsonApiBazisException
from bazis.core.utils.schemas import TranslatedSchemaModel


TITLES = {'en': 'Status timestamp', 'ru': 'Временная метка статуса'}


def _payload_type():
    transit = Transit(
        id='to_active',
        validators=['validator_must_active'],
        actions_before=['before_dt_approved'],
        actions_after=['after_child_entities'],
    )
    return ParentEntity.get_transit_payload_type(transit)


def test_payload_schemas_of_the_core():
    """
    The lazy texts are translated by the generator of the core, not by one of the package.
    """
    from bazis.contrib.statusy import schemas

    assert issubclass(_payload_type(), TranslatedSchemaModel)
    assert issubclass(TransitActionEndpointBodySchema, TranslatedSchemaModel)
    assert not hasattr(schemas, 'TranslatedJsonSchema')


def test_payload_titles_translated_per_schema():
    payload_type = _payload_type()

    for language, title in TITLES.items():
        with translation.override(language):
            schema = payload_type.model_json_schema()
        # a plain JSON document: the export of the contract serializes it
        assert json.loads(json.dumps(schema)) == schema
        assert schema['properties']['dt_approved']['title'] == title
        assert schema['properties']['must_active']['title'] == 'Must Active'


def test_transit_body_titles_translated_per_schema():
    """
    The body of the transit endpoint in `state_actions`: the payload type is a definition of
    the body schema.
    """
    payload_type = _payload_type()
    body_type = create_model('Body', __base__=TransitActionEndpointBodySchema[payload_type])

    for language, title in TITLES.items():
        with translation.override(language):
            schema = body_type.model_json_schema()
        payload_schema = schema['$defs'][payload_type.__name__]
        assert payload_schema['properties']['dt_approved']['title'] == title
        # the response serializes the body as it is
        endpoint = StateActionEndpointSchema(url='/transit/', method='POST', body=schema)
        assert json.loads(endpoint.model_dump_json())['body'] == schema


def test_transit_action_schema_no_deprecation_warning():
    """
    The default `code` of a state action is read from the class: `model_fields` of an
    instance is deprecated since Pydantic 2.11.
    """
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        action = TransitActionSchema(
            endpoint=StateActionEndpointSchema(url='/transit/', method='POST'),
            resource={'id': '1', 'type': 'entity.parent_entity'},
        )
    assert action.code == 'ACTION_TRANSIT'


class ReasonPayload(BaseModel):
    reason: str = Field(title='Reason', min_length=1, max_length=20)


@pytest.mark.django_db
def test_required_text_of_the_payload_is_stripped(monkeypatch):
    """
    The payload type strips its texts before their length is checked: a reason of only
    spaces is refused at its field, the methods receive the stripped text.
    """
    received = []

    def validator_reason(self, transit, user, payload: ReasonPayload):
        if payload is not payload_validate_none:
            received.append(payload.reason)

    monkeypatch.setattr(ParentEntity, 'validator_reason', validator_reason, raising=False)
    transit = Transit(
        id='reject',
        model=ContentType.objects.get_for_model(ParentEntity),
        validators=['validator_reason'],
    )
    item = ParentEntity()

    for blank in ('', '   ', '\t\n '):
        with pytest.raises(JsonApiBazisException) as raised:
            item.transit_validation(transit, None, {'reason': blank})
        assert raised.value.status == 422
        (error,) = raised.value.errors
        assert error.loc == ('payload', 'reason')
    assert received == []

    item.transit_validation(transit, None, {'reason': '  too late  '})
    item.transit_validation(transit, None, ReasonPayload(reason=' x '))
    assert received == ['too late', 'x']


def test_payload_type_of_a_transit_without_payload_is_none():
    transit = Transit(id='no_payload', validators=[], actions_before=[], actions_after=[])

    assert ParentEntity.get_transit_payload_type(transit) is None


@pytest.mark.django_db
def test_the_old_name_returns_the_class_method(monkeypatch):
    """
    `transit_payload_type`, the old name of the classmethod, returns what it returns.
    """
    marker = object()
    monkeypatch.setattr(
        ParentEntity, 'get_transit_payload_type', classmethod(lambda cls, transit: marker)
    )

    assert ParentEntity().transit_payload_type(Transit(id='x')) is marker


@pytest.mark.django_db
def test_the_classmethod_is_the_hook(monkeypatch):
    """
    A model changes the payload type of a transit in one place, the classmethod: the
    validation of a transit (`transit_apply`, the transit endpoint) uses it.
    """
    monkeypatch.setattr(
        ParentEntity, 'get_transit_payload_type', classmethod(lambda cls, transit: ReasonPayload)
    )
    transit = Transit(
        id='reject', model=ContentType.objects.get_for_model(ParentEntity), validators=[]
    )
    item = ParentEntity()

    payload = item.transit_validation(transit, None, {'reason': 'x'})
    assert isinstance(payload, ReasonPayload)
    assert payload.reason == 'x'
    with pytest.raises(JsonApiBazisException) as raised:
        item.transit_validation(transit, None, {})
    assert raised.value.status == 422


def test_the_class_stands_in_for_an_object():
    """
    bazis-front 0.6 reads the payload type of a transit with the class in place of an
    object (`Model.transit_payload_type(Model, transit)`): the same schema as the classmethod.
    """
    transit = Transit(
        id='activate',
        validators=['validator_must_active'],
        actions_before=['before_dt_approved'],
        actions_after=[],
    )

    assert (
        ParentEntity.transit_payload_type(ParentEntity, transit).model_json_schema()
        == ParentEntity.get_transit_payload_type(transit).model_json_schema()
    )
