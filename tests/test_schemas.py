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
The schemas of the package use the API of Pydantic 2: `Field(example=...)` was deprecated
(`PydanticDeprecatedSince20`, a warning in the tests of every project) and kept the example
as an extra of the field.
"""

from bazis.contrib.statusy.schemas import TransitActionSchema


def test_transit_action_example():
    field = TransitActionSchema.model_fields['code']

    assert field.examples == ['ACTION_TRANSIT']
    assert field.json_schema_extra is None
    code = TransitActionSchema.model_json_schema()['properties']['code']
    assert code['examples'] == ['ACTION_TRANSIT']
    assert 'example' not in code
