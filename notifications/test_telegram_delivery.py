from types import SimpleNamespace

from django.test import SimpleTestCase

from .telegram_delivery import build_telegram_message


class TelegramDeliveryPresentationTests(SimpleTestCase):
    def _notification(self, *, kind, title, message="", meta=None):
        return SimpleNamespace(
            kind=kind,
            title=title,
            message=message,
            meta=meta or {},
        )

    def test_goal_notification_uses_match_presentation(self):
        notification = self._notification(
            kind="match_reminder",
            title="⚽ Гол! 1:0",
            message="ADT — УКВ Мокегуа",
            meta={"event": "score", "score": "1:0"},
        )

        text, button = build_telegram_message(notification)

        self.assertIn("⚽ <b>Гол! 1:0</b>", text)
        self.assertIn("ADT — УКВ Мокегуа", text)
        self.assertNotIn("⚽ <b>⚽", text)
        self.assertEqual(button, "⚽ Открыть матч")

    def test_prediction_and_achievement_have_specific_actions(self):
        prediction = self._notification(
            kind="new_prediction",
            title="Новый прогноз от Expert",
            message="Опубликован новый прогноз.",
        )
        achievement = self._notification(
            kind="achievement",
            title="Новое достижение",
            message="Серия побед",
        )

        prediction_text, prediction_button = build_telegram_message(prediction)
        achievement_text, achievement_button = build_telegram_message(achievement)

        self.assertTrue(prediction_text.startswith("🔥"))
        self.assertEqual(prediction_button, "📊 Открыть прогноз")
        self.assertTrue(achievement_text.startswith("🏆"))
        self.assertEqual(achievement_button, "👤 Открыть профиль")

    def test_settlement_emoji_depends_on_result(self):
        lose = self._notification(
            kind="favorite_settled",
            title="Избранный прогноз рассчитан",
            meta={"state": "lose"},
        )
        refund = self._notification(
            kind="favorite_settled",
            title="Избранный прогноз рассчитан",
            meta={"state": "refund"},
        )

        lose_text, _ = build_telegram_message(lose)
        refund_text, _ = build_telegram_message(refund)

        self.assertTrue(lose_text.startswith("❌"))
        self.assertTrue(refund_text.startswith("↩️"))

    def test_user_text_is_html_escaped(self):
        notification = self._notification(
            kind="new_prediction",
            title="Прогноз <тест>",
            message="Команда & соперник",
        )

        text, _ = build_telegram_message(notification)

        self.assertIn("Прогноз &lt;тест&gt;", text)
        self.assertIn("Команда &amp; соперник", text)
