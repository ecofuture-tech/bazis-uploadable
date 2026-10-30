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

from bazis.contrib.author.checks import check_routes_author
from bazis.core.introspect import read_manifest, validate_manifest


def test_manifest_is_valid():
    assert validate_manifest('bazis.contrib.uploadable') == []


def test_bundled_route_does_not_let_a_client_set_the_author(sample_app):
    # the sample project registers bazis.contrib.uploadable.router
    assert check_routes_author(None) == []


def test_manifest_names_the_checks():
    pitfalls = read_manifest('bazis.contrib.uploadable')['pitfalls']
    checks = {it['check'] for it in pitfalls if 'check' in it}
    assert checks == {'uploadable.E001', 'uploadable.E002', 'uploadable.W003'}
