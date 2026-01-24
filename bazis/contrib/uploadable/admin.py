from django.contrib import admin

from . import models


@admin.register(models.FileUpload)
class FileUploadAdmin(admin.ModelAdmin):
    list_display = ('name',)
    list_filter = ('extension',)
    search_fields = ('name', 'extension')

