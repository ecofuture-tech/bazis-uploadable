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

import os
from functools import partial, reduce
from operator import or_

from django.apps import apps
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Model, Q, QuerySet
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.utils.translation import gettext as _

from fastapi import Depends, Form, HTTPException, Request

from starlette.responses import StreamingResponse

from bazis.contrib.author.routes_abstract import AuthorRequiredRouteBase
from bazis.contrib.users.models_abstract import UserMixin
from bazis.contrib.users.service import get_user_from_token, get_user_optional, get_user_required
from bazis.core.errors import JsonApiBazisError, JsonApiBazisException
from bazis.core.routes_abstract.initial import http_get, http_post
from bazis.core.routes_abstract.jsonapi import (
    RestrictedQsRouteMixin,
    api_action_init,
    api_action_jsonapi_init,
    api_action_response_init,
    item_data_typing,
    meta_fields_addition,
)
from bazis.core.schemas import AccessAction, CrudAccessAction, CrudApiAction, SchemaFields
from bazis.core.schemas.enums import RouteKind
from bazis.core.throttle import Throttle
from bazis.core.utils.django_types import UploadFileDjango
from bazis.core.utils.functools import inheritors

from .signatures import HEAD_SIZE, SIGNATURES, signature_type
from .storages import INLINE_CONTENT_TYPES, served_content_type


#: the size of the chunks a download reads from the storage
DOWNLOAD_CHUNK_SIZE = 64 * 1024

#: the attributes of an anonymous upload its uploader reads in the response: not its URL
ANONYMOUS_FIELDS = ('name', 'extension', 'size')


def anonymous_uploads() -> bool:
    """
    Whether anonymous users upload files: `BAZIS_FILE_UPLOAD_ANONYMOUS` with a size limit
    (`BAZIS_FILE_UPLOAD_MAX_SIZE`; without one they do not, `uploadable.E002`).
    """
    return settings.BAZIS_FILE_UPLOAD_ANONYMOUS and settings.BAZIS_FILE_UPLOAD_MAX_SIZE > 0


def upload_user(user=Depends(get_user_from_token)):
    """
    The user of an upload: the user of the token, an anonymous user without one when
    anonymous uploads are on (`anonymous_uploads`), else 401 as for the other routes.
    """
    if user is None and anonymous_uploads():
        return get_user_optional(user)
    return get_user_required(user)


def anonymous_rate() -> str:
    """
    The rate of the anonymous uploads per IP address (`BAZIS_FILE_UPLOAD_ANONYMOUS_RATE`).
    """
    return settings.BAZIS_FILE_UPLOAD_ANONYMOUS_RATE


class AnonymousThrottle(Throttle):
    """
    A throttle that counts only the requests of anonymous users: the uploads of a user who is
    logged in are not limited.
    """

    def check(self, request: Request, user=None, scope: str | None = None) -> None:
        if not getattr(user, 'is_authenticated', False):
            super().check(request, user=user, scope=scope)


def files_visible_field(model: type[Model], name: str) -> type[Model] | None:
    """
    The model a name of `files_visible` of a route set of the model refers to: the related
    model of its forward relation (a foreign key, a one-to-one or a many-to-many field),
    else None.
    """
    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist:
        return None
    if not field.is_relation or field.auto_created:
        return None
    return field.related_model


def files_visible_declarations() -> list[type]:
    """
    The route classes that declare `files_visible` in their own body, by module and name:
    a subclass does not inherit the declaration (it would make the files visible through
    every route class of the model derived from it).
    """
    from bazis.core.routes_abstract.jsonapi import JsonapiRouteBase

    return sorted(
        (it for it in inheritors(JsonapiRouteBase) if 'files_visible' in vars(it)),
        key=lambda it: (it.__module__, it.__qualname__),
    )


