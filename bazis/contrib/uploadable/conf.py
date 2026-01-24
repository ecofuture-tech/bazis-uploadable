from django.utils.translation import gettext_lazy as _

from pydantic import Field

from bazis.core.utils.schemas import BazisSettings


class Settings(BazisSettings):
    BAZIS_STORAGE_FILE_UPLOAD: str = Field('', title=_('Uploadable files storage engine'))


settings = Settings()
