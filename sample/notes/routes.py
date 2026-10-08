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

from django.apps import apps

from bazis.contrib.users.routes_abstract import UserRequiredRouteBase
from bazis.core.errors import JsonApiBazisError, JsonApiBazisException


class NoteRouteSet(UserRequiredRouteBase):
    """
    The notes: every user who is logged in reads and changes them all. A user attaches
    only a file he uploaded: the core does not check yet that a relationship targets an
    object the user may see, so without these checks a user would link the file of another
    user by its id and read it with `include=attachment`.
    """

    model = apps.get_model('notes.Note')

    def check_attachment(self, file_id):
        """
        Fails with 403 unless the file is None or one the user uploaded.
        """
        if file_id is None:
            return
        files = apps.get_model('uploadable.FileUpload').objects
        if not files.filter(pk=file_id, author=self.inject.user).exists():
            raise JsonApiBazisException(
                JsonApiBazisError(
                    detail='Only a file you uploaded can be attached',
                    loc=('body', 'data', 'relationships', 'attachment'),
                    code='ERR_ATTACHMENT_NOT_OWN',
                    title='Attachment not allowed',
                    status=403,
                ),
                status=403,
            )

    def hook_before_create(self, item):
        if isinstance(item, self.model):
            self.check_attachment(item.attachment_id)
        super().hook_before_create(item)

    def hook_before_update(self, item):
        # the attachment before the update: an attachment that is kept is not checked again
        if isinstance(item, self.model):
            self.attachment_before = item.attachment_id
        super().hook_before_update(item)

    def hook_after_update(self, item):
        # runs in the transaction of the update: a failure rolls it back
        if isinstance(item, self.model) and item.attachment_id != self.attachment_before:
            self.check_attachment(item.attachment_id)
        super().hook_after_update(item)

    def hook_before_relationships_change(self, item, data, related_field_name, action):
        if related_field_name == 'attachment' and action != 'remove':
            target = data.relationships.model_dump()['attachment'].get('data') or {}
            self.check_attachment(target.get('id'))
        super().hook_before_relationships_change(item, data, related_field_name, action)
