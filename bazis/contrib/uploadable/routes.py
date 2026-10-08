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
from django.conf import settings
from django.db.models import QuerySet
from django.utils.translation import gettext as _

from fastapi import Form, Request

from bazis.contrib.author.routes_abstract import AuthorRequiredRouteBase
from bazis.contrib.users.models_abstract import UserMixin
from bazis.core.errors import JsonApiBazisError, JsonApiBazisException
from bazis.core.routes_abstract.initial import http_post
from bazis.core.routes_abstract.jsonapi import (
    RestrictedQsRouteMixin,
    api_action_init,
    api_action_jsonapi_init,
    api_action_response_init,
    item_data_typing,
    meta_fields_addition,
)
from bazis.core.schemas import AccessAction, CrudAccessAction, CrudApiAction, SchemaFields
from bazis.core.utils.django_types import UploadFileDjango


class FileUploadRouteSet(RestrictedQsRouteMixin, AuthorRequiredRouteBase):
    """
    The uploaded files of the user: a user who is logged in uploads a file (he becomes its
    `author`), lists and reads his own files. No file is changed or deleted through the
    route. As the default route of the files, its `restrict_queryset` is also what the
    other routes link and include (bazis 2.7): a user links and sees in `included` only
    the files he uploaded (see AGENTS.md to widen it).
    """

    model = apps.get_model('uploadable.FileUpload')
    actions_exclude = [
        'action_update',
        'action_schema_update',
        'action_destroy',
        'action_post_relationships',
        'action_update_relationships',
        'action_delete_relationships',
    ]

    # the author is the user himself; through `include` it would show the user who uploaded
    # the attachment of a shared object
    fields = {
        None: SchemaFields(
            include={
                'size': None,
                'extension': None,
            },
            exclude={'author': None, 'author_updated': None},
        )
    }

    @http_post(
        '/',
        status_code=201,
        endpoint_callbacks=[
            partial(meta_fields_addition, api_action=CrudApiAction.CREATE),
            partial(api_action_init, api_action=CrudApiAction.CREATE),
            partial(api_action_response_init, api_action=CrudApiAction.RETRIEVE),
            partial(item_data_typing, api_action=CrudApiAction.CREATE),
            api_action_jsonapi_init,
        ],
    )
    def action_create(
        self,
        request: Request,
        file: UploadFileDjango,
        name: str | None = Form(None),
        **kwargs,
    ):
        max_size = settings.BAZIS_FILE_UPLOAD_MAX_SIZE
        if max_size and (file.size or 0) > max_size:
            raise JsonApiBazisException(
                JsonApiBazisError(
                    detail=_('The file is larger than %(size)s bytes') % {'size': max_size},
                    loc=('body', 'file'),
                    code='ERR_FILE_TOO_LARGE',
                    title=_('File too large'),
                    status=413,
                ),
                status=413,
            )

        if not isinstance(file, UploadFileDjango):
            file.__class__ = UploadFileDjango

        request._json = {
            'data': {
                'type': self.model.get_resource_label(),
                'attributes': {
                    'name': name,
                    'file': file,
                }
            },
        }

        item_data = self.schema_defaults[CrudApiAction.CREATE].model_validate(request._json)

        return super().action_create.func(self, request, item_data)

    @classmethod
    def restrict_queryset(
        cls, qs: QuerySet, access_action: AccessAction, user=None, **kwargs
    ) -> QuerySet:
        """
        The files the user uploaded, for every action. Without a user (a route without a
        user, e.g. called by the core for the relationships of another route) the
        authenticated user of the request (`UserMixin.CTX_USER_REQUEST`); none for an
        anonymous user.
        """
        if user is None:
            user = UserMixin.CTX_USER_REQUEST.get()
        if user is None or user.is_anonymous:
            return qs.none()
        return super().restrict_queryset(qs, access_action, user=user, **kwargs).filter(author=user)

    def get_queryset(self):
        """
        The files of the user.
        """
        return self.restrict_queryset(
            super().get_queryset(), CrudAccessAction.VIEW, user=self.inject.user
        )
