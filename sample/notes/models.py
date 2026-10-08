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

from django.db import models

from bazis.core.models_abstract import JsonApiMixin


class Note(JsonApiMixin):
    """
    A model that references an uploaded file: a user who reads a note reads its file with
    `include=attachment`; the route set lets a user attach only a file he uploaded.
    """

    title = models.CharField(max_length=255)
    attachment = models.ForeignKey(
        'uploadable.FileUpload', blank=True, null=True, on_delete=models.SET_NULL, related_name='+'
    )
