from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User, UserVipSubscription
from game.models import Match

from tournaments.models import Tournament, TournamentParticipant, TournamentResult

from .forms import AdminNotificationCampaignForm
from .models import (
    AdminNotificationCampaign,
    MatchWatch,
    Notification,
    TelegramAccount,
)
from .services import (
    campaign_recipients_queryset,
    create_notification,
    send_admin_notification_campaign,
    get_preferences,
)
from .telegram_bot import (
    TelegramAlreadyLinkedError,
    consume_link_payload,
    create_link_payload,
    disconnect_telegram,
)


class NotificationServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="reader-notifications",
            email="reader@example.com",
            password="test-password-123",
        )

    def test_event_key_is_idempotent(self):
        preferences = get_preferences(self.user)
        preferences.match_reminder = True
        preferences.save(update_fields=["match_reminder", "updated_at"])

        first = create_notification(
            recipient=self.user,
            kind=Notification.Kind.MATCH_REMINDER,
            title="Скоро матч",
            event_key="test:event:1",
        )
        second = create_notification(
            recipient=self.user,
            kind=Notification.Kind.MATCH_REMINDER,
            title="Скоро матч",
            event_key="test:event:1",
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Notification.objects.count(), 1)

    def test_disabled_category_does_not_create_notification(self):
        preferences = get_preferences(self.user)
        preferences.achievement = False
        preferences.save(update_fields=["achievement", "updated_at"])

        notification = create_notification(
            recipient=self.user,
            kind=Notification.Kind.ACHIEVEMENT,
            title="Достижение",
            event_key="test:achievement:1",
        )

        self.assertIsNone(notification)
        self.assertFalse(Notification.objects.exists())


    def test_disabled_bonus_referral_category_does_not_create_notification(self):
        preferences = get_preferences(self.user)
        preferences.bonus_referral = False
        preferences.save(update_fields=["bonus_referral", "updated_at"])

        notification = create_notification(
            recipient=self.user,
            kind=Notification.Kind.BONUS_REFERRAL,
            title="Реферальный бонус",
            event_key="test:bonus-referral:1",
        )

        self.assertIsNone(notification)
        self.assertFalse(
            Notification.objects.filter(
                event_key="test:bonus-referral:1",
            ).exists()
        )

    def test_disabled_bonus_daily_task_category_does_not_create_notification(self):
        preferences = get_preferences(self.user)
        preferences.bonus_daily_task = False
        preferences.save(update_fields=["bonus_daily_task", "updated_at"])

        notification = create_notification(
            recipient=self.user,
            kind=Notification.Kind.BONUS_DAILY_TASK,
            title="Награда за задание",
            event_key="test:bonus-daily-task:1",
        )

        self.assertIsNone(notification)
        self.assertFalse(
            Notification.objects.filter(
                event_key="test:bonus-daily-task:1",
            ).exists()
        )


class TelegramLinkingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="telegram-reader",
            password="test-password-123",
        )

    def test_deep_link_connects_telegram_and_is_single_use(self):
        payload = create_link_payload(self.user)
        linked_user = consume_link_payload(
            payload,
            chat_id="123456789",
            telegram_username="cappers_user",
        )

        self.assertEqual(linked_user, self.user)
        preferences = get_preferences(self.user)
        telegram_account = TelegramAccount.objects.get(user=self.user)
        self.assertEqual(telegram_account.chat_id, "123456789")
        self.assertEqual(telegram_account.username, "cappers_user")
        self.assertEqual(preferences.telegram_chat_id, "123456789")
        self.assertEqual(preferences.telegram_username, "cappers_user")
        self.assertTrue(preferences.telegram_enabled)
        self.assertIsNotNone(preferences.telegram_connected_at)

        repeated = consume_link_payload(
            payload,
            chat_id="123456789",
            telegram_username="cappers_user",
        )
        self.assertIsNone(repeated)

    def test_same_chat_cannot_move_to_new_cappers_account(self):
        other = User.objects.create_user(
            username="telegram-reader-two",
            password="test-password-123",
        )
        first_payload = create_link_payload(self.user)
        consume_link_payload(first_payload, chat_id="555", telegram_username="same_chat")

        second_payload = create_link_payload(other)
        with self.assertRaises(TelegramAlreadyLinkedError) as error:
            consume_link_payload(
                second_payload,
                chat_id="555",
                telegram_username="same_chat",
            )

        self.assertEqual(error.exception.user, self.user)
        first_preferences = get_preferences(self.user)
        second_preferences = get_preferences(other)
        self.assertEqual(TelegramAccount.objects.get(user=self.user).chat_id, "555")
        self.assertFalse(TelegramAccount.objects.filter(user=other).exists())
        self.assertEqual(first_preferences.telegram_chat_id, "555")
        self.assertTrue(first_preferences.telegram_enabled)
        self.assertEqual(second_preferences.telegram_chat_id, "")
        self.assertFalse(second_preferences.telegram_enabled)

    def test_disconnect_clears_telegram_delivery(self):
        payload = create_link_payload(self.user)
        consume_link_payload(payload, chat_id="777", telegram_username="reader")
        disconnect_telegram(self.user)

        preferences = get_preferences(self.user)
        self.assertFalse(TelegramAccount.objects.filter(user=self.user).exists())
        self.assertEqual(preferences.telegram_chat_id, "")
        self.assertEqual(preferences.telegram_username, "")
        self.assertFalse(preferences.telegram_enabled)
        self.assertIsNone(preferences.telegram_connected_at)


class NotificationViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="reader-center",
            password="test-password-123",
        )
        self.client.force_login(self.user)
        self.notification = Notification.objects.create(
            recipient=self.user,
            kind=Notification.Kind.NEW_PREDICTION,
            title="Новый прогноз",
            event_key="view:test:1",
        )

    def test_summary_and_mark_read(self):
        summary = self.client.get(reverse("notifications:summary"))
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["unread_count"], 1)

        response = self.client.post(
            reverse("notifications:mark_read", args=[self.notification.id])
        )
        self.assertEqual(response.status_code, 200)
        self.notification.refresh_from_db()
        self.assertTrue(self.notification.is_read)
        self.assertIsNotNone(self.notification.read_at)

    def test_match_watch_toggle(self):
        match = Match.objects.create(
            external_id=991001,
            sync_scope=Match.SyncScope.PREMATCH,
        )
        url = reverse("notifications:match_watch", args=[match.id])

        first = self.client.post(url)
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()["watching"])
        self.assertTrue(MatchWatch.objects.filter(user=self.user, match=match).exists())

        second = self.client.post(url)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json()["watching"])
        self.assertFalse(MatchWatch.objects.filter(user=self.user, match=match).exists())

    def test_update_preferences_saves_bonus_notification_fields(self):
        response = self.client.post(
            reverse("notifications:preferences"),
            {
                "in_app_enabled": "on",
                "bonus_daily_task": "on",
                "bonus_streak": "on",
                "bonus_level": "on",
                "bonus_roulette": "on",
                "bonus_referral": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        preferences = get_preferences(self.user)
        self.assertTrue(preferences.bonus_daily_task)
        self.assertTrue(preferences.bonus_streak)
        self.assertTrue(preferences.bonus_level)
        self.assertTrue(preferences.bonus_roulette)
        self.assertTrue(preferences.bonus_referral)

        center_response = self.client.get(reverse("notifications:center"))
        self.assertContains(center_response, 'name="bonus_daily_task"')
        self.assertContains(center_response, 'name="bonus_streak"')
        self.assertContains(center_response, 'name="bonus_level"')
        self.assertContains(center_response, 'name="bonus_roulette"')
        self.assertContains(center_response, 'name="bonus_referral"')

    def test_telegram_disconnect_view(self):
        preferences = get_preferences(self.user)
        preferences.telegram_chat_id = "999"
        preferences.telegram_enabled = True
        preferences.save(update_fields=["telegram_chat_id", "telegram_enabled", "updated_at"])

        response = self.client.post(reverse("notifications:telegram_disconnect"))
        self.assertEqual(response.status_code, 302)

        preferences.refresh_from_db()
        self.assertFalse(TelegramAccount.objects.filter(user=self.user).exists())
        self.assertEqual(preferences.telegram_chat_id, "")
        self.assertFalse(preferences.telegram_enabled)



class AdminNotificationCampaignRecipientTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.creator = User.objects.create_user(
            username="campaign-admin",
            password="test-password",
            is_staff=True,
            is_active=False,
        )
        self.reader = User.objects.create_user(
            username="campaign-reader",
            password="test-password",
            role=User.Role.READER,
        )
        self.capper = User.objects.create_user(
            username="campaign-capper",
            password="test-password",
            role=User.Role.ANALYST,
        )
        self.vip_reader = User.objects.create_user(
            username="campaign-vip-reader",
            password="test-password",
            role=User.Role.READER,
        )
        self.inactive_reader = User.objects.create_user(
            username="campaign-inactive-reader",
            password="test-password",
            role=User.Role.READER,
        )
        User.objects.filter(pk=self.inactive_reader.pk).update(
            last_login=self.now - timedelta(days=40)
        )
        self.inactive_reader.refresh_from_db()

        UserVipSubscription.objects.create(
            user=self.vip_reader,
            starts_at=self.now - timedelta(days=1),
            ends_at=self.now + timedelta(days=30),
            duration_days=31,
            source=UserVipSubscription.Source.ADMIN,
            is_active=True,
        )

        self.tournament = Tournament.objects.create(
            title="Campaign tournament",
            starts_at=self.now - timedelta(days=3),
            ends_at=self.now - timedelta(days=1),
            status=Tournament.Status.PUBLISHED,
        )
        self.other_tournament = Tournament.objects.create(
            title="Other campaign tournament",
            starts_at=self.now - timedelta(days=6),
            ends_at=self.now - timedelta(days=4),
            status=Tournament.Status.PUBLISHED,
        )
        self.winner_participation = TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=self.capper,
        )
        self.other_participation = TournamentParticipant.objects.create(
            tournament=self.other_tournament,
            user=self.capper,
        )
        TournamentResult.objects.create(
            tournament=self.other_tournament,
            participant=self.other_participation,
            rank=1,
        )

    def campaign(self, audience, **kwargs):
        return AdminNotificationCampaign.objects.create(
            audience=audience,
            title="Тестовая рассылка",
            message="Текст рассылки",
            created_by=self.creator,
            **kwargs,
        )

    def recipient_ids(self, campaign):
        return set(
            campaign_recipients_queryset(campaign).values_list(
                "id",
                flat=True,
            )
        )

    def test_campaign_recipients_for_basic_audiences(self):
        all_active = {
            self.reader.pk,
            self.capper.pk,
            self.vip_reader.pk,
            self.inactive_reader.pk,
        }
        self.assertEqual(
            self.recipient_ids(
                self.campaign(AdminNotificationCampaign.Audience.ALL_USERS)
            ),
            all_active,
        )
        self.assertEqual(
            self.recipient_ids(
                self.campaign(AdminNotificationCampaign.Audience.READERS)
            ),
            {
                self.reader.pk,
                self.vip_reader.pk,
                self.inactive_reader.pk,
            },
        )
        self.assertEqual(
            self.recipient_ids(
                self.campaign(AdminNotificationCampaign.Audience.CAPPERS)
            ),
            {self.capper.pk},
        )
        self.assertEqual(
            self.recipient_ids(
                self.campaign(
                    AdminNotificationCampaign.Audience.READERS_AND_CAPPERS
                )
            ),
            all_active,
        )

    def test_campaign_recipients_for_vip_and_inactive_users(self):
        self.assertEqual(
            self.recipient_ids(
                self.campaign(AdminNotificationCampaign.Audience.VIP_USERS)
            ),
            {self.vip_reader.pk},
        )
        self.assertEqual(
            self.recipient_ids(
                self.campaign(
                    AdminNotificationCampaign.Audience.INACTIVE_USERS,
                    inactive_days=30,
                )
            ),
            {self.inactive_reader.pk},
        )

    def test_campaign_recipients_for_tournament_audiences(self):
        self.assertEqual(
            self.recipient_ids(
                self.campaign(
                    AdminNotificationCampaign.Audience.TOURNAMENT_WINNERS
                )
            ),
            {self.capper.pk},
        )
        self.assertEqual(
            self.recipient_ids(
                self.campaign(
                    AdminNotificationCampaign.Audience.TOURNAMENT_PARTICIPANTS,
                    tournament=self.tournament,
                )
            ),
            {self.capper.pk},
        )

    def test_admin_campaign_bulk_send_is_idempotent(self):
        campaign = self.campaign(
            AdminNotificationCampaign.Audience.READERS,
            image="notifications/campaigns/2026/09/campaign.jpg",
            url="/cabinet/bonuses/",
        )

        count, was_sent = send_admin_notification_campaign(campaign)

        self.assertTrue(was_sent)
        self.assertEqual(count, 3)
        campaign.refresh_from_db()
        self.assertIsNotNone(campaign.sent_at)
        self.assertEqual(campaign.recipients_count, 3)

        notifications = Notification.objects.filter(
            kind=Notification.Kind.ADMIN_CAMPAIGN,
        ).order_by("recipient_id")
        self.assertEqual(notifications.count(), 3)
        for notification in notifications:
            self.assertEqual(
                notification.event_key,
                f"admin-campaign:{campaign.pk}:{notification.recipient_id}",
            )
            self.assertEqual(notification.title, campaign.title)
            self.assertEqual(notification.message, campaign.message)
            self.assertEqual(notification.url, campaign.url)
            self.assertEqual(
                notification.meta["image_url"],
                campaign.image.url,
            )

        second_count, second_was_sent = send_admin_notification_campaign(
            campaign
        )
        self.assertFalse(second_was_sent)
        self.assertEqual(second_count, 3)
        self.assertEqual(
            Notification.objects.filter(
                kind=Notification.Kind.ADMIN_CAMPAIGN,
            ).count(),
            3,
        )

    @override_settings(
        STORAGES={
            "default": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
            },
            "staticfiles": {
                "BACKEND": (
                    "django.contrib.staticfiles.storage.StaticFilesStorage"
                ),
            },
        }
    )
    def test_admin_campaign_image_is_exposed_in_center_and_realtime_summary(self):
        campaign = self.campaign(
            AdminNotificationCampaign.Audience.READERS,
            image="notifications/campaigns/2026/09/campaign.jpg",
        )
        send_admin_notification_campaign(campaign)
        self.client.force_login(self.reader)

        center_response = self.client.get(reverse("notifications:center"))
        self.assertEqual(center_response.status_code, 200)
        self.assertContains(center_response, 'class="notification-image"')
        self.assertContains(center_response, campaign.image.url)

        latest_id = (
            Notification.objects.filter(recipient=self.reader)
            .order_by("-id")
            .values_list("id", flat=True)
            .first()
        )
        summary_response = self.client.get(
            reverse("notifications:summary"),
            {"after_id": latest_id - 1},
        )
        self.assertEqual(summary_response.status_code, 200)
        payload = summary_response.json()
        self.assertEqual(
            payload["notifications"][0]["image_url"],
            campaign.image.url,
        )

    def test_campaign_form_requires_dependent_filters(self):
        inactive_form = AdminNotificationCampaignForm(
            data={
                "audience": AdminNotificationCampaign.Audience.INACTIVE_USERS,
                "title": "Inactive",
                "message": "Message",
            }
        )
        self.assertFalse(inactive_form.is_valid())
        self.assertIn("inactive_days", inactive_form.errors)

        tournament_form = AdminNotificationCampaignForm(
            data={
                "audience": (
                    AdminNotificationCampaign.Audience.TOURNAMENT_PARTICIPANTS
                ),
                "title": "Tournament",
                "message": "Message",
            }
        )
        self.assertFalse(tournament_form.is_valid())
        self.assertIn("tournament", tournament_form.errors)
