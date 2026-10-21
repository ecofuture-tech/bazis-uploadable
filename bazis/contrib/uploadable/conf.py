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

from bazis.core.utils.rates import parse_rate
from bazis.core.utils.schemas import BazisSettings

from .signatures import SIGNATURES


class Settings(BazisSettings):
    BAZIS_STORAGE_FILE_UPLOAD: str = Field('', title=_('Uploadable files storage engine'))
    BAZIS_FILE_UPLOAD_MAX_SIZE: int = Field(
        0, title=_('Maximum size of an uploaded file in bytes (0 - no limit)'), ge=0
    )
    # anonymous uploads (a public form with files): off unless the size is limited
    BAZIS_FILE_UPLOAD_ANONYMOUS: bool = Field(False, title=_('Anonymous users upload files'))
    BAZIS_FILE_UPLOAD_ANONYMOUS_TYPES: list[str] = Field(
        ['image/jpeg', 'image/png', 'image/webp'],
        title=_('Types of the anonymous uploads, recognized by their content'),
    )
    BAZIS_FILE_UPLOAD_ANONYMOUS_TTL: int = Field(
        24, title=_('Hours an anonymous upload can be attached to an object'), ge=1
    )
    BAZIS_FILE_UPLOAD_ANONYMOUS_RATE: str = Field(
        '60/hour', title=_('Request rate of the anonymous uploads per IP address')
    )

    @field_validator('BAZIS_FILE_UPLOAD_ANONYMOUS_TYPES')
    @classmethod
    def anonymous_types_check(cls, value: list[str]) -> list[str]:
        """
        The types whose signature the package recognizes (`signatures.SIGNATURES`).
        """
        if unknown := [it for it in value if it not in SIGNATURES]:
            raise ValueError(f'{unknown} are not among {sorted(SIGNATURES)}')
        return value

    @field_validator('BAZIS_FILE_UPLOAD_ANONYMOUS_RATE')
    @classmethod
    def anonymous_rate_check(cls, value: str) -> str:
        """
        A rate of bazis.core.throttle (`'60/hour'`): the anonymous uploads are always limited.
        """
        parse_rate(value)
        return value


settings = Settings()
