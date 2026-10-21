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

from functools import partial

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from bazis.contrib.uploadable.models_abstract import FileUploadAbstract


class Command(BaseCommand):
    help = (
        'Deletes the anonymous uploads older than BAZIS_FILE_UPLOAD_ANONYMOUS_TTL hours that '
        'no object references, with their files in the storage.'
    )

    def handle(self, *args, **options):
        deleted = 0
        for model in apps.get_models():
            if not issubclass(model, FileUploadAbstract):
                continue
            for item in model.objects.anonymous_expired().only('pk', 'file'):
                # still expired and not referenced when it is deleted; its file is deleted
                # once the deletion is committed
                with transaction.atomic():
                    if model.objects.anonymous_expired().filter(pk=item.pk).delete()[0]:
                        transaction.on_commit(partial(item.file.storage.delete, item.file.name))
                        deleted += 1
        self.stdout.write(f'Deleted {deleted} anonymous uploads.')
