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

from django.conf import settings
from django.db import models

from bazis.core.models_abstract import JsonApiMixin


class Note(JsonApiMixin):
    """
    A model that references an uploaded file: a user attaches only a file he uploaded and
    reads it with `include=attachment` (the core checks the relationship and `included`
    against the default route of the files).
    """

    title = models.CharField(max_length=255)
    attachment = models.ForeignKey(
        'uploadable.FileUpload', blank=True, null=True, on_delete=models.SET_NULL, related_name='+'
    )


class Memo(JsonApiMixin):
    """
    A memo its owner and its readers read: its attachment is visible to them
    (`files_visible` of `MemoRouteSet`), its cover is not declared and stays private.
    """

    title = models.CharField(max_length=255)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, blank=True, null=True, on_delete=models.CASCADE, related_name='+'
    )
    readers = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='+')
    attachment = models.ForeignKey(
        'uploadable.FileUpload', blank=True, null=True, on_delete=models.SET_NULL, related_name='+'
    )
    cover = models.ForeignKey(
        'uploadable.FileUpload', blank=True, null=True, on_delete=models.SET_NULL, related_name='+'
    )


class Board(JsonApiMixin):
    """
    A board of its members, with many files (`files_visible` of `BoardRouteSet`).
    """

    title = models.CharField(max_length=255)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='+')
    files = models.ManyToManyField('uploadable.FileUpload', blank=True, related_name='+')