def files_visible_problem(route_cls) -> str | None:
    """
    Why the declaration of `files_visible` of a route class makes no file visible, or None:
    it is on an abstract route class (or one without a model), or it is not a tuple of
    field names (`uploadable.E001`).
    """
    names = route_cls.files_visible
    if getattr(route_cls, 'abstract', False) or getattr(route_cls, 'model', None) is None:
        return (
            'is declared on an abstract route class (or one without a model): it is not inherited'
        )
    if not isinstance(names, tuple | list) or not all(isinstance(it, str) for it in names):
        return f'is {names!r}, not a tuple of field names'
    return None


#: the declarations of `files_visible` by model of files, kept once the application is
#: loaded (its routers have imported the route sets)
_files_visible_cache: dict[type[Model], list[tuple[type, tuple[str, ...]]]] = {}


def files_visible_cache_clear() -> None:
    """
    Forgets the declarations of `files_visible`: for a route set defined after the
    application is loaded (a test).
    """
    _files_visible_cache.clear()


def files_visible_routes(files_model: type[Model]) -> list[tuple[type, tuple[str, ...]]]:
    """
    The route sets that make the files of `files_model` visible through their objects:
    the declaring route classes with their names of `files_visible` that refer to
    `files_model` (a declaration with a problem, `uploadable.E001`, refers to none).
    Resolved once the application is loaded, every time before.
    """
    from bazis.core.introspect import loaded_app

    if (cached := _files_visible_cache.get(files_model)) is not None:
        return cached
    result = []
    for route_cls in files_visible_declarations():
        if files_visible_problem(route_cls):
            continue
        names = tuple(
            it
            for it in route_cls.files_visible
            if files_visible_field(route_cls.model, it) is files_model
        )
        if names:
            result.append((route_cls, names))
    if loaded_app() is not None:
        _files_visible_cache[files_model] = result
    return result


def files_visible_q(files_model: type[Model], user) -> Q | None:
    """
    The files of `files_model` the user sees through the objects that reference them: the
    files of the fields of `files_visible` of the objects each declaring route set shows
    the user (its `restrict_queryset` for VIEW; all the objects if it does not restrict
    them). None if no route set declares them.
    """
    conditions = []
    for route_cls, names in files_visible_routes(files_model):
        objects = route_cls.model.objects.all()
        if restrict := getattr(route_cls, 'restrict_queryset', None):
            objects = restrict(objects, CrudAccessAction.VIEW, user=user)
        for name in names:
            conditions.append(
                Q(pk__in=objects.filter(**{f'{name}__isnull': False}).values(name))
            )
    return reduce(or_, conditions) if conditions else None


