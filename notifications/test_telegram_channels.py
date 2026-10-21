import io
import json
import urllib.error
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystProfile, User
from game.models import Match, Prediction, PredictionCoupon, Sport

from .models import TelegramAccount, TelegramChannel, TelegramChannelPost
from .tasks import dispatch_recent_coupon_events, post_to_telegram_channel
from .telegram_bot import TelegramApiError, api_call, api_upload
from .telegram_channels import publish_channel_post, sync_channel_membership

TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
PREDICTION = TelegramChannelPost.Kind.PREDICTION
RESULT = TelegramChannelPost.Kind.RESULT


def membership(status="administrator", *, adder_id=5001, can_post=True):
    return {
        "chat": {"id": -100777, "type": "channel", "title": "Ставки Вадима", "username": "vadim_bets"},
        "from": {"id": adder_id},
        "new_chat_member": {"status": status, "can_post_messages": can_post},
    }


@override_settings(STORAGES=TEST_STORAGES, SITE_BASE_URL="https://capper-hub.com", TG_BOT_TOKEN="123456:TEST")
class TelegramChannelTests(TestCase):
    def setUp(self):
        cache.clear()
        self.capper = User.objects.create_user(username="vadim", password="secret", role=User.Role.ANALYST)
        self.profile, _ = AnalystProfile.objects.get_or_create(user=self.capper)
        TelegramAccount.objects.create(user=self.capper, chat_id="5001", username="vadim_tg")
        sport, _ = Sport.objects.get_or_create(code="football", defaults={"name": "Football", "name_ru": "Футбол"})
        self.match = Match.objects.create(
            external_id=881001,
            sport=sport,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(days=1),
            raw_data={
                "league": {"name": {"ru": "Ла Лига"}},
                "teams": {"home": {"name": {"ru": "Барселона"}}, "away": {"name": {"ru": "Жирона"}}},
            },
        )

    def _channel(self, **fields):
        return TelegramChannel.objects.create(user=self.capper, chat_id="-100777", title="Ставки Вадима", **fields)

    def _coupon(self, audience=PredictionCoupon.Audience.FREE):
        coupon = PredictionCoupon.objects.create(
            author=self.capper,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            audience=audience,
            total_stake=Decimal("500"),
            possible_payout=Decimal("975"),
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon, match=self.match, market="winner", selection="Барселона", outcome_code="1",
            coefficient=Decimal("1.95"), stake=Decimal("500"),
        )
        return coupon

    def _settle(self, coupon, state):
        coupon.state_status = state
        coupon.settled_at = timezone.now()
        coupon.save()
        self.match.score = "2-1"
        self.match.save()

    def _publish(self, coupon, kind, message_id=10):
        with patch("notifications.telegram_channels.api_upload", return_value={"message_id": message_id}) as upload:
            post = publish_channel_post(coupon.pk, kind)
        return post, upload

    # Linking ---------------------------------------------------------------------------

    def test_capper_who_adds_the_bot_gets_the_channel(self):
        with patch("notifications.telegram_channels.send_message") as notify:
            channel = sync_channel_membership(membership())

        self.assertEqual((channel.user, channel.chat_id, channel.title), (self.capper, "-100777", "Ставки Вадима"))
        self.assertTrue(channel.is_active)
        self.assertEqual(notify.call_args.args[0], "5001")

        with patch("notifications.telegram_channels.send_message") as notify:
            # Another admin of a linked channel only gives the rights back.
            self.assertEqual(sync_channel_membership(membership(adder_id=999)), channel)
            TelegramChannel.objects.all().delete()
            self.assertIsNone(sync_channel_membership(membership(adder_id=999)))
        self.assertFalse(TelegramChannel.objects.exists())
        self.assertIn("не связан с аккаунтом каппера", notify.call_args.args[1])

    def test_bot_passes_channel_membership_updates_on(self):
        from notifications.management.commands.run_telegram_bot import Command

        with patch("notifications.telegram_channels.send_message"):
            Command()._handle_update({"update_id": 1, "my_chat_member": membership()})
        self.assertEqual(TelegramChannel.objects.get().user, self.capper)

    def test_lost_rights_or_removal_stop_the_channel(self):
        self._channel()
        sync_channel_membership(membership(can_post=False))
        channel = TelegramChannel.objects.get()
        self.assertFalse(channel.is_active)
        self.assertEqual(channel.last_error, "У бота нет права публиковать сообщения")

        sync_channel_membership(membership("left"))
        self.assertEqual(TelegramChannel.objects.get().last_error, "Бот удалён из канала")

    # Posts -----------------------------------------------------------------------------

    def test_new_coupon_is_posted_once_with_card_and_site_link(self):
        self._channel()
        coupon = self._coupon()

        post, upload = self._publish(coupon, PREDICTION)

        self.assertEqual(post.message_id, 10)
        method, payload, files = upload.call_args.args
        self.assertEqual((method, payload["chat_id"], payload["parse_mode"]), ("sendPhoto", "-100777", "HTML"))
        for text in ("Новый прогноз", "Барселона — Жирона", "Ла Лига", "<b>П1</b>", "1.95"):
            self.assertIn(text, payload["caption"])
        button = payload["reply_markup"]["inline_keyboard"][0][0]
        self.assertTrue(button["url"].startswith(f"https://capper-hub.com/predictions/{coupon.pk}/?utm_source=telegram"))
        self.assertTrue(files["photo"][1].startswith(b"\x89PNG"))

        post, upload = self._publish(coupon, PREDICTION)
        self.assertIsNone(post)
        upload.assert_not_called()

    def test_paid_coupon_is_a_teaser_without_pick_and_odds(self):
        self.profile.paid_predictions_enabled = True
        self.profile.paid_predictions_price = Decimal("990")
        self.profile.save()
        channel = self._channel()
        coupon = self._coupon(PredictionCoupon.Audience.PAID)

        _post, upload = self._publish(coupon, PREDICTION)

        payload = upload.call_args.args[1]
        self.assertIn("Платный прогноз", payload["caption"])
        self.assertIn("от 990 ₽/мес", payload["caption"])
        self.assertNotIn("П1", payload["caption"])
        self.assertNotIn("1.95", payload["caption"])
        self.assertEqual(payload["reply_markup"]["inline_keyboard"][0][0]["text"], "🔓 Открыть доступ")

        channel.post_paid = False
        channel.save()
        post, upload = self._publish(self._coupon(PredictionCoupon.Audience.PAID), PREDICTION)
        self.assertIsNone(post)
        upload.assert_not_called()

    def test_result_replies_to_the_announcement_and_counts_the_channel_record(self):
        self._channel()
        announced = self._coupon()
        silent = self._coupon()
        self._publish(announced, PREDICTION, message_id=10)
        self._settle(announced, PredictionCoupon.StateStatus.WIN)
        self._settle(silent, PredictionCoupon.StateStatus.WIN)

        post, upload = self._publish(announced, RESULT, message_id=11)

        payload = upload.call_args.args[1]
        self.assertEqual(payload["reply_parameters"]["message_id"], 10)
        for text in ("✅ <b>Прогноз зашёл</b>", "2 : 1", "Итоги в канале: 1 ✅ · 0 ❌ · 0 ↩️"):
            self.assertIn(text, payload["caption"])
        self.assertEqual((post.message_id, post.state), (11, "win"))
        self.assertIsNone(self._publish(announced, RESULT)[0])
        self.assertIsNone(self._publish(silent, RESULT)[0])

        self._settle(announced, PredictionCoupon.StateStatus.LOSE)
        post, upload = self._publish(announced, RESULT, message_id=12)
        caption = upload.call_args.args[1]["caption"]
        self.assertIn("Итог пересчитан", caption)
        self.assertIn("❌ <b>Прогноз не зашёл</b>", caption)
        self.assertIn("Итоги в канале: 0 ✅ · 1 ❌ · 0 ↩️", caption)
        self.assertEqual(TelegramChannelPost.objects.filter(kind=RESULT).count(), 1)

    def test_refusal_switches_the_channel_off_and_keeps_no_post(self):
        self._channel()
        coupon = self._coupon()
        error = TelegramApiError("Forbidden: bot is not a member of the channel chat", code=403)
        with patch("notifications.telegram_channels.api_upload", side_effect=error):
            self.assertIsNone(publish_channel_post(coupon.pk, PREDICTION))

        channel = TelegramChannel.objects.get()
        self.assertFalse(channel.is_active)
        self.assertIn("bot is not a member", channel.last_error)
        self.assertFalse(TelegramChannelPost.objects.exists())

    def test_dispatch_queues_posts_for_authors_with_a_channel(self):
        self._channel()
        coupon = self._coupon()
        with patch("notifications.tasks.post_to_telegram_channel.delay") as delay:
            dispatch_recent_coupon_events()
        delay.assert_called_once_with(coupon.pk, PREDICTION)

    def test_flood_limit_retries_after_the_pause_telegram_asks(self):
        error = TelegramApiError("Too Many Requests: retry after 7", code=429, retry_after=7)
        with patch("notifications.tasks.publish_channel_post", side_effect=error), \
                patch.object(post_to_telegram_channel, "retry", side_effect=RuntimeError("retry")) as retry:
            with self.assertRaises(RuntimeError):
                post_to_telegram_channel(1, PREDICTION)
        self.assertEqual(retry.call_args.kwargs["countdown"], 7)

    # Settings -------------------------------------------------------------------------

    def test_settings_panel_switch_and_disconnect(self):
        self.client.force_login(self.capper)
        settings_url = f"{reverse('cabinet:profile')}?tab=settings"
        page = self.client.get(settings_url)
        self.assertContains(page, "Автопостинг прогнозов")
        self.assertContains(page, reverse("notifications:telegram_channel_add"))

        self._channel()
        self.assertContains(self.client.get(settings_url), "Ставки Вадима")
        self.client.post(reverse("notifications:telegram_channel_update"))
        self.assertFalse(TelegramChannel.objects.get().post_paid)

        with patch("notifications.telegram_channels.api_call") as call:
            response = self.client.post(reverse("notifications:telegram_channel_disconnect"))
        self.assertRedirects(response, settings_url, fetch_redirect_response=False)
        call.assert_called_once_with("leaveChat", {"chat_id": "-100777"})
        self.assertFalse(TelegramChannel.objects.exists())


