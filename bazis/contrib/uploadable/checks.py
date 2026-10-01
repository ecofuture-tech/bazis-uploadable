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

from django.core.checks import Warning, register


@register()
def check_routes_bundled(app_configs, **kwargs):
    """
    The bundled `FileUploadRouteSet` has no access control: anyone can upload, list, change
    and delete the files. Runs when the application is loaded (`manage.py bazis_doctor`).
    """
    from bazis.core.introspect import loaded_app, route_sets

    if (app := loaded_app()) is None:
        return []

    from .routes import FileUploadRouteSet

    if FileUploadRouteSet not in route_sets(app):
        return []
    return [
        Warning(
            'The route bazis.contrib.uploadable.routes.FileUploadRouteSet is registered: '
            'anyone can upload, list, change and delete the uploaded files.',
            hint=(
                'Register a subclass of FileUploadRouteSet that requires a user or '
                'permissions instead of bazis.contrib.uploadable.router.'
            ),
            obj=FileUploadRouteSet,
            id='uploadable.W001',
        )
    ]
