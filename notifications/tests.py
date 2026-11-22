from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Message, MessageThread, NotificationLog


class UnifiedInboxTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='inbox_user',
            password='pass1234',
        )
        self.client.force_login(self.user)
        NotificationLog.objects.create(
            recipient_number='+256700000000',
            message_type='debt_reminder',
            message_body='Notification inbox test',
            status='sent',
        )
        self.thread = MessageThread.objects.create(
            subject='Inbox message test',
            created_by=self.user,
        )
        self.thread.participants.add(self.user)
        Message.objects.create(
            thread=self.thread,
            sender=self.user,
            body='A message in the unified inbox',
        )

    def test_notification_page_has_shared_inbox_tabs_and_log(self):
        response = self.client.get(reverse('notifications:list'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'notifications/inbox.html')
        self.assertEqual(response.context['active_tab'], 'notifications')
        self.assertContains(response, 'Notification inbox test')
        self.assertContains(response, '?tab=messages')
        self.assertContains(response, '?tab=notifications')
        self.assertEqual(response.content.decode().count('title="Inbox"'), 1)

    def test_messages_route_opens_the_same_inbox_with_threads(self):
        response = self.client.get(reverse('notifications:message_threads'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'notifications/inbox.html')
        self.assertEqual(response.context['active_tab'], 'messages')
        self.assertContains(response, self.thread.subject)
        self.assertContains(response, 'New message')
        self.assertContains(response, '?tab=notifications')
