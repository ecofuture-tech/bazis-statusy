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
The JSON schemas of the payload of a transit: the lazy titles of its fields
(`Field(title=_('...'))`) are strings of the language active when a schema is generated (the
contract of bazis-front, the `state_actions` of a request), as the titles of the schemas of
the core are: the payload type and the body of the transit endpoint are
`TranslatedSchemaModel` of the core.
"""

import json
import warnings

from django.utils import translation

from pydantic import create_model

from entity.models import ParentEntity

from bazis.contrib.statusy.models import Transit
from bazis.contrib.statusy.schemas import (
    StateActionEndpointSchema,
    TransitActionEndpointBodySchema,
    TransitActionSchema,
)
from bazis.core.utils.schemas import TranslatedSchemaModel


TITLES = {'en': 'Status timestamp', 'ru': 'Временная метка статуса'}


def _payload_type():
    transit = Transit(
        id='to_active',
        validators=['validator_must_active'],
        actions_before=['before_dt_approved'],
        actions_after=['after_child_entities'],
    )
    # the class stands in for an object, as in the contract export of bazis-front
    return ParentEntity.transit_payload_type(ParentEntity, transit)


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
