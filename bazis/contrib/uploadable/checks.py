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

"""
Django system checks of bazis-uploadable (see `manage.py bazis_doctor`).
"""

from django.core.checks import Error, Warning, register


def files_visible_errors(route_cls) -> list[str]:
    """
    The problems of `files_visible` of a route class: it is a tuple of the names of the
    relations of the model of the route to a model of uploaded files whose default route is
    `FileUploadRouteSet` or a subclass (its `restrict_queryset` makes them visible).
    """
    from .models_abstract import FileUploadAbstract
    from .routes import FileUploadRouteSet, files_visible_field, files_visible_problem

    if problem := files_visible_problem(route_cls):
        return [problem]
    errors = []
    for name in route_cls.files_visible:
        files_model = files_visible_field(route_cls.model, name)
        # not a model of files (e.g. a relation to ContentType, which has no default route)
        is_files = isinstance(files_model, type) and issubclass(files_model, FileUploadAbstract)
        default_route = files_model.get_default_route() if is_files else None
        if not (
            is_files
            and isinstance(default_route, type)
            and issubclass(default_route, FileUploadRouteSet)
        ):
            errors.append(
                f'{name!r} is not a relation of {route_cls.model._meta.label} to a model of '
                'uploaded files whose default route is FileUploadRouteSet'
            )
    return errors


@register()
def check_files_visible(app_configs, **kwargs):
    """
    `files_visible` of a route set names the relations of its model to the uploaded files
    that the users who see its objects read: a name that is not such a relation shows no
    file, nor does a declaration on an abstract route class (`uploadable.E001`). Runs when
    the application is loaded.
    """
    from bazis.core.introspect import loaded_app

    if loaded_app() is None:
        return []

    from .routes import files_visible_declarations

    messages = []
    for route_cls in files_visible_declarations():
        for error in files_visible_errors(route_cls):
            messages.append(
                Error(
                    f'{route_cls.__module__}.{route_cls.__qualname__}.files_visible {error}.',
                    hint='Declare files_visible = (<field>, ...): the foreign keys or '
                    'many-to-many fields of the model to the uploaded files.',
                    obj=route_cls,
                    id='uploadable.E001',
                )
            )
    return messages


@register()
def check_anonymous_uploads(app_configs, **kwargs):
    """
    Anonymous uploads (`BAZIS_FILE_UPLOAD_ANONYMOUS`) need a size limit: without
    `BAZIS_FILE_UPLOAD_MAX_SIZE` anonymous users upload nothing (`uploadable.E002`).
    """
    from django.conf import settings

    if settings.BAZIS_FILE_UPLOAD_ANONYMOUS and not settings.BAZIS_FILE_UPLOAD_MAX_SIZE:
        return [
            Error(
                'BAZIS_FILE_UPLOAD_ANONYMOUS is on without BAZIS_FILE_UPLOAD_MAX_SIZE: '
                'anonymous users upload nothing.',
                hint='Set BS_BAZIS_FILE_UPLOAD_MAX_SIZE (bytes) and limit the request body '
                'size on the reverse proxy.',
                id='uploadable.E002',
            )
        ]
    return []


@register()
def check_public_files(app_configs, **kwargs):
    """
    A route set that serves anonymous users (`route_serves_anonymous`) and declares
    `files_visible` without restricting its objects (no `restrict_queryset` of its own)
    makes the files of all its objects public, guests read them (`uploadable.W003`),
    unless it says that its objects are public (`permit_public = True`: the convention of
    bazis-permit, `permit.W002`, read by its name without depending on bazis-permit). Runs
    when the application is loaded.
    """
    from bazis.core.introspect import loaded_app

    if loaded_app() is None:
        return []

    from bazis.core.routes_abstract.jsonapi.mixins import restrict_queryset_override

    from .routes import files_visible_declarations, files_visible_problem, route_serves_anonymous

    messages = []
    for route_cls in files_visible_declarations():
        if (
            files_visible_problem(route_cls)
            or not route_serves_anonymous(route_cls)
            or restrict_queryset_override(route_cls) is not None
            or getattr(route_cls, 'permit_public', False) is True
        ):
            continue
        messages.append(
            Warning(
                f'{route_cls.__module__}.{route_cls.__qualname__} serves anonymous users and '
                'does not restrict its objects: guests read the files of files_visible of '
                'all its objects.',
                hint='Override restrict_queryset to return the objects a guest may see (none '
                'for an anonymous user if they are private), require a user, or declare '
                'permit_public = True if all the objects and their files are public.',
                obj=route_cls,
                id='uploadable.W003',
            )
        )
    return messages
