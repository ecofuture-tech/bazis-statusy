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

from functools import partial
from itertools import chain
from typing import Annotated, Any

from django.apps import apps
from django.conf import settings
from django.db.models import Count
from django.http import QueryDict
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from fastapi import Depends, Response

from pydantic import Field, create_model

from bazis.contrib.permit.routes_abstract import PermitRouteBase, SchemasPermit
from bazis.core.errors import JsonApi403Exception, JsonApiBazisException
from bazis.core.routes_abstract.initial import http_get, http_post, inject_make
from bazis.core.routes_abstract.jsonapi import (
    JsonapiRouteBase,
    api_action_init,
    api_action_jsonapi_init,
    api_action_response_init,
    item_id_typing,
    meta_fields_addition,
)
from bazis.core.schemas import (
    ApiAction,
    CrudAccessAction,
    CrudApiAction,
    SchemaField,
    SchemaFields,
    SchemaInclusion,
    SchemaInclusions,
    meta_field,
)
from bazis.core.services.filtering import Filtering
from bazis.core.services.includes import include_to_list
from bazis.core.utils.functools import ExcIntercept, get_attr
from bazis.core.utils.imp import import_class

from . import TransitError, schemas
from .models_abstract import StatusyChildMixin, StatusyMixin
from .schemas import (
    StateActionEndpointSchema,
    StatusyAccessAction,
    StatusyApiAction,
    TransitActionEndpointBodySchema,
    TransitActionSchema,
    payload_validate_none,
)
from .services import PermitStatusyService


class StatusRouteBase(JsonapiRouteBase):
    model = apps.get_model(settings.BAZIS_STATUSY_STATUS_MODEL)
    actions = ['action_list', 'action_retrieve']


class TransitRouteBase(JsonapiRouteBase):
    model = apps.get_model(settings.BAZIS_STATUSY_TRANSIT_MODEL)
    actions = ['action_list', 'action_retrieve']
    fields = {
        None: SchemaFields(
            exclude={
                'actions_before': None,
                'actions_after': None,
                'source_link': None,
            }
        )
    }


class SchemasStatusyPermit(SchemasPermit):

    @classmethod
    def get_builders(cls):
        return super().get_builders() | {
            StatusyApiAction.TRANSIT: cls.build_schema_transit,
        }

    def build_schema_transit(self):
        helper = self.get_helper(StatusyApiAction.TRANSIT)
        return helper.build_schema(inclusions=list(helper.inclusions))


class StatusyPermitRouteSetBase(PermitRouteBase):
    abstract: bool = True
    item: StatusyChildMixin | None = None

    @inject_make()
    class InjectPermit:
        permit: PermitStatusyService = Depends()


class StatusySimpleRouteSetBase(StatusyPermitRouteSetBase):
    abstract: bool = True
    item: StatusyChildMixin | None = None

    @inject_make()
    class InjectPermit:
        permit: PermitStatusyService = Depends()

    # @classmethod
    # def cls_init(cls):
    #     super().cls_init()
    #
    #     # a proxy model cannot be used as the base for a status route
    #     if cls.model._meta.proxy:
    #         raise Exception("Proxy model can't be model for status-route")

    def schemas_make(self):
        def get_item():
            return self.item or self.model

        self.schemas = SchemasStatusyPermit(
            type(self), self.inject.user, get_item, getattr(self.inject, 'include', [])
        )

        self.schemas_responses = SchemasStatusyPermit(
            type(self), self.inject.user, get_item, getattr(self.inject, 'include', []), True
        )

    @http_get(
        '/{item_id}/schema_transit/',
        response_model=dict[str, Any],
        endpoint_callbacks=[
            partial(api_action_init, api_action=StatusyApiAction.TRANSIT),
        ],
    )
    def action_schema_transit(
        self, item_id: str, include: str | None = Depends(include_to_list), **kwargs
    ):
        self.set_api_action(StatusyApiAction.TRANSIT)
        self.set_item(item_id)
        return self.schemas[StatusyApiAction.TRANSIT].schema()


