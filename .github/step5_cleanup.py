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

errors_path = Path("Errors to fix.md")
errors = errors_path.read_text()
errors = errors.replace(
    "13. _ensure_initial_bonus_locked в services.py — создаёт транзакцию INITIAL_BONUS даже при CAPPER_STARTING_BALANCE=0.\n",
    "",
)
errors_path.write_text(errors)
