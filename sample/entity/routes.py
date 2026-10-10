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

from django.apps import apps

from bazis.contrib.statusy.routes_abstract import StatusyRouteSetBase, StatusySimpleRouteSetBase
from bazis.contrib.statusy.schemas import TransitRequestSchema
from bazis.core.routes_abstract.initial import http_post
from bazis.core.schemas import SchemaFields


class ChildEntityRouteSet(StatusySimpleRouteSetBase):
    model = apps.get_model('entity.ChildEntity')

    fields = {
        None: SchemaFields(
            include={
                'parent_entities': None,
            },
        ),
    }


class DependentEntityRouteSet(StatusySimpleRouteSetBase):
    model = apps.get_model('entity.DependentEntity')


class ExtendedEntityRouteSet(StatusySimpleRouteSetBase):
    model = apps.get_model('entity.ExtendedEntity')


class ParentEntityRouteSet(StatusyRouteSetBase):
    model = apps.get_model('entity.ParentEntity')
    search_fields = ['name']
    # the restrictions of the parent entities for the other routes
    default_route = True

    # add fields (extended_entity, dependent_entities) to schema
    fields = {
        None: SchemaFields(
            include={'extended_entity': None, 'dependent_entities': None},
        ),
    }


class ParentEntityGuestRouteSet(StatusyRouteSetBase):
    """
    The transits of the parent entities open to anonymous users (with the transit
    permissions of the roles for anonymous users): an override with `public=True`.
    """

    model = apps.get_model('entity.ParentEntity')
    actions = ['action_transit']

    @classmethod
    def get_url_prefix(cls) -> str:
        return '/entity/parent_entity_guest'

    @http_post(
        '/{item_id}/transit/',
        public=True,
        endpoint_callbacks=StatusyRouteSetBase.action_transit.endpoint_callbacks,
    )
    def action_transit(self, item_id: str, data: TransitRequestSchema, **kwargs):
        return StatusyRouteSetBase.action_transit.func(self, item_id, data, **kwargs)
