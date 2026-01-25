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

    # add fields (extended_entity, dependent_entities) to schema
    fields = {
        None: SchemaFields(
            include={'extended_entity': None, 'dependent_entities': None},
        ),
    }
