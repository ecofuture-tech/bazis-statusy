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

from django.contrib import admin

from . import models
from .admin_abstract import (
    StatusAdminBase,
    StatusyContentTypeAdminBase,
    TransitAdminBase,
    TransitInlineBase,
    TransitRelationInlineBase,
)


@admin.register(models.Status)
class StatusAdmin(StatusAdminBase):
    pass


class TransitInline(TransitInlineBase):
    model = models.Transit


@admin.register(models.StatusyContentType)
class StatusyContentTypeAdmin(StatusyContentTypeAdminBase):
    inlines = [TransitInline]


class TransitRelationInline(TransitRelationInlineBase):
    model = models.TransitRelation


@admin.register(models.Transit)
class TransitAdmin(TransitAdminBase):
    inlines = [TransitRelationInline]
