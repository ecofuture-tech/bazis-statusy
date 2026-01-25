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

from bazis_test_utils import factories_abstract
from entity.models import ChildEntity, DependentEntity, ExtendedEntity, ParentEntity


class ChildEntityFactory(factories_abstract.ChildEntityFactoryAbstract):
    class Meta:
        model = ChildEntity


class DependentEntityFactory(factories_abstract.DependentEntityFactoryAbstract):
    class Meta:
        model = DependentEntity


class ExtendedEntityFactory(factories_abstract.ExtendedEntityFactoryAbstract):
    class Meta:
        model = ExtendedEntity


class ParentEntityFactory(factories_abstract.ParentEntityFactoryAbstract):
    class Meta:
        model = ParentEntity
