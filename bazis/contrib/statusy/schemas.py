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

from typing import Any, Literal, TypeVar, get_origin

from django.utils.functional import cached_property

from fastapi.encoders import jsonable_encoder

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bazis.core.errors import JsonApiBazisException
from bazis.core.schemas import AccessAction, ApiAction
from bazis.core.utils.schemas import CommonResourceSchema


#: Stub for determining payload in validation mode
payload_validate_none = object()


class StatusyAccessAction(AccessAction):
    TRANSIT = 'transit'


class StatusyApiAction(ApiAction):
    TRANSIT = 'transit'

    @cached_property
    def access_action(self):
        return {
            StatusyApiAction.TRANSIT: StatusyAccessAction.TRANSIT,
        }[self]

    @cached_property
    def for_read_only(self):
        return True

    @cached_property
    def for_write_only(self):
        if self.access_action in (StatusyAccessAction.TRANSIT,):
            return True
        return False


class TransitRequestSchema(BaseModel):
    transit: str
    payload: Any | None = None


class StateActionEndpointSchema(BaseModel):
    url: str
    method: str
    body: dict | None = None


class StateActionRestrictsSchema(BaseModel):
    title: str
    code: str
    detail: str | None = None
    meta: dict | None = None


class StateActionSchema(BaseModel):
    code: str
    endpoint: StateActionEndpointSchema
    restricts: list[StateActionRestrictsSchema] | None = None
    hint: str | None = None
    hint_title: str | None = None
    hint_action: str | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, **data: Any):
        # explicitly set code to bypass value exclusion when the exclude_unset parameter is triggered
        if 'code' not in data:
            code_field = self.model_fields['code']

            if get_origin(code_field.annotation) == Literal:
                data['code'] = code_field.annotation.__args__[0]
            else:
                data['code'] = self.model_fields['code'].default
        super().__init__(**data)

    @field_validator('restricts', mode='before')
    def restricts_to_dict(cls, v):  # noqa: N805
        if v and isinstance(v, JsonApiBazisException):
            return jsonable_encoder(
                [
                    {
                        'title': err.title,
                        'code': err.code,
                        'detail': err.detail,
                        'meta': err.meta,
                    }
                    for err in v.errors
                ]
            )
        return v


TransitPayloadSchemaT = TypeVar('TransitPayloadSchemaT')


class TransitActionEndpointBodySchema[TransitPayloadSchemaT](BaseModel):
    transit: str
    payload: TransitPayloadSchemaT


class TransitActionSchema(StateActionSchema):
    code: Literal['ACTION_TRANSIT'] = Field(
        'ACTION_TRANSIT', example='ACTION_TRANSIT', title='Transit'
    )
    resource: CommonResourceSchema
