from django.test import TestCase
from django.urls import reverse

from cabinet.models import AnalystFollow, User
from notifications.models import Notification, NotificationSectionState


class ProfileFollowerNotificationTests(TestCase):
    def test_followers_tab_marks_new_follower_row_and_clears_badge(self):
        analyst = User.objects.create_user(
            username="profile-analyst",
            password="test-password",
            role=User.Role.ANALYST,
        )
        follower = User.objects.create_user(
            username="profile-follower",
            password="test-password",
        )
        AnalystFollow.objects.create(
            analyst=analyst,
            follower=follower,
        )
        notification = Notification.objects.get(
            recipient=analyst,
            actor=follower,
            kind=Notification.Kind.NEW_FOLLOWER,
        )
        self.client.force_login(analyst)

        response = self.client.get(f"{reverse('cabinet:profile')}?tab=followers")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "profile-follower")
        self.assertContains(response, "profile-row-new-dot")
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)
        self.assertFalse(
            NotificationSectionState.objects.filter(
                user=analyst,
                section=NotificationSectionState.Section.FOLLOWERS,
                unread_count__gt=0,
            ).exists()
        )
