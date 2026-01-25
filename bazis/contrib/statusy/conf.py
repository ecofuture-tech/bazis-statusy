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

from django.utils.translation import gettext_lazy as _

from pydantic import Field, field_validator

from bazis.core.utils.schemas import BazisSettings


def status_check(value):
    if not isinstance(value, list) or len(value) != 2:
        return False
    return True


class Settings(BazisSettings):
    BAZIS_STATUS_INITIAL: list = Field(['draft', 'Draft'], title=_('Initial status'))
    BAZIS_STATUSY_TRANSIT_MODEL: str = Field('statusy.Transit', title=_('Transit model'))
    BAZIS_STATUSY_STATUS_MODEL: str = Field('statusy.Status', title=_('Status model'))
    BAZIS_STATUSY_TRANSIT_RELATION_MODEL: str = Field(
        'statusy.TransitRelation', title=_('Transit relation model')
    )
    BAZIS_STATUSY_TRANSIT_MIDDLE_ABSTRACT_MODEL: str = Field(
        'bazis.contrib.statusy.models_abstract.StatusyTransit', title=_('Transit middle abstract model')
    )

    @field_validator('BAZIS_STATUS_INITIAL', mode='before')
    def status_check(cls, value): # noqa: N805
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError(_('Default status must be a list of 2 elements'))
        return value


settings = Settings()
