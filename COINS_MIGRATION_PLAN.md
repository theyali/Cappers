# План миграции виртуального баланса на коины

Цель: полностью отказаться от концепции "виртуального баланса в рублях" и заменить ее внутренней валютой приложения: коинами. Реальный баланс остается отдельным денежным балансом и используется только для реальных начислений: призы турниров, доходы капперов, реферальные начисления, выводы. Fallback на старый виртуальный баланс оставлять нельзя.

## 1. Спроектировать новую модель кошелька коинов и админские настройки курса/пакетов

В `wallets/models.py` заменить смысл старых моделей `CapperBalance` и `BalanceTransaction` на coin-кошелек и coin-ledger. Лучше не пытаться поддерживать старое название как основное API. Нужно ввести новые модели:

```python
class CoinWallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="coin_wallet")
    balance = models.PositiveBigIntegerField("Коины", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

```python
class CoinTransaction(models.Model):
    class Kind(models.TextChoices):
        INITIAL_GRANT = "initial_grant", "Стартовые коины"
        PACKAGE_PURCHASE = "package_purchase", "Покупка пакета"
        ROULETTE_REWARD = "roulette_reward", "Приз рулетки"
        PREDICTION_STAKE = "prediction_stake", "Списание за прогноз"
        PREDICTION_PAYOUT = "prediction_payout", "Выплата по прогнозу"
        PREDICTION_REFUND = "prediction_refund", "Возврат прогноза"
        COPYBET_STAKE = "copybet_stake", "Списание за копиставку"
        COPYBET_PAYOUT = "copybet_payout", "Выплата по копиставке"
        COPYBET_REFUND = "copybet_refund", "Возврат копиставки"
        DAILY_TASK_REWARD = "daily_task_reward", "Ежедневное задание"
        ADJUSTMENT = "adjustment", "Корректировка"
```

Поля транзакции должны быть целочисленными:

```python
amount = models.BigIntegerField("Изменение коинов")
balance_after = models.PositiveBigIntegerField("Коинов после операции")
```

Добавить админские настройки:

```python
class CoinSettings(models.Model):
    coin_price_rub = models.DecimalField("Цена 1 коина, ₽", max_digits=10, decimal_places=2, default=5)
    initial_grant = models.PositiveIntegerField("Стартовые коины", default=1000)
    is_enabled = models.BooleanField("Коины включены", default=True)
