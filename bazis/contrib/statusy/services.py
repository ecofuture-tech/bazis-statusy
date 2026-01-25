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

from collections.abc import Iterable

from bazis.contrib.permit.schemas import PERM_ALL
from bazis.contrib.permit.services import PermitHandler, PermitService
from bazis.core.utils.query_complex import QueryComplex


class PermitStatusyHandler(PermitHandler):

    def get_status_field(self):
        if hasattr(self.struct, 'get_status_field'):
            status_field = self.struct.get_status_field()
            if status_field.endswith('_id'):
                status_field = status_field[:-3]
            else:
                status_field = status_field
            return status_field

    def _parse_perms(self, perms: dict) -> Iterable[tuple[dict, QueryComplex]]:
        perms_iter = super()._parse_perms(perms)

        # if the model does not assume obtaining a status - return the default set of permissions
        if not (status_field := self.get_status_field()):
            yield from perms_iter
            return

        for statuses, cond in perms_iter:
            for status, perm in statuses.items():
                if status == PERM_ALL:
                    yield perm, cond
                else:
                    yield perm, cond & {status_field: status}


class PermitStatusyService(PermitService):
    handler_class = PermitStatusyHandler
