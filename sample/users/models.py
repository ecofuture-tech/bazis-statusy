from bazis.contrib.permit.models_abstract import (
    AnonymousUserPermitMixin,
    PermitSelectorMixin,
    UserPermitMixin,
)
from bazis.contrib.users.models_abstract import AnonymousUserAbstract, UserAbstract
from bazis.core.models_abstract import UuidMixin


class User(UserPermitMixin, PermitSelectorMixin, UuidMixin, UserAbstract):
    pass


class AnonymousUser(AnonymousUserPermitMixin, AnonymousUserAbstract):
    pass
