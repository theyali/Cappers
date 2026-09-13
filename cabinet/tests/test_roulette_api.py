import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from cabinet.roulette_history import RouletteSpin
from cabinet.roulette_models import RoulettePrize, RouletteSettings
from cabinet.roulette_rewards import UserRouletteRewardState
from cabinet.roulette_state import UserRouletteState


class RouletteApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="roulette-user",
            email="roulette@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)
        RouletteSettings.objects.update_or_create(
            pk=1,
            defaults={
                "is_enabled": True,
                "daily_free_spins": 0,
                "reset_hour": 0,
            },
        )

    def create_prize(self, **overrides):
        data = {
            "title": "VIP",
            "short_text": "на 1 день",
            "reward_type": RoulettePrize.RewardType.VIP_DAYS,
            "reward_value": 1,
            "reward_text": "",
            "weight": 15,
            "is_active": True,
            "sector_order": 2,
        }
        data.update(overrides)
        return RoulettePrize.objects.create(**data)

    def post_spin(self, operation_id):
        return self.client.post(
            reverse("cabinet:roulette_spin"),
            data=json.dumps({"operation_id": str(operation_id)}),
            content_type="application/json",
        )

    def test_state_returns_public_sector_data_without_weight_or_promo_code(self):
        prize = self.create_prize(
            title="Промокод",
            short_text="Скидка на VIP",
            reward_type=RoulettePrize.RewardType.PROMO_CODE,
            reward_value=0,
            reward_text="SECRET-20",
        )

        response = self.client.get(reverse("cabinet:roulette_state"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("server_time", payload)
        self.assertEqual(payload["available_spins"], 0)
        self.assertEqual(len(payload["sectors"]), 1)
        sector = payload["sectors"][0]
        self.assertEqual(sector["prize_id"], prize.pk)
        self.assertEqual(sector["sector_index"], 2)
        self.assertEqual(sector["visual_type"], "default")
        self.assertNotIn("weight", sector)
        self.assertNotIn("reward_text", sector)
        self.assertNotIn("SECRET-20", response.content.decode("utf-8"))

    def test_state_limits_canvas_to_ten_active_sectors(self):
        for sector_order in range(12):
            self.create_prize(
                title=f"Приз {sector_order}",
                reward_type=RoulettePrize.RewardType.NOTHING,
                reward_value=0,
                sector_order=sector_order,
            )

        response = self.client.get(reverse("cabinet:roulette_state"))

        self.assertEqual(response.status_code, 200)
        sectors = response.json()["sectors"]
        self.assertEqual(len(sectors), 10)
        self.assertEqual(
            [sector["sector_index"] for sector in sectors],
            list(range(10)),
        )

    def test_fixed_roulette_renders_ssr_badge_when_spins_are_available(self):
        UserRouletteState.objects.create(user=self.user, available_spins=3)

        response = self.client.get(reverse("cabinet:bonuses"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-roulette-available-spins="3"')
        self.assertContains(response, 'data-roulette-badge')
        self.assertContains(response, '>3</span>')

    def test_fixed_roulette_omits_ssr_badge_when_no_spins_are_available(self):
        UserRouletteState.objects.create(user=self.user, available_spins=0)

        response = self.client.get(reverse("cabinet:bonuses"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-roulette-available-spins="0"')
        self.assertNotContains(response, 'data-roulette-badge')

    def test_spin_returns_no_spins_code_when_user_has_no_attempts(self):
        self.create_prize(reward_type=RoulettePrize.RewardType.NOTHING, reward_value=0)

        response = self.post_spin(uuid.uuid4())

        self.assertEqual(response.status_code, 409)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["code"], "no_spins")
        self.assertEqual(RouletteSpin.objects.count(), 0)

    def test_ten_available_spins_allow_exactly_ten_unique_operations(self):
        self.create_prize(
            title="Пустой сектор",
            reward_type=RoulettePrize.RewardType.NOTHING,
            reward_value=0,
            weight=1,
        )
        UserRouletteState.objects.create(user=self.user, available_spins=10)

        for expected_remaining in range(9, -1, -1):
            response = self.post_spin(uuid.uuid4())
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["available_spins"], expected_remaining)

        rejected_response = self.post_spin(uuid.uuid4())

        self.assertEqual(rejected_response.status_code, 409)
        self.assertEqual(rejected_response.json()["code"], "no_spins")
        self.assertEqual(RouletteSpin.objects.filter(user=self.user).count(), 10)

        state = UserRouletteState.objects.get(user=self.user)
        self.assertEqual(state.available_spins, 0)
        self.assertEqual(state.total_spins, 10)

    def test_repeated_operation_id_does_not_consume_attempt_twice(self):
        self.create_prize(
            title="Пустой сектор",
            reward_type=RoulettePrize.RewardType.NOTHING,
            reward_value=0,
            weight=1,
        )
        UserRouletteState.objects.create(user=self.user, available_spins=2)
        operation_id = uuid.uuid4()

        first_response = self.post_spin(operation_id)
        second_response = self.post_spin(operation_id)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response.json()["spin_id"], second_response.json()["spin_id"])
        self.assertEqual(first_response.json()["available_spins"], 1)
        self.assertEqual(second_response.json()["available_spins"], 1)
        self.assertEqual(RouletteSpin.objects.filter(user=self.user).count(), 1)

        state = UserRouletteState.objects.get(user=self.user)
        self.assertEqual(state.available_spins, 1)
        self.assertEqual(state.total_spins, 1)

    def test_spin_is_server_authoritative_and_idempotent(self):
        prize = self.create_prize(
            title="Пустой сектор",
            short_text="Попробуйте завтра",
            reward_type=RoulettePrize.RewardType.NOTHING,
            reward_value=0,
            weight=1,
            sector_order=7,
        )
        UserRouletteState.objects.create(user=self.user, available_spins=1)
        operation_id = uuid.uuid4()

        first_response = self.post_spin(operation_id)
        second_response = self.post_spin(operation_id)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        first_payload = first_response.json()
        second_payload = second_response.json()
        self.assertTrue(first_payload["ok"])
        self.assertEqual(first_payload["prize_id"], prize.pk)
        self.assertEqual(first_payload["sector_index"], 7)
        self.assertEqual(first_payload["available_spins"], 0)
        self.assertEqual(first_payload["spin_id"], second_payload["spin_id"])
        self.assertEqual(RouletteSpin.objects.count(), 1)

        state = UserRouletteState.objects.get(user=self.user)
        self.assertEqual(state.available_spins, 0)
        self.assertEqual(state.total_spins, 1)

    def test_extra_spin_reward_is_applied_once_and_saved_in_attempts_after(self):
        prize = self.create_prize(
            title="Дополнительная попытка",
            short_text="+1 попытка",
            reward_type=RoulettePrize.RewardType.EXTRA_SPIN,
            reward_value=1,
            weight=1,
            sector_order=0,
        )
        UserRouletteState.objects.create(user=self.user, available_spins=1)
        operation_id = uuid.uuid4()

        first_response = self.post_spin(operation_id)
        second_response = self.post_spin(operation_id)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response.json()["prize_id"], prize.pk)
        self.assertEqual(first_response.json()["available_spins"], 1)
        self.assertEqual(second_response.json()["available_spins"], 1)
        self.assertEqual(first_response.json()["spin_id"], second_response.json()["spin_id"])

        spin = RouletteSpin.objects.get(operation_id=operation_id)
        self.assertEqual(spin.attempts_before, 1)
        self.assertEqual(spin.attempts_after, 1)
        self.assertEqual(spin.reward_status, RouletteSpin.RewardStatus.ISSUED)

        state = UserRouletteState.objects.get(user=self.user)
        self.assertEqual(state.available_spins, 1)
        self.assertEqual(state.total_spins, 1)
        self.assertEqual(RouletteSpin.objects.filter(user=self.user).count(), 1)

    def test_spin_returns_reward_result_for_win_screen(self):
        self.create_prize(
            title="VIP",
            short_text="на 1 день",
            reward_type=RoulettePrize.RewardType.VIP_DAYS,
            reward_value=1,
            weight=1,
            sector_order=0,
        )
        UserRouletteState.objects.create(user=self.user, available_spins=1)

        response = self.post_spin(uuid.uuid4())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["reward_status"], RouletteSpin.RewardStatus.ISSUED)
        self.assertEqual(payload["reward_result"]["type"], RoulettePrize.RewardType.VIP_DAYS)
        self.assertIsNotNone(payload["reward_result"]["vip_until"])

        reward_state = UserRouletteRewardState.objects.get(user=self.user)
        self.assertIsNotNone(reward_state.vip_until)

    def test_spin_rejects_invalid_operation_id(self):
        response = self.client.post(
            reverse("cabinet:roulette_spin"),
            data=json.dumps({"operation_id": "not-a-uuid"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["code"], "invalid_operation_id")


class RouletteConcurrentApiTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="roulette-concurrent-user",
            email="roulette-concurrent@example.com",
            password="test-password",
        )
        RouletteSettings.objects.update_or_create(
            pk=1,
            defaults={
                "is_enabled": True,
                "daily_free_spins": 0,
                "reset_hour": 0,
            },
        )
        RoulettePrize.objects.create(
            title="Пустой сектор",
            short_text="",
            reward_type=RoulettePrize.RewardType.NOTHING,
            reward_value=0,
            reward_text="",
            weight=1,
            is_active=True,
            sector_order=0,
        )
        UserRouletteState.objects.create(user=self.user, available_spins=1)

    def _post_spin_after_barrier(self, operation_id, barrier):
        close_old_connections()
        try:
            client = Client()
            user = get_user_model().objects.get(pk=self.user.pk)
            client.force_login(user)
            barrier.wait(timeout=5)
            response = client.post(
                reverse("cabinet:roulette_spin"),
                data=json.dumps({"operation_id": str(operation_id)}),
                content_type="application/json",
            )
            return response.status_code, response.json()
        finally:
            close_old_connections()

    def test_two_fast_posts_cannot_consume_more_than_available_spins(self):
        barrier = Barrier(2)
        operation_ids = (uuid.uuid4(), uuid.uuid4())

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self._post_spin_after_barrier, operation_id, barrier)
                for operation_id in operation_ids
            ]
            results = [future.result(timeout=10) for future in futures]

        statuses = sorted(status for status, _payload in results)
        self.assertEqual(statuses, [200, 409])

        rejected_payloads = [payload for status, payload in results if status == 409]
        self.assertEqual(len(rejected_payloads), 1)
        self.assertEqual(rejected_payloads[0]["code"], "no_spins")
        self.assertEqual(RouletteSpin.objects.filter(user=self.user).count(), 1)

        state = UserRouletteState.objects.get(user=self.user)
        self.assertEqual(state.available_spins, 0)
        self.assertEqual(state.total_spins, 1)
