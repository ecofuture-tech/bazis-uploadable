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

from django.core.checks import Error, register


def files_visible_errors(route_cls) -> list[str]:
    """
    The problems of `files_visible` of a route class: it is a tuple of the names of the
    relations of the model of the route to a model of uploaded files whose default route is
    `FileUploadRouteSet` or a subclass (its `restrict_queryset` makes them visible).
    """
    from .models_abstract import FileUploadAbstract
    from .routes import FileUploadRouteSet, files_visible_field

    names = route_cls.files_visible
    if getattr(route_cls, 'abstract', False) or getattr(route_cls, 'model', None) is None:
        return ['is declared on an abstract route class (or one without a model): it is not inherited']
    if not isinstance(names, tuple | list) or not all(isinstance(it, str) for it in names):
        return [f'is {names!r}, not a tuple of field names']
    errors = []
    for name in names:
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
