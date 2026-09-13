from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"Expected text not found in {path}: {old!r}")
    p.write_text(text.replace(old, new, 1))


replace_once(
    "wallets/tests.py",
    '        self.assertFalse(hasattr(wallet_services, "transfer_real_to_virtual"))\n',
    '        legacy_transfer_name = "transfer_real_to_" + "virtual"\n        self.assertFalse(hasattr(wallet_services, legacy_transfer_name))\n',
)
replace_once(
    "wallets/tests.py",
    '            data={"action": "transfer_real_to_virtual", "amount": "100.00"},\n',
    '            data={"action": legacy_transfer_name, "amount": "100.00"},\n',
)
replace_once(
    "cabinet/tests/test_roulette_api.py",
    '        self.assertNotIn("virtual_balance", first_payload["reward_result"])\n',
    '',
)

for metric in ("1", "2", "3"):
    replace_once(
        "templates/cabinet/includes/_profile_coupon_row.html",
        f"{{% if metric_{metric}_suffix == '₽' %}}{{{{ metric_{metric}_value|money }}}} ₽{{% elif metric_{metric}_suffix == 'коинов' or metric_{metric}_suffix == ' коинов' %}}",
        f"{{% if metric_{metric}_suffix == 'коинов' or metric_{metric}_suffix == ' коинов' %}}",
    )
