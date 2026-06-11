from django import forms
from django.contrib.auth import get_user_model

User = get_user_model()

class NewMessageForm(forms.Form):
    recipients = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        widget=forms.SelectMultiple(attrs={'class': 'form-ctrl recipient-select', 'style': 'width:100%'}),
        help_text='Choose one or more staff recipients.',
    )
    subject = forms.CharField(
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-ctrl', 'placeholder': 'Optional subject'}),
    )
    body = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-ctrl', 'rows': 5, 'placeholder': 'Write your message here...'}),
        label='Message',
    )
    attachment = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-ctrl'}),
        label='Attachment',
        help_text='Optional file attachment (PDF, image, document, etc.).',
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields['recipients'].queryset = User.objects.filter(is_active_staff=True).exclude(pk=user.pk).order_by('first_name', 'last_name')
        else:
            self.fields['recipients'].queryset = User.objects.filter(is_active_staff=True).order_by('first_name', 'last_name')

class ReplyMessageForm(forms.Form):
    body = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-ctrl', 'rows': 4, 'placeholder': 'Write your reply...'}),
        label='Reply',
    )
    attachment = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-ctrl'}),
        label='Attachment',
        help_text='Attach an optional file to your reply.',
    )
