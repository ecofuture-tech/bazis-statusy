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
    def status_check(cls, value):
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError(_('Default status must be a list of 2 elements'))
        return value


settings = Settings()
