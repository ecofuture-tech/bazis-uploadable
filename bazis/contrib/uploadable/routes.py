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

from fastapi import Form, Request

from bazis.core.routes_abstract.initial import http_post
from bazis.core.routes_abstract.jsonapi import (
    JsonapiRouteBase,
    api_action_init,
    api_action_jsonapi_init,
    api_action_response_init,
    item_data_typing,
    meta_fields_addition,
)
from bazis.core.schemas import CrudApiAction, SchemaFields
from bazis.core.utils.django_types import UploadFileDjango


class FileUploadRouteSet(JsonapiRouteBase):
    model = apps.get_model('uploadable.FileUpload')

    fields = {
        None: SchemaFields(
            include={
                'size': None,
                'extension': None,
            }
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
        id: str | None = Form(None),
        **kwargs,
    ):
        if not isinstance(file, UploadFileDjango):
            file.__class__ = UploadFileDjango

        request._json = {
            'data': {
                'id': id,
                'type': self.model.get_resource_label(),
                'attributes': {
                    'name': name,
                    'file': file,
                }
            },
        }

        item_data = self.schema_defaults[CrudApiAction.CREATE].model_validate(request._json)

        return super().action_create.func(self, request, item_data)