class FileUploadRouteSet(RestrictedQsRouteMixin, AuthorRequiredRouteBase):
    """
    The uploaded files of the user: a user who is logged in uploads a file (he becomes its
    `author`), lists, reads and downloads his own files and the files of the objects he
    sees through a route set that declares them in `files_visible`. No file is changed or
    deleted through the route. As the default route of the files, its `restrict_queryset`
    is also what the other routes link and include (bazis 2.7): `included` shows the files
    he sees, a relationship links only the files he uploaded (`link=True`, bazis 2.16).
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
            exclude={'author': None, 'author_updated': None, 'uploaded_anonymously': None},
        )
    }

    @http_post(
        '/',
        status_code=201,
        # known when the routes are imported: anonymous users may call it (`upload_user`)
        public=anonymous_uploads() or None,
        dependencies=[Depends(AnonymousThrottle(anonymous_rate, key='ip'))],
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
        user=Depends(upload_user),
        **kwargs,
    ):
        """
        Uploads a file: the user becomes its author. An anonymous user (`anonymous_uploads`)
        uploads only a file of `BAZIS_FILE_UPLOAD_ANONYMOUS_TYPES` (by its content, 422
        otherwise), stored with the extension of its type and without an author, and reads
        back only its id and `ANONYMOUS_FIELDS`.
        """
        anonymous = not user.is_authenticated
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

        if anonymous:
            name = file.filename = self.anonymous_name(file, name)

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

        if anonymous:
            # he does not see the file (`restrict_queryset`): it is answered as it is created
            item = self.create(request._json, item_data)
            item.only_fields = ANONYMOUS_FIELDS
            return {'data': item}
        return super().action_create.func(self, request, item_data)

    def hook_before_create(self, item):
        """
        An upload of an anonymous user is marked with its time (`uploaded_anonymously`).
        """
        super().hook_before_create(item)
        if not self.inject.user.is_authenticated:
            item.uploaded_anonymously = timezone.now()

    @staticmethod
    def anonymous_name(file, name: str | None) -> str:
        """
        The name of an anonymous upload: its name (or the name of the file) with the
        extension of the type of its content, which must be one of
        `BAZIS_FILE_UPLOAD_ANONYMOUS_TYPES` (422 `ERR_FILE_TYPE`).
        """
        head = file.file.read(HEAD_SIZE)
        file.file.seek(0)
        types = settings.BAZIS_FILE_UPLOAD_ANONYMOUS_TYPES
        if (content_type := signature_type(head, types)) is None:
            raise JsonApiBazisException(
                JsonApiBazisError(
                    detail=_('The file is not of the types %(types)s')
                    % {'types': ', '.join(types)},
                    loc=('body', 'file'),
                    code='ERR_FILE_TYPE',
                    title=_('File type not allowed'),
                    status=422,
                ),
                status=422,
            )
        stem = os.path.splitext(os.path.basename(name or file.filename or ''))[0] or 'file'
        return f'{stem}.{SIGNATURES[content_type][0]}'

    @classmethod
    def restrict_queryset(
        cls, qs: QuerySet, access_action: AccessAction, user=None, link: bool = False, **kwargs
    ) -> QuerySet:
        """
        The files the user uploaded and, to view, the files of the objects he sees through
        a route set that declares them in `files_visible` (`files_visible_q`). A
        relationship links only his own files (`link=True`, passed by the core when it
        checks the linked objects: a visible file of another user is 422
        `ERR_RELATION_LINK`). Without a user (a route without a user, e.g. called by the
        core for the relationships of another route) the authenticated user of the request
        (`UserMixin.authenticated_user`); none for an anonymous user.
        """
        if (user := UserMixin.authenticated_user(user)) is None:
            return qs.none()
        qs = super().restrict_queryset(qs, access_action, user=user, link=link, **kwargs)
        own = Q(author=user)
        if link or access_action != CrudAccessAction.VIEW:
            return qs.filter(own)
        if (visible := files_visible_q(qs.model, user)) is None:
            return qs.filter(own)
        return qs.filter(own | visible)

    @http_get(
        '/{item_id}/download/',
        kind=RouteKind.OTHER,
        response_class=StreamingResponse,
        responses={200: {'content': {'application/octet-stream': {}}, 'description': 'The file'}},
    )
    def action_download(self, item_id: str, **kwargs):
        """
        The content of a file the user sees (`get_queryset`: his own files and the visible
        ones), read from the storage: 404 for another file or a file missing from the
        storage. Served as the media host serves it (`storages`): a raster image inline,
        any other file as a download named after the file, with `nosniff` and a sandbox.
        """
        item = self.set_item(item_id)
        try:
            stream = item.file.open('rb')
        except (OSError, ValueError):
            raise HTTPException(status_code=404, detail=_('Item not found')) from None

        content_type = served_content_type(item.file.name)
        name = item.name or item.file.name.rsplit('/', 1)[-1]

        def chunks():
            try:
                yield from stream.chunks(DOWNLOAD_CHUNK_SIZE)
            finally:
                stream.close()

        return StreamingResponse(
            chunks(),
            media_type=content_type,
            headers={
                'Content-Disposition': content_disposition_header(
                    content_type not in INLINE_CONTENT_TYPES, name
                ),
                'X-Content-Type-Options': 'nosniff',
                'Content-Security-Policy': 'sandbox',
                'Cache-Control': 'private, no-store',
            },
        )

    def get_queryset(self):
        """
        The files the user sees (`restrict_queryset` for VIEW).
        """
        return self.restrict_queryset(
            super().get_queryset(), CrudAccessAction.VIEW, user=self.inject.user
        )
