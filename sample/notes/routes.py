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
from django.db.models import Q

from bazis.contrib.users.models_abstract import UserMixin
from bazis.contrib.users.routes_abstract import UserRequiredRouteBase, UserRouteBase
from bazis.core.routes_abstract.jsonapi import RestrictedQsRouteMixin
from bazis.core.schemas import CrudAccessAction


class NoteRouteSet(UserRequiredRouteBase):
    """
    The notes: every user who is logged in reads and changes them all. A user attaches
    only a file he uploaded and sees in `included` only his files: the core checks the
    attachment against `restrict_queryset` of `FileUploadRouteSet`, the route set needs no
    checks of its own.
    """

    model = apps.get_model('notes.Note')


class MembersRouteBase(RestrictedQsRouteMixin, UserRequiredRouteBase):
    """
    The objects of a model a user sees: those that `members_q` gives him.
    """

    abstract = True

    @classmethod
    def members_q(cls, user) -> Q:
        raise NotImplementedError

    @classmethod
    def restrict_queryset(cls, qs, access_action, user=None, **kwargs):
        if (user := UserMixin.authenticated_user(user)) is None:
            return qs.none()
        qs = super().restrict_queryset(qs, access_action, user=user, **kwargs)
        return qs.filter(cls.members_q(user)).distinct()

    def get_queryset(self):
        return self.restrict_queryset(
            super().get_queryset(), CrudAccessAction.VIEW, user=self.inject.user
        )


class MemoRouteSet(MembersRouteBase):
    """
    The memos of their owner and their readers: whoever sees a memo reads its attachment,
    not its cover. A user attaches only a file he uploaded.
    """

    model = apps.get_model('notes.Memo')
    files_visible = ('attachment',)

    @classmethod
    def members_q(cls, user) -> Q:
        return Q(owner=user) | Q(readers=user)


class BoardRouteSet(MembersRouteBase):
    """
    The boards of their members: a member reads all the files of a board.
    """

    model = apps.get_model('notes.Board')
    files_visible = ('files',)

    @classmethod
    def members_q(cls, user) -> Q:
        return Q(members=user)


class PosterRouteSet(RestrictedQsRouteMixin, UserRouteBase):
    """
    The posters of a public catalog, read by anyone (the user is optional): a guest reads
    the published posters and their photo (`files_visible`: bazis-uploadable serves the
    files of the objects a route set that serves guests shows them), a user also the
    drafts. Its `restrict_queryset` is what a guest sees (without it every poster and its
    photo would be public, `uploadable.W003`). Only read: the server writes the posters.
    """

    model = apps.get_model('notes.Poster')
    actions = ['action_list', 'action_retrieve']
    files_visible = ('photo',)

    @classmethod
    def restrict_queryset(cls, qs, access_action, user=None, **kwargs):
        qs = super().restrict_queryset(qs, access_action, user=user, **kwargs)
        if UserMixin.authenticated_user(user) is None:
            return qs.filter(published=True)
        return qs

    def get_queryset(self):
        return self.restrict_queryset(
            super().get_queryset(), CrudAccessAction.VIEW, user=self.inject.user
        )
