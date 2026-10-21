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

from datetime import datetime
from types import UnionType
from typing import Annotated, Any, Literal, TypeVar, Union, get_args, get_origin

from django.core.exceptions import ImproperlyConfigured
from django.utils.functional import cached_property

from fastapi.encoders import jsonable_encoder

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bazis.core.errors import JsonApiBazisException
from bazis.core.schemas import AccessAction, ApiAction
from bazis.core.utils.schemas import CommonResourceSchema, TranslatedSchemaModel


#: Stub for determining payload in validation mode
payload_validate_none = object()


class _NotInHistory:
    def __repr__(self):
        return 'NOT_IN_HISTORY'


#: The mark of a field of a payload model that the history record of the transit does not
#: keep (`secret: Annotated[str | None, NOT_IN_HISTORY] = None`, or `Annotated[str,
#: NOT_IN_HISTORY] | None`): the field is validated and the methods of the transit receive
#: it, `extra['payload']` of the record leaves it out
NOT_IN_HISTORY = _NotInHistory()


def fields_not_in_history(model: type[BaseModel]) -> set[str]:
    """
    The names of the fields of a payload model marked `NOT_IN_HISTORY`: in the annotation of
    the field or of a member of its union (`Optional`). A mark anywhere else (an item of a
    list, a field of a nested model) would not leave the value out of the history: it is
    ImproperlyConfigured.
    """
    names = set()
    for name, field in model.model_fields.items():
        # every member of the union is checked, a misplaced mark fails in any of them
        marked = _union_marked(field.annotation, f'{model.__name__}.{name}', set())
        if marked or NOT_IN_HISTORY in field.metadata:
            names.add(name)
    return names


def _union_marked(tp, path: str, seen: set) -> bool:
    """
    Whether the annotation of a field, or a member of its union, is marked; a mark inside
    them is an error.
    """
    if get_origin(tp) is Annotated:
        base, *metadata = get_args(tp)
        return _union_marked(base, path, seen) or NOT_IN_HISTORY in metadata
    if get_origin(tp) in (Union, UnionType):
        return any([_union_marked(arg, path, seen) for arg in get_args(tp)])
    _check_not_marked(tp, path, seen)
    return False


def _check_not_marked(tp, path: str, seen: set) -> None:
    metadata = ()
    if get_origin(tp) is Annotated:
        tp, *metadata = get_args(tp)
    _refuse_mark(metadata, path)
    if get_origin(tp) is None and isinstance(tp, type) and issubclass(tp, BaseModel):
        if tp in seen:
            return
        seen.add(tp)
        for name, field in tp.model_fields.items():
            _refuse_mark(field.metadata, f'{path}.{name}')
            _check_not_marked(field.annotation, f'{path}.{name}', seen)
    else:
        for arg in get_args(tp):
            _check_not_marked(arg, path, seen)


def _refuse_mark(metadata, path: str) -> None:
    if NOT_IN_HISTORY in metadata:
        raise ImproperlyConfigured(
            f'NOT_IN_HISTORY must mark a field of the payload model (or its Optional): {path}'
        )


class StatusyAccessAction(AccessAction):
    TRANSIT = 'transit'
    #: reading the history of the transits with their payloads (`GET /{item_id}/status_history/`)
    HISTORY = 'history'


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


class StatusHistoryEntry(BaseModel):
    """
    A transit of the history of an item (`StatusyMixin.status_history`): the transit, the
    status it set, its time and the id of its author (None for a system transit).
    """

    transit: str
    status: str
    dt: datetime
    author: str | int | None = None


class StatusHistoryTransitSchema(BaseModel):
    id: str
    name: str


class StatusHistoryRecordSchema(BaseModel):
    """
    A transit of the item in `GET /{item_id}/status_history/`: the transit (its id and
    name), the statuses it went from (kept in the record; for a record made before 2.15,
    the source status of the current definition of the transit) and to, its time, its
    author (None for a transit of the system) and the payload it was made with (None
    without one; the fields marked `NOT_IN_HISTORY` are not kept).
    """

    transit: StatusHistoryTransitSchema
    status_src: str
    status_dst: str
    dt: datetime
    author: CommonResourceSchema | None = None
    payload: dict | None = None


class StatusHistoryResponseSchema(BaseModel):
    data: list[StatusHistoryRecordSchema]


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
            code_field = type(self).model_fields['code']

            if get_origin(code_field.annotation) == Literal:
                data['code'] = code_field.annotation.__args__[0]
            else:
                data['code'] = code_field.default
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


class TransitActionEndpointBodySchema[TransitPayloadSchemaT](TranslatedSchemaModel):
    transit: str
    payload: TransitPayloadSchemaT


class TransitActionSchema(StateActionSchema):
    code: Literal['ACTION_TRANSIT'] = Field(
        'ACTION_TRANSIT', examples=['ACTION_TRANSIT'], title='Transit'
    )
    resource: CommonResourceSchema
