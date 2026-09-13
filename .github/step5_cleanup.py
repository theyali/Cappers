from pathlib import Path


def replace_once(path, old, new):
    file_path = Path(path)
    text = file_path.read_text()
    if old not in text:
        raise SystemExit(f"Expected text not found in {path}: {old!r}")
    file_path.write_text(text.replace(old, new, 1))


models_path = Path("wallets/models.py")
models = models_path.read_text()
start = models.index("\nclass CapperBalance(models.Model):")
end = models.index("\nclass CapperRealBalance(models.Model):", start)
models = models[:start] + "\n\n" + models[end:]
legacy_real_kind = '        VIRTUAL_TOP_UP = "virtual_top_up", "Пополнение виртуального баланса"\n'
if legacy_real_kind not in models:
    raise SystemExit("Legacy real->virtual transaction kind not found")
models = models.replace(legacy_real_kind, "", 1)
old_coin_settings_save = '''    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
'''
new_coin_settings_save = '''    def save(self, *args, **kwargs):
        self.pk = 1
        if self._state.adding and type(self).objects.filter(pk=1).exists():
            if self.created_at is None:
                self.created_at = type(self).objects.values_list("created_at", flat=True).get(pk=1)
            self._state.adding = False
            kwargs.pop("force_insert", None)
            kwargs["force_update"] = True
        super().save(*args, **kwargs)
'''
if old_coin_settings_save not in models:
    raise SystemExit("CoinSettings.save block not found")
models = models.replace(old_coin_settings_save, new_coin_settings_save, 1)
models_path.write_text(models)

settings_path = Path("cappers/settings.py")
settings = settings_path.read_text()
replace_import = "from decimal import Decimal\n"
if replace_import not in settings:
    raise SystemExit("Decimal import not found in settings")
settings = settings.replace(replace_import, "", 1)
old_processor = '                "wallets.context_processors.capper_balance",\n'
new_processor = '                "wallets.context_processors.coin_wallet",\n'
if old_processor not in settings:
    raise SystemExit("Legacy context processor setting not found")
settings = settings.replace(old_processor, new_processor, 1)
for line in (
    'CAPPER_STARTING_BALANCE = Decimal(os.getenv("CAPPER_STARTING_BALANCE", "10000.00"))\n',
    'CAPPER_VIRTUAL_TOP_UP_AMOUNT = Decimal(os.getenv("CAPPER_VIRTUAL_TOP_UP_AMOUNT", "10000.00"))\n',
):
    if line not in settings:
        raise SystemExit(f"Legacy setting not found: {line.strip()}")
    settings = settings.replace(line, "", 1)
settings_path.write_text(settings)

replace_once(
    "tournaments/tests.py",
    '        self.analyst.capper_balance.refresh_from_db()\n'
    '        self.assertEqual(self.analyst.capper_balance.balance, Decimal("9900.00"))\n',
    '        self.analyst.coin_wallet.refresh_from_db()\n'
    '        self.assertEqual(self.analyst.coin_wallet.balance, 900)\n',
)

replace_once(
    "wallets/tests.py",
    '    def test_top_up_post_does_not_mint_coins_without_payment(self):\n'
    '        CoinPackage.objects.create(\n',
    '    def test_top_up_post_does_not_mint_coins_without_payment(self):\n'
    '        package = CoinPackage.objects.create(\n',
)
replace_once(
    "wallets/tests.py",
    '            data={"package_id": 1, "next": reverse("cabinet:profile")},\n',
    '            data={"package_id": package.pk, "next": reverse("cabinet:profile")},\n',
)

errors_path = Path("Errors to fix.md")
errors = errors_path.read_text()
errors = errors.replace(
    "13. _ensure_initial_bonus_locked в services.py — создаёт транзакцию INITIAL_BONUS даже при CAPPER_STARTING_BALANCE=0.\n",
    "",
)
errors_path.write_text(errors)