```

Добавить пакеты покупки:

```python
class CoinPackage(models.Model):
    title = models.CharField(max_length=80)
    coins = models.PositiveIntegerField("Коины")
    price_rub = models.DecimalField("Цена, ₽", max_digits=12, decimal_places=2)
    bonus_coins = models.PositiveIntegerField("Бонусные коины", default=0)
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)
```

Админка `wallets/admin.py` должна позволять:

- менять курс `coin_price_rub`;
- включать/выключать coin-систему;
- создавать пакеты: `1000 коинов за 500 ₽`, `10000 коинов за 1000 ₽` и любые другие;
- видеть кошельки пользователей;
- видеть всю историю `CoinTransaction`;
- вручную делать корректировку коинов через admin action или отдельный безопасный сервис.

Критерии готовности шага:

- в коде есть `CoinWallet`, `CoinTransaction`, `CoinSettings`, `CoinPackage`;
- у `CoinSettings` singleton-поведение как у `RouletteSettings.load()`;
- коиновые суммы хранятся только целыми числами;
- реальные деньги в пакетах и реальном балансе остаются `Decimal`;
- старые названия "виртуальный баланс" не используются в новых публичных API.

## 2. Переписать wallet-сервисы на coin API без fallback на `CapperBalance`

В `wallets/services.py` ввести новый основной API:

```python
ensure_coin_wallet(user) -> CoinWallet
credit_coins(user, amount, kind, related_obj=None, note="") -> CoinWallet
charge_coins(user, amount, kind, related_obj=None, note="") -> CoinWallet
purchase_coin_package(user, package, payment=None, note="") -> CoinWallet
format_coins(value) -> str
```

Старые функции нужно не оставлять как fallback, а удалить или заменить на явные ошибки на время миграции:

```python
ensure_virtual_balance
ensure_capper_balance
top_up_virtual_balance
transfer_real_to_virtual
virtual_top_up_amount
starting_balance
```

Важно: не должно быть логики "если coin wallet не найден, используем capper_balance". Если кошелька нет, `ensure_coin_wallet()` создает `CoinWallet` и начисляет стартовые коины через `CoinTransaction.Kind.INITIAL_GRANT`.

Правила сервиса:

- все операции с коинами идут внутри `transaction.atomic()`;
- кошелек блокируется через `select_for_update()`;
- списание запрещено, если `balance < amount`;
- `amount` для коинов всегда `int`, `Decimal` тут не использовать;
- идемпотентность сохраняется через `related_model` + `related_id`, как сейчас у `BalanceTransaction`;
- начисления/списания прогнозов и копибеттинга должны писать `CoinTransaction`, а не `BalanceTransaction`;
- `RealBalanceTransaction` и `CapperRealBalance` не трогать, кроме удаления перевода real -> virtual.

Переписать конкретные места:

- `charge_prediction_stake()` должен стать `charge_prediction_stake()` на коинах или быть переименован в `charge_prediction_coin_stake()`;
- `settle_prediction_coupon()` должен выплачивать коины;
- `_charge_copied_bet_stake()` должен списывать коины;
- `settle_copied_bets_for_coupon()` должен начислять коины;
- `activate_copybetting()` должен проверять `ensure_coin_wallet(user)`;
- `copybetting` поля `bank_amount`, `stop_loss_amount`, `max_single_stake`, `total_staked`, `total_profit`, `current_loss` пока можно оставить `Decimal` только если это сильно завязано на формы, но все UI-лейблы и расчеты должны трактовать их как коины. Лучше отдельной миграцией перевести их в `PositiveBigIntegerField`/`BigIntegerField`.

Критерии готовности шага:

- `rg "ensure_virtual_balance|top_up_virtual_balance|transfer_real_to_virtual|CapperBalance|BalanceTransaction" wallets cabinet tournaments front templates` не показывает рабочих импортов старого virtual balance, кроме миграций или временных data migration;
- все новые начисления/списания идут через `CoinTransaction`;
- реальные деньги не смешиваются с коинами.

## 3. Обновить все продуктовые сценарии: ставки, копибеттинг, рулетка, платежка, профиль

Заменить использование виртуального баланса во всех местах проекта.

Основные файлы для проверки:

```text
wallets/views.py
wallets/context_processors.py
wallets/signals.py
wallets/forms.py
wallets/admin.py
wallets/tests.py
cabinet/views.py
cabinet/roulette/api.py
cabinet/roulette/reward_service.py
front/static/front/js/roulette.js
front/static/front/js/matches.js
tournaments/views.py
tournaments/services/coupons.py
templates/wallets/top_up.html
templates/wallets/copybetting_setup.html
templates/cabinet/profile.html
templates/front/includes/_main_header.html
templates/front/includes/_mobile_offcanvas.html
```

Что поменять:

- header должен показывать коины, а не `₽`;
- профиль `wallet` tab должен показывать `Коины` и историю `CoinTransaction`;
- страница пополнения должна стать страницей покупки coin-пакетов;
- формы ставок/купонов должны показывать стоимость в коинах;
- копибеттинг должен показывать банк, ставку, стоп-лосс и прибыль в коинах;
- рулетка должна заменить reward type `virtual_balance` на `coins`;
- текст выигрыша в `front/static/front/js/roulette.js` должен стать `+N коинов начислено`;
- API рулетки должен возвращать актуальный `coin_balance`, а не `virtual_balance`;
- `wallets/views.real_balance_action` должен убрать действие `transfer_to_virtual`;
- `templates/wallets/top_up.html` должен убрать блок "Перевести реальный в виртуальный";
- реальный баланс должен остаться только для капперов и только для реальных начислений/выводов.

Для платежки:

- покупка пакета коинов должна создавать платеж на сумму `CoinPackage.price_rub`;
- после успешной оплаты вызывать `purchase_coin_package()`;
- в `CoinTransaction` писать `coins + bonus_coins`;
- если платежка пока не готова, оставить пакетную покупку как admin/dev-заглушку, но не через старое "виртуальное пополнение".

Критерии готовности шага:

- на UI нигде нет "Виртуальный баланс";
- на UI нигде нет `₽` рядом с coin-балансом, ставкой или копибеттинг-банком;
- реальные рубли видны только в real balance, выводах, доходах каппера и покупке coin-пакетов;
- рулетка начисляет коины через `credit_coins()`.

## 4. Сделать миграцию данных и убрать старый virtual balance без fallback

Нужна миграция, которая переносит старые данные из `CapperBalance`/`BalanceTransaction` в новые `CoinWallet`/`CoinTransaction`.

Правило конвертации задать явно. Например:

```text
1 старый virtual balance unit = 1 coin
```

или использовать текущую настройку курса, если бизнес хочет пересчет:

```text
coins = old_balance / coin_price_rub
```

Рекомендация для безопасной миграции: `1 старый unit = 1 coin`, потому что старый баланс уже использовался как внутренняя игровая валюта, хотя отображался в рублях.

Что сделать:

- создать schema migration с новыми моделями;
- создать data migration:
  - для каждого `CapperBalance` создать `CoinWallet`;
  - для каждой `BalanceTransaction` создать `CoinTransaction`;
  - сохранить `kind`, `amount`, `balance_after`, `related_model`, `related_id`, `note`, `created_at`;
  - старые Decimal значения округлить до int по выбранному правилу;
- после успешной миграции удалить или перестать регистрировать старые модели;
- удалить создание старого `CapperBalance` из `wallets/signals.py`;
- заменить `related_name="capper_balance"` на `coin_wallet`;
- убрать старые настройки `CAPPER_STARTING_BALANCE`, `CAPPER_VIRTUAL_TOP_UP_AMOUNT` или заменить их на coin-настройки;
- удалить старые admin-классы `CapperBalanceAdmin` и `BalanceTransactionAdmin`.

Важно: не оставлять compatibility layer, который продолжает читать `CapperBalance`. После миграции источник истины только `CoinWallet`.

Команды проверки:

```bash
python manage.py makemigrations wallets
python manage.py migrate
python manage.py shell
```

В shell проверить:

```python
from wallets.models import CoinWallet, CoinTransaction
CoinWallet.objects.count()
CoinTransaction.objects.count()
```

Критерии готовности шага:

- новые пользователи получают `CoinWallet`;
- старые пользователи имеют перенесенный coin-баланс;
- старые virtual-модели не используются приложением;
- real balance migration не затронут.

## 5. Переписать тесты, проверить поиском и закрыть старые упоминания

Обновить тесты:

```text
wallets/tests.py
cabinet/tests/test_roulette_api.py
tournaments/tests.py
```

Что покрыть:

- новый пользователь получает стартовые коины;
- покупка coin-пакета начисляет `coins + bonus_coins`;
- ставка списывает коины;
- победа по прогнозу начисляет коины;
- refund возвращает коины;
- копибеттинг списывает и начисляет коины;
- roulette reward `coins` начисляет коины;
- real balance не может переводиться в coins напрямую через старый `transfer_real_to_virtual`;
- реальный баланс по турнирам и подпискам продолжает работать отдельно;
- недостаток коинов возвращает `InsufficientBalance` с текстом про коины, не про рубли.

Запустить проверки:

```bash
rg -n "Виртуальный баланс|виртуальный баланс|virtual_balance|CapperBalance|BalanceTransaction|top_up_virtual_balance|ensure_virtual_balance|transfer_real_to_virtual|REAL_TO_VIRTUAL|VIRTUAL_DEPOSIT|₽" wallets cabinet tournaments front templates
python manage.py test wallets cabinet.tests.test_roulette_api tournaments
```

После `rg` допустимы только:

- старые миграции;
- документация, если она явно помечена как историческая;
- реальные рубли в `CapperRealBalance`, `RealBalanceTransaction`, покупке coin-пакетов и платежке.

Финальные критерии готовности:

- во всех пользовательских сценариях используется `CoinWallet`;
- старый virtual balance не читается и не пополняется;
- в админке можно управлять курсом и пакетами коинов;
- в UI коины отображаются как коины, а рубли только как реальные деньги;
- тесты проходят.
