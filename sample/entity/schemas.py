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

from django.utils.translation import gettext_lazy as _

from pydantic import BaseModel, Field


class ParentEntityValidatedSchema(BaseModel):
    must_active: bool


class ParentEntityBeforeSchema(BaseModel):
    # a lazy title: translated in the language of each JSON schema (a msgid of the package)
    dt_approved: datetime = Field(title=_('Status timestamp'))
