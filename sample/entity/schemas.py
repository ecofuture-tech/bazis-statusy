from datetime import datetime

from pydantic import BaseModel


class ParentEntityValidatedSchema(BaseModel):
    must_active: bool


class ParentEntityBeforeSchema(BaseModel):
    dt_approved: datetime
