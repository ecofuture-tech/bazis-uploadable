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
The types of the anonymous uploads, recognized by the first bytes of the content (its
signature), not by the name or the type the client declared.
"""

#: the bytes of the content a type is recognized by
HEAD_SIZE = 12

#: the types an anonymous upload may have: the extension it is stored with and the test of
#: the first bytes of its content
SIGNATURES = {
    'image/jpeg': ('jpg', lambda head: head.startswith(b'\xff\xd8\xff')),
    'image/png': ('png', lambda head: head.startswith(b'\x89PNG\r\n\x1a\n')),
    'image/webp': ('webp', lambda head: head[:4] == b'RIFF' and head[8:12] == b'WEBP'),
}


def signature_type(head: bytes, types) -> str | None:
    """
    The type among `types` (of `SIGNATURES`) whose signature `head`, the first bytes of a
    content, has, else None.
    """
    return next((it for it in types if SIGNATURES[it][1](head)), None)