class StatusyRouteSetBase(StatusySimpleRouteSetBase):
    abstract: bool = True
    item: StatusyMixin | None = None
    model: type[StatusyMixin]

    # list of child routes
    routes_child: list[type[StatusySimpleRouteSetBase]] = []
    _routes_child_dict: dict[type[StatusyChildMixin], type[StatusySimpleRouteSetBase]]

    fields: dict[ApiAction, SchemaFields] = {
        CrudApiAction.CREATE: SchemaFields(
            include={'status': SchemaField(required=False)},
            exclude={'status_dt': None},
        ),
        CrudApiAction.UPDATE: SchemaFields(
            exclude={'status_dt': None},
        ),
    }

    inclusions = {
        None: SchemaInclusions(
            include={
                'status': SchemaInclusion(
                    fields_struct=SchemaFields(
                        exclude={
                            'actions_before': None,
                            'actions_after': None,
                            'source_link': None,
                        }
                    )
                ),
            }
        )
    }

    @classmethod
    def cls_init(cls):
        super().cls_init()

        cls._routes_child_dict = {}
        for route in cls.routes_child:
            if isinstance(route, str):
                route = import_class(route, cls.__module__)
            cls._routes_child_dict[route.model] = route
        #
        # # based on model relations, determine whether all routes are specified in the parent
        # children_models = cls.model._statusy_children_models_dict.keys()
        #
        # print(set(children_models), set(cls._routes_child_dict.keys()))
        #
        # if set(children_models) - set(cls._routes_child_dict.keys()):
        #     raise Exception(
        #         f'StatusyRouteSetBase-base class-route must declare '
        #         f'"routes_child" for each child model: {list(children_models)}'
        #     )

    @cached_property
    def allow_transits(self) -> list[str]:
        """
        List of allowed transitions for the current user. Takes into account the current state of the object
        and the user's permissions.
        """
        permit_handler = self.inject.permit.handler(StatusyAccessAction.TRANSIT, self.item)
        if not permit_handler.check_access():
            return []
        # list of transition labels available for the current object
        labels_for_instance = {t.id for t in self.item.instance_transits}
        # list of transition labels available to the current user according to permissions
        labels_for_user = set(chain(*[it.keys() for it in permit_handler.perms_item_values]))
        # return the intersection of labels
        return list(labels_for_instance & labels_for_user)

    @http_post(
        '/{item_id}/transit/',
        endpoint_callbacks=[
            partial(meta_fields_addition, api_action=CrudApiAction.RETRIEVE),
            partial(api_action_init, api_action=StatusyApiAction.TRANSIT),
            partial(api_action_response_init, api_action=CrudApiAction.RETRIEVE),
            api_action_jsonapi_init,
            item_id_typing,
        ],
    )
    def action_transit(self, item_id: str, data: schemas.TransitRequestSchema, **kwargs):
        # set the current object without dependencies
        self.set_item(item_id, with_lock=True)

        # check permission for the transition
        if data.transit not in self.allow_transits:
            raise JsonApi403Exception(detail=_('Transition permission is missing'))

        # determine the transition by its label
        transit = self.item.get_transit(data.transit)
        if not transit:
            raise JsonApiBazisException(
                TransitError(_('This action is not allowed for this type'), item=self.item)
            )

        if transit.is_schema_validate:
            self.get_item(item_id).schema_validate(self, self.inject.user)

        # perform the actual transition
        item_updated = self.item.transit_apply(transit, self.inject.user, data.payload)

        try:
            self.check_access(CrudAccessAction.VIEW, item_updated)
        except JsonApi403Exception:
            return Response(status_code=204)
        else:
            return self.get_item(item_id)

    def _build_transits_schemas(self, transits_related, is_nested=False):
        for transit, item_selector in transits_related:
            # get the object by selector
            if not item_selector:
                item = self.item
            elif not (item := get_attr(self.item, item_selector)):
                continue

            # compute the payload data type
            payload_type = item.transit_payload_type(transit) or (dict | None)

            # compute the request body data type
            body_type = create_model(
                getattr(payload_type, '__name__', 'DictOrNone') + '_body_type',
                __base__=TransitActionEndpointBodySchema[payload_type],
                transit=(Annotated[str, Field()], Field(default=transit.id)),
            )

            with ExcIntercept(JsonApiBazisException) as err:
                item.transit_validation(transit, self.inject.user, payload_validate_none)

            # current schema
            action_schema = TransitActionSchema(
                hint=transit.hint,
                hint_title=transit.hint_title,
                hint_action=transit.hint_action,
                endpoint=StateActionEndpointSchema(
                    url=item.get_default_route().url_path_for('action_transit', item_id=item.id),
                    method='POST',
                    body=body_type.model_json_schema(),
                ),
                resource=item.resource_id,
                restricts=err.value,
            )

            # dependent schemas
            action_schemas_related = self._build_transits_schemas(
                [
                    (it.transit_child, it.item_selector)
                    for it in apps.get_model('statusy.TransitRelation').objects.filter(transit_parent=transit)
                ]
            )

            if is_nested:
                yield action_schema
                yield from action_schemas_related
            elif action_schemas_related := list(action_schemas_related):
                yield [action_schema] + action_schemas_related
            else:
                yield action_schema

    @meta_field([CrudApiAction.RETRIEVE], title=_('Object state actions'), alias='state_actions')
    def state_actions(self) -> list[TransitActionSchema | list[TransitActionSchema]]:
        return list(
            self._build_transits_schemas(
                [
                    (transit, None)
                    for transit in apps.get_model('statusy.Transit').objects.filter(
                        pk__in=self.allow_transits,
                        transit_relations_as_child=None,
                    )
                ]
            )
        )

    @meta_field([CrudApiAction.LIST], title=_('Number of elements by status'), alias='status_aggs')
    def status_aggs(self) -> dict[str, int]:
        # create a copy of the filtering query
        query_filter = QueryDict(self.inject.filtering.query_str, mutable=True)
        # remove the status parameter from it
        query_filter.pop('status', None)

        # apply filters without status + string search
        qs = self.restrict_queryset(self.get_queryset(), CrudAccessAction.VIEW)
        qs = Filtering.qs_apply(
            qs,
            query_filter.urlencode('$|()[]~'),
            filters_aliases=self.filters_aliases,
            fiter_context=self.get_fiter_context(),
        )
        qs = self.inject.searching.apply(qs)

        # collect aggregation
        return {
            it['status']: it['_count'] for it in qs.values('status').annotate(_count=Count('*'))
        }

    @meta_field([CrudApiAction.LIST], title=_('Allowed statuses'), alias='status_allowed')
    def status_allowed(self) -> list[str]:
        return self.model.get_model_statuses()
