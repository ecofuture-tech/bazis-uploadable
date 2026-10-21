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
The types of the bodies of the actions that take uploaded files.
"""

from typing import Annotated

from pydantic import Field


#: the id of an uploaded file (`uploadable.FileUpload`) in the body of an action: the id the
#: upload answered, for a guest the token of his upload (`anonymous_token`). The
#: `x-relation` of its JSON schema tells the clients to upload it (`list[UploadedFileId]`
#: has it in `items`); the action takes the files of a guest with
#: `FileUpload.objects.anonymous(tokens)`
UploadedFileId = Annotated[str, Field(json_schema_extra={'x-relation': 'uploadable.file_upload'})]
