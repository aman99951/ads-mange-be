from django.contrib import admin
from django import forms
from django.contrib.auth.models import User
from .models import Client, Manager, Developer


class ManagerForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, required=False,
                               help_text='Required when creating a new manager')

    class Meta:
        model = Manager
        exclude = ['user']

    def save(self, commit=True):
        instance = super().save(commit=False)
        password = self.cleaned_data.get('password')

        if instance.pk:
            instance.user.first_name = instance.name
            instance.user.username = instance.mobile
            if password:
                instance.user.set_password(password)
            if commit:
                instance.user.save()
                instance.save()
        else:
            user = User.objects.create_user(
                username=instance.mobile,
                password=password or 'changeme123',
                first_name=instance.name,
                is_staff=True,
            )
            instance.user = user
            if commit:
                instance.save()

        return instance

    def clean_mobile(self):
        mobile = self.cleaned_data['mobile']
        qs = Manager.objects.exclude(pk=self.instance.pk if self.instance.pk else None)
        if qs.filter(mobile=mobile).exists():
            raise forms.ValidationError('Mobile already exists')
        return mobile


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ['mobile', 'name', 'created_at']
    search_fields = ['mobile', 'name']


@admin.register(Manager)
class ManagerAdmin(admin.ModelAdmin):
    form = ManagerForm
    list_display = ['name', 'mobile', 'user']
    search_fields = ['name', 'mobile']


@admin.register(Developer)
class DeveloperAdmin(admin.ModelAdmin):
    list_display = ['company_name', 'api_key', 'is_active', 'created_at']
    search_fields = ['company_name', 'user__email']
    readonly_fields = ['api_key']
