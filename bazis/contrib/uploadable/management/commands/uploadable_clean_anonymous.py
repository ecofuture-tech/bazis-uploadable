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
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction

from bazis.contrib.uploadable.models_abstract import FileUploadAbstract, FileUploadManager


class Command(BaseCommand):
    help = (
        'Deletes the anonymous uploads older than BAZIS_FILE_UPLOAD_ANONYMOUS_TTL hours that '
        'no object references, with their files in the storage. Exits with an error if '
        'one could not be deleted (the others are).'
    )

    def handle(self, *args, **options):
        deleted, failed = 0, []
        for model in apps.get_models():
            if not issubclass(model, FileUploadAbstract):
                continue
            manager = model._default_manager
            if not isinstance(manager, FileUploadManager):
                self.stderr.write(
                    f'{model._meta.label}: its default manager is not a FileUploadManager'
                )
                failed.append(model._meta.label)
                continue
            for item in manager.anonymous_expired().only('pk', 'file'):
                try:
                    # locked while still expired and not referenced (a reference inserted
                    # meanwhile waits for the deletion and fails, the deletion does not
                    # touch it), then deleted only if still so; its file once the deletion
                    # is committed
                    with transaction.atomic():
                        still = manager.anonymous_expired().filter(pk=item.pk)
                        locked = still.select_for_update().values_list('pk', flat=True)
                        if list(locked) and still.delete()[0]:
                            transaction.on_commit(lambda item=item: self.file_delete(item, failed))
                            deleted += 1
                except DatabaseError as error:
                    self.stderr.write(f'{model._meta.label} {item.pk}: {error}')
                    failed.append(item.pk)
        self.stdout.write(f'Deleted {deleted} anonymous uploads.')
        if failed:
            raise CommandError(f'{len(failed)} anonymous uploads or files were not deleted.')

    def file_delete(self, item, failed: list):
        """
        Deletes the file of a deleted upload from the storage; a failure is reported.
        """
        try:
            item.file.storage.delete(item.file.name)
        except Exception as error:
            self.stderr.write(f'{item.file.name}: {error}')
            failed.append(item.file.name)
