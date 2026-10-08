from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from cabinet.models import User, UserVipSubscription
from cabinet.roulette.models import RoulettePrize
from cabinet.roulette.selectors import get_available_roulette_prizes
from cabinet.vip import extend_vip


class RoulettePrizeSeedTests(TestCase):
    def seed(self, *args):
        output = StringIO()
        call_command("seed_roulette_prizes", *args, stdout=output)
        return output.getvalue()

    def wheel(self, username, role, *, vip=False):
        user = User.objects.create_user(username=username, password="x", role=role)
        if vip:
            extend_vip(user, 7, UserVipSubscription.Source.ROULETTE)
        return [prize.title for prize in get_available_roulette_prizes(user=user)]

    def test_each_audience_gets_its_own_prizes_within_ten_sectors(self):
        self.seed()

        reader = self.wheel("seed-reader", User.Role.READER)
        vip_reader = self.wheel("seed-vip-reader", User.Role.READER, vip=True)
        capper = self.wheel("seed-capper", User.Role.ANALYST)
        vip_capper = self.wheel("seed-vip-capper", User.Role.ANALYST, vip=True)

        self.assertEqual([len(reader), len(vip_reader), len(capper), len(vip_capper)], [8, 8, 8, 10])
        for wheel in (reader, vip_reader, capper, vip_capper):
            self.assertTrue({"50 коинов", "Пусто", "+1 попытка", "300 коинов"} <= set(wheel))
        self.assertIn("VIP на 1 день", reader)
        self.assertNotIn("VIP на 1 день", vip_reader)
        self.assertIn("+3 дня VIP", vip_reader)
        self.assertNotIn("+3 дня VIP", reader)
        self.assertIn("1 бесплатный прогноз", capper)
        self.assertNotIn("1 бесплатный прогноз", reader)
        self.assertIn("400 коинов", vip_capper)

    def test_second_run_adds_nothing(self):
        self.seed()
        self.seed()

        self.assertEqual(RoulettePrize.objects.count(), 14)

    def test_update_brings_a_same_named_prize_to_its_audience(self):
        RoulettePrize.objects.create(title="500 коинов", reward_type=RoulettePrize.RewardType.COINS, reward_value=500)

        self.seed()
        self.assertIn("500 коинов", self.wheel("seed-reader-before", User.Role.READER))

        self.seed("--update")
        self.assertNotIn("500 коинов", self.wheel("seed-reader-after", User.Role.READER))

    def test_other_prizes_are_switched_off_only_on_request(self):
        old = RoulettePrize.objects.create(title="Старый приз", reward_type=RoulettePrize.RewardType.COINS, reward_value=10)

        output = self.seed()
        old.refresh_from_db()
        self.assertTrue(old.is_active)
        self.assertIn("--disable-other-prizes", output)

        self.seed("--disable-other-prizes")
        old.refresh_from_db()
        self.assertFalse(old.is_active)