@override_settings(TG_BOT_TOKEN="123456:TEST")
class TelegramApiTests(TestCase):
    def test_refusal_keeps_code_and_pause(self):
        body = {"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 5}}
        refusal = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, io.BytesIO(json.dumps(body).encode()))
        with patch("urllib.request.urlopen", side_effect=refusal):
            with self.assertRaises(TelegramApiError) as caught:
                api_call("sendMessage", {"chat_id": "1"})
        self.assertEqual((caught.exception.code, caught.exception.retry_after), (429, 5))

    def test_upload_sends_fields_json_and_file(self):
        answer = io.BytesIO(json.dumps({"ok": True, "result": {"message_id": 3}}).encode())
        with patch("urllib.request.urlopen", return_value=answer) as urlopen:
            result = api_upload(
                "sendPhoto",
                {"chat_id": "-100", "reply_markup": {"inline_keyboard": []}},
                {"photo": ("card.png", b"PNGDATA", "image/png")},
            )
        request = urlopen.call_args.args[0]
        self.assertEqual(result, {"message_id": 3})
        self.assertTrue(request.get_header("Content-type").startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="chat_id"\r\n\r\n-100\r\n', request.data)
        self.assertIn(b'{"inline_keyboard": []}', request.data)
        self.assertIn(b'filename="card.png"\r\nContent-Type: image/png\r\n\r\nPNGDATA\r\n', request.data)
