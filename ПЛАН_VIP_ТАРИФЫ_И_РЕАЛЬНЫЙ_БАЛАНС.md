# План: VIP-тарифы для каппера и единый учет через реальный баланс

## Цель

Сделать отдельную страницу, где каппер выбирает VIP-тариф, видит текущий активный VIP и сколько времени осталось до окончания. Параллельно привести денежные операции к правилу:

- VIP-покупка списывается с реального баланса пользователя, а не с коинов;
- покупка платных прогнозов у каппера должна иметь явное списание/оплату в реальных деньгах, а доход каппера уже зачисляется на реальный баланс;
- выигрыш на турнире уже зачисляется на реальный баланс, это надо сохранить и проверить везде;
- админка и страницы должны показывать рубли/реальный баланс там, где речь о VIP, подписках, доходах и призах;
- коины оставить только для игровой ставки/купона/копибеттинга/бонусов, если это игровая внутренняя механика.

## Текущее состояние

### Уже есть

- `cabinet.models.VipPlan`
  - сейчас поле цены: `price_coins`.
- `cabinet.models.UserVipSubscription`
  - хранит периоды VIP, `starts_at`, `ends_at`, `source`, `plan`.
- `cabinet.vip.get_active_vip(user)`
  - возвращает текущий активный VIP.
- `cabinet.vip.purchase_vip(user, plan)`
  - сейчас покупает VIP за коины через `wallets.services.charge_coins`.
- `cabinet.vip_views.vip_purchase`
  - POST endpoint, возвращает JSON с `coin_balance`.
- `wallets.models.CapperRealBalance`
  - реальный баланс каппера.
- `wallets.models.RealBalanceTransaction`
  - реальные транзакции, уже есть виды `SUBSCRIPTION_INCOME`, `TOURNAMENT_PRIZE`, `REAL_DEPOSIT`, `WITHDRAWAL_*`.
- `wallets.services.credit_real_balance`
  - зачисление на реальный баланс.
- `cabinet.paid_predictions.subscribe_to_paid_predictions`
  - уже начисляет доход капперу через `credit_real_balance(..., SUBSCRIPTION_INCOME, ...)`.
- `tournaments.services.leaderboard.finalize_tournament_results`
  - уже начисляет приз турнира через `credit_real_balance(..., TOURNAMENT_PRIZE, ...)`.
- `cabinet.views.profile`
  - уже передает `coin_wallet`, `real_balance`, `coin_transactions`, `real_transactions`.

### Главная проблема

VIP покупается за коины, а должен покупаться за реальные деньги/реальный баланс. Для подписки на платные прогнозы у каппера доход начисляется капперу на реальный баланс, но нужно проверить и явно оформить источник оплаты покупателя, чтобы не было “бесплатного” создания подписки.

## Архитектурное решение

Ввести единый сервис реальных списаний:

```python
debit_real_balance(user, amount, kind, *, related_obj=None, note="")
```

Он должен:

- работать через `transaction.atomic()`;
- блокировать `CapperRealBalance` через `select_for_update`;
- проверять достаточность `balance`;
- создавать `RealBalanceTransaction` с отрицательной суммой;
- быть идемпотентным по `related_obj`, как `credit_real_balance`;
- возвращать обновленный `CapperRealBalance`.

Важно: сейчас `CapperRealBalance` валидирует пользователя как аналитика. Если реальным балансом должны платить и обычные пользователи, модель/сервис нужно переименовывать концептуально или ослабить `_validate_analyst`. Минимальный путь:

- оставить модель `CapperRealBalance` на первом этапе;
- разрешить `ensure_real_balance`/`debit_real_balance` для всех пользователей;
- в UI для читателя называть это “реальный баланс”, а не “баланс каппера”;
- позже можно переименовать модель в `UserRealBalance`, но это отдельная крупная миграция.

## Этап 1. Модель VIP-тарифов в рублях

### Файл: `cabinet/models.py`

Модель: `VipPlan`.

Добавить поле:

```python
price_rub = models.DecimalField(
    "Стоимость, ₽",
    max_digits=12,
    decimal_places=2,
    default=0,
)
```

Временно оставить `price_coins`, чтобы миграция была безопасной и старые данные не потерялись.

Обновить `__str__`:

```python
return f"{self.title} · {self.duration_days} дн. · {self.price_rub} ₽"
```

### Миграция

Создать миграцию:

```bash
python manage.py makemigrations cabinet
```

В миграции можно перенести старую цену:

- если `price_rub == 0` и `price_coins > 0`, рассчитать через `wallets.coin_economy.coins_to_rub(price_coins)`;
- либо руками оставить `price_rub=0` и заполнить тарифы в админке.

Лучше сделать data migration, чтобы старые тарифы не стали бесплатными случайно.

### Файл: `cabinet/admin.py`

Для `VipPlanAdmin`:

- заменить отображение `price_coins` на `price_rub`;
- добавить `price_rub` в `list_display`, `fields`, `list_editable` если есть;
- `price_coins` оставить read-only или убрать из UI после миграции.

Проверить через:

```bash
rg -n "VipPlan|price_coins|price_rub" cabinet/admin.py cabinet/models.py
```

## Этап 2. Реальное списание баланса

### Файл: `wallets/models.py`

В `RealBalanceTransaction.Kind` добавить виды:

```python
VIP_PURCHASE = "vip_purchase", "Покупка VIP"
PAID_PREDICTION_PURCHASE = "paid_prediction_purchase", "Покупка платной подписки"
```

Опционально:

```python
VIP_REFUND = "vip_refund", "Возврат VIP"
PAID_PREDICTION_REFUND = "paid_prediction_refund", "Возврат платной подписки"
```

### Файл: `wallets/services.py`

Добавить:

```python
def debit_real_balance(user, amount, kind: str, *, related_obj=None, note: str = "") -> CapperRealBalance:
    ...
```

Логика:

- `amount = _money(amount)`;
- если `amount <= 0`, ошибка;
- `balance = _real_balance_for_update(user)`;
- если уже есть транзакция по `kind + related_obj`, вернуть баланс;
- если `balance.balance < amount`, поднять `InsufficientBalance`;
- применить `_apply_real_locked(balance, -amount, kind, ...)`.

### Важная правка в валидации

Сейчас `ensure_real_balance`, `credit_real_balance`, `request_real_withdrawal` вызывают `_validate_analyst(user)`.

Нужно разделить:

- `ensure_real_balance(user)` и `debit_real_balance(user, ...)` должны быть доступны всем активным пользователям;
- `credit_real_balance(user, ...)`, `request_real_withdrawal(user, ...)` можно оставить только для аналитиков, если доходы/выводы доступны только капперам.

Предложение:

```python
def _validate_real_balance_user(user):
    if not user or not user.pk:
        raise ValidationError("Пользователь не найден.")

def ensure_real_balance(user):
    _validate_real_balance_user(user)
```

`credit_real_balance` и `request_real_withdrawal` оставить с `_validate_analyst`.

### Тесты

Файл: `wallets/tests.py` или новый `wallets/test_real_balance.py`.

Проверить:

- пользователь может иметь реальный баланс;
- `debit_real_balance` списывает деньги;
- недостаток баланса дает `InsufficientBalance`;
- повторный вызов с тем же `related_obj` не списывает дважды.

## Этап 3. VIP покупка через реальный баланс

### Файл: `cabinet/vip.py`

Переписать `purchase_vip`.

Сейчас:

```python
charge_coins(... CoinTransaction.Kind.ADJUSTMENT ...)
return subscription, wallet
```

Должно быть:

```python
from wallets.models import RealBalanceTransaction
from wallets.services import debit_real_balance, ensure_real_balance

subscription = activate_vip(...)
if current_plan.price_rub > 0:
    real_balance = debit_real_balance(
        user,
        current_plan.price_rub,
        RealBalanceTransaction.Kind.VIP_PURCHASE,
        related_obj=subscription,
        note=f"Покупка VIP «{current_plan.title}»",
    )
else:
    real_balance = ensure_real_balance(user)
return subscription, real_balance
```

Важно: порядок операций. Сейчас сначала создается подписка, потом списываются коины. Если списание не удалось, transaction rollback откатывает подписку. Это поведение сохранить.

### Файл: `cabinet/vip_views.py`

Заменить `InsufficientCoins` на `InsufficientBalance`.

JSON ответ:

Сейчас:

```json
{
  "coin_balance": 123
}
```

Должно быть:

```json
{
  "real_balance": "1000.00",
  "real_balance_display": "1 000 ₽"
}
```

Импортировать `format_money`.

### Файл: `cabinet/tests/test_vip_service.py`

Обновить тесты:

- старые проверки `coin_wallet.balance` заменить на `real_balance.balance`;
- добавить тест “не хватает реального баланса”;
- проверить, что VIP-период не создается при ошибке списания;
- проверить, что активный VIP продлевается от текущего `ends_at`.

## Этап 4. Страница выбора VIP-тарифа

### URL

Файл: `cabinet/urls.py`.

Добавить:

```python
path("vip/", vip_views.vip_plans, name="vip_plans")
```

Оставить старый POST:

```python
path("vip/purchase/", vip_views.vip_purchase, name="vip_purchase")
```

### View

Файл: `cabinet/vip_views.py`.

Добавить `vip_plans(request)`.

Контекст:

- `plans = VipPlan.objects.filter(is_active=True).order_by("order", "duration_days", "id")`;
- `active_vip = get_active_vip(request.user)`;
- `real_balance = ensure_real_balance(request.user)`;
- `real_balance_display = format_money(real_balance.balance)`;
- `vip_time_left`:
  - если `active_vip`, посчитать `ends_at - timezone.now()`;
  - передать `days`, `hours`, `minutes`, `ends_at`;
- `next_url` после покупки.

Для роли:

- страница доступна авторизованным;
- если VIP нужен только капперам, в view проверять `request.user.role == User.Role.ANALYST`;
- если VIP может покупать любой пользователь, страницу оставить для всех.

По текущей логике VIP-фичи больше относятся к капперам, поэтому минимально ограничить капперами.

### Template

Создать:

```text
templates/cabinet/vip_plans.html
```

Структура:

- текущий статус:
  - “VIP активен” / “VIP не активен”;
  - “Осталось: X дней Y часов”;
  - дата окончания;
- карточки тарифов:
  - название;
  - срок;
  - цена в ₽;
  - активность/популярный;
  - кнопка “Подключить” или “Продлить”;
- блок баланса:
  - текущий реальный баланс;
  - ссылка на пополнение `wallets:top_up`;
  - если баланса не хватает, CTA “Пополнить баланс”.

Форма покупки:

```django
<form method="post" action="{% url 'cabinet:vip_purchase' %}">
    {% csrf_token %}
    <input type="hidden" name="plan_id" value="{{ plan.id }}">
    <button type="submit">...</button>
</form>
```

Можно использовать обычный POST+redirect вместо JSON, либо оставить JSON endpoint и сделать progressive enhancement JS. Проще и надежнее:

- `vip_purchase` должен уметь HTML POST;
- если `Accept: application/json` или `Content-Type: application/json`, вернуть JSON;
- иначе `messages.success/error` и redirect обратно на `vip_plans`.

### CSS

Файл: `front/static/front/css/main.css`.

Добавить новый блок:

- `.vip-plans-page`
- `.vip-status-card`
- `.vip-plan-grid`
- `.vip-plan-card`
- `.vip-plan-price`
- `.vip-plan-action`
- `.vip-balance-panel`

Не использовать inline styles.

Ограничить визуально без огромных блоков:

- карточки 8-12px radius;
- `font-size <= 17px`;
- `font-weight <= 600`;
- плотная сетка, без hero-баннера.

### Навигация

Найти ссылки на VIP:

```bash
rg -n "vip_purchase|VIP|vip" templates cabinet front
```

Заменить CTA, где пользователь должен выбирать тариф:

- `reverse("cabinet:vip_purchase")` заменить на `reverse("cabinet:vip_plans")`;
- в профиле/настройках/locked state rich editor `vip_upgrade_url` должен вести на `cabinet:vip_plans`.

Файл:

- `game/services/prediction_editor.py`
  - сейчас `vip_upgrade_url = reverse("cabinet:profile")`;
  - заменить на `reverse("cabinet:vip_plans")`.

Проверить:

- `cabinet/avatar_views.py`;
- `templates/cabinet/profile.html`;
- `templates/cabinet/_profile_settings.html`;
- `templates/game/rich_prediction_form.html`;
- `templates/cabinet/capper/*`.

## Этап 5. Платные прогнозы: явное списание покупателя

### Текущая проблема

`cabinet.paid_predictions.subscribe_to_paid_predictions` начисляет доход капперу:

```python
credit_real_balance(analyst, capper_income, SUBSCRIPTION_INCOME)
```

Но в найденном коде не видно явного списания денег у покупателя. Нужно сделать симметрично:

- покупатель платит `price`;
- каппер получает `capper_income`;
- комиссия платформы, если есть, остается как разница.

### Файл: `cabinet/paid_predictions.py`

Внутри `subscribe_to_paid_predictions`:

Перед созданием/продлением подписки или внутри той же транзакции добавить:

```python
debit_real_balance(
    subscriber,
    price,
    RealBalanceTransaction.Kind.PAID_PREDICTION_PURCHASE,
    related_obj=subscription,
    note=f"Покупка подписки @{analyst.username}: {plan_title}",
)
```

Но `subscription` создается в `get_or_create`, поэтому порядок лучше такой:

1. создать/получить subscription под lock;
2. определить, новая покупка или продление;
3. списать с `subscriber` по `related_obj=subscription` и kind `PAID_PREDICTION_PURCHASE`;
4. начислить `capper_income` аналитику;
5. начислить рефералку.

Для продления нужен idempotency:

- если использовать один и тот же `subscription` как related_obj, повторное продление может не списаться из-за unique constraint;
- значит для продлений нужен отдельный объект или другой related_id.

Варианты:

Вариант А, простой:

- создать новую модель `PaidPredictionPayment`;
- каждая покупка/продление создает payment row;
- транзакции real balance связаны с payment.

Вариант Б, временный:

- `related_obj=None` для списаний подписок;
- тогда идемпотентность не работает.

Лучший вариант: Вариант А.

### Новая модель

Файл: `cabinet/models.py`.

Добавить:

```python
class AnalystPaidSubscriptionPayment(models.Model):
    subscription = models.ForeignKey(AnalystPaidSubscription, ...)
    subscriber = models.ForeignKey(User, related_name="paid_prediction_payments", ...)
    analyst = models.ForeignKey(User, related_name="paid_prediction_sales", ...)
    plan = models.ForeignKey(AnalystPaidPlan, null=True, blank=True, ...)
    price = models.DecimalField(...)
    capper_income = models.DecimalField(...)
    duration_days = models.PositiveIntegerField(...)
    starts_at = models.DateTimeField(...)
    expires_at = models.DateTimeField(...)
    created_at = models.DateTimeField(auto_now_add=True)
```

Тогда:

- `debit_real_balance(subscriber, price, PAID_PREDICTION_PURCHASE, related_obj=payment)`;
- `credit_real_balance(analyst, capper_income, SUBSCRIPTION_INCOME, related_obj=payment)`;
- рефералку тоже привязать к `payment`.

### UI

Файлы:

- `templates/cabinet/paid_predictions_checkout.html`;
- `templates/modals/expert_paid_subscribe.html`;
- `templates/cabinet/includes/_paid_plan_picker.html`.

Добавить:

- показ реального баланса покупателя;
- предупреждение, если не хватает средств;
- ссылка на пополнение;
- цены показывать в ₽, не в коинах.

### Tests

Файл: `wallets/tests.py` или новый `cabinet/tests/test_paid_predictions_real_balance.py`.

Проверить:

- покупатель с балансом 1000 ₽ покупает подписку 990 ₽;
- у покупателя баланс 10 ₽;
- у каппера начисляется `capper_income`;
- создаются две транзакции:
  - `PAID_PREDICTION_PURCHASE` у покупателя отрицательная;
  - `SUBSCRIPTION_INCOME` у каппера положительная;
- продление создает новую payment row и списывает еще раз.

## Этап 6. Турнирные призы: закрепить текущую логику

### Уже правильно

Файл: `tournaments/services/leaderboard.py`.

При финализации:

```python
credit_real_balance(
    result.participant.user,
    result.prize_amount,
    RealBalanceTransaction.Kind.TOURNAMENT_PRIZE,
    related_obj=tournament,
)
```

### Что проверить/доделать

1. Админка турниров:
   - `tournaments/admin.py`;
   - цены/призы должны подписываться как ₽.

2. Templates:
   - `templates/tournaments/detail.html`;
   - `templates/cabinet/_expert_public_tournaments.html`;
   - `templates/cabinet/profile_earnings.html`;
   - `templates/cabinet/expert_profile_performance.html`.

3. Не должно быть coin icon рядом с prize_amount.

Проверка:

```bash
rg -n "prize_amount|prize_first|prize_second|prize_third|coin-amount|coin_icon" tournaments templates/cabinet templates/tournaments
```

### Tests

Добавить/обновить тест:

- финализация турнира начисляет `RealBalanceTransaction.Kind.TOURNAMENT_PRIZE`;
- не создается `CoinTransaction`;
- профиль доходов показывает турнирный приз в рублях.

## Этап 7. Админка: единый денежный учет

### Файл: `wallets/admin.py`

Проверить и обновить:

- `CapperRealBalanceAdmin`;
- `RealBalanceTransactionAdmin`;
- фильтры по новым kind:
  - `VIP_PURCHASE`;
  - `PAID_PREDICTION_PURCHASE`;
  - `SUBSCRIPTION_INCOME`;
  - `TOURNAMENT_PRIZE`;
- добавить поиск по `user__username`, `related_model`, `related_id`;
- сделать `amount` визуально понятным:
  - отрицательные списания;
  - положительные начисления.

### Файл: `cabinet/admin.py`

`VipPlanAdmin`:

- показывать `price_rub`;
- убрать акцент с `price_coins`.

`UserVipSubscriptionAdmin`:

- добавить `plan`, `starts_at`, `ends_at`, `source`, `is_active`;
- фильтр `source`;
- readonly для дат создания.

### Админ dashboard

Файлы:

- `cappers/admin_dashboard.py`;
- `templates/admin/index.html`;
- `templates/admin/includes/quick_actions.html`.

Добавить быстрые действия:

- “VIP-тарифы” -> `admin:cabinet_vipplan_changelist`;
- “Реальные транзакции” -> `admin:wallets_realbalancetransaction_changelist`;
- “Заявки на вывод” -> фильтр `kind=withdrawal_request&status=pending`.

## Этап 8. Страницы и тексты, где нужно заменить коины на рубли

### Команда аудита

```bash
rg -n "VIP|vip|price_coins|coin|коин|coins|coin-amount|coin_icon|paid_predictions|subscription|prize" templates cabinet front game tournaments wallets
```

### Точно проверить

1. VIP:
   - `cabinet/vip.py`
   - `cabinet/vip_views.py`
   - `cabinet/tests/test_vip_service.py`
   - `cabinet/tests/test_vip_status.py`
   - `templates/cabinet/profile.html`
   - `templates/cabinet/_profile_settings.html`
   - `templates/game/rich_prediction_form.html`

2. Платные прогнозы:
   - `cabinet/paid_predictions.py`
   - `cabinet/views.py::subscribe_paid_predictions_view`
   - `templates/cabinet/paid_predictions_checkout.html`
   - `templates/modals/expert_paid_subscribe.html`
   - `templates/cabinet/includes/_paid_plan_picker.html`
   - `cabinet/tests` / `wallets/tests.py`

3. Турниры:
   - `tournaments/models.py`
   - `tournaments/admin.py`
   - `tournaments/services/leaderboard.py`
   - `templates/tournaments/detail.html`
   - `templates/cabinet/_expert_public_tournaments.html`
   - `cabinet/earnings_views.py`

4. Баланс/профиль:
   - `wallets/views.py`
   - `templates/wallets/top_up.html`
   - `cabinet/views.py`
   - `templates/cabinet/profile.html`
   - `templates/cabinet/profile_earnings.html`
   - `front/static/front/css/main.css`

## Этап 9. Пополнение реального баланса

Сейчас `wallets/views.top_up_balance` показывает покупку коинов и реальный баланс каппера, но реальное пополнение пока не подключено.

Для тестового/ручного сценария:

### Файл: `wallets/views.py`

В `real_balance_action` добавить action:

```python
if action == "deposit":
    credit_real_balance(
        request.user,
        amount,
        RealBalanceTransaction.Kind.REAL_DEPOSIT,
        note="Тестовое пополнение реального баланса",
    )
```

Но это опасно для продакшена. Лучше:

- для пользователя показывать “пополнение будет доступно после платежного сценария”;
- для разработки/админки пополнять через `wallets/admin.py`;
- либо сделать deposit только если `settings.DEBUG`.

Решение выбрать перед реализацией.

## Этап 10. Тестовый чеклист

### Django checks

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
```

### Точечные тесты

```bash
python manage.py test cabinet.tests.test_vip_service
python manage.py test cabinet.tests.test_vip_status
python manage.py test wallets.tests
python manage.py test tournaments.tests
```

Если локально снова будет проблема `pgbouncer`, зафиксировать это в отчете.

### Ручная проверка

1. Каппер без VIP:
   - открыть `/cabinet/vip/`;
   - увидеть тарифы;
   - увидеть реальный баланс;
   - при нехватке денег получить ошибку и ссылку пополнения.

2. Каппер с балансом:
   - купить тариф;
   - VIP активен;
   - видно “осталось X дней”;
   - создана `RealBalanceTransaction` с `VIP_PURCHASE` и отрицательной суммой.

3. Каппер с активным VIP:
   - покупает еще тариф;
   - новый период начинается после текущего `ends_at`;
   - страница показывает обновленную дату окончания.

4. Пользователь покупает платные прогнозы:
   - списание с реального баланса покупателя;
   - доход капперу;
   - доступ к платным прогнозам открыт.

5. Турнир:
   - финализация начисляет приз на реальный баланс;
   - в профиле доходов приз отображается в ₽.

## Рекомендуемый порядок внедрения

1. Добавить `price_rub` в `VipPlan` и админку.
2. Добавить `debit_real_balance` и новые `RealBalanceTransaction.Kind`.
3. Перевести `purchase_vip` на реальный баланс.
4. Сделать страницу `/cabinet/vip/`.
5. Обновить все VIP CTA на новую страницу.
6. Добавить модель платежа платной подписки и списание покупателя.
7. Проверить/почистить турнирные призы и отображение ₽.
8. Обновить админку и quick actions.
9. Добавить тесты.
10. Пройти аудит `rg` по coin/коин/VIP/subscription/prize.

## Важные риски

- Нельзя просто переименовать все “коины” в “рубли”: ставки прогнозов и игровые расчеты сейчас используют `CoinWallet`, это отдельная внутренняя экономика.
- `CapperRealBalance` сейчас связан с каппером, но покупки платных прогнозов делает обычный пользователь. Нужно решить, становится ли реальный баланс общим пользовательским балансом.
- У `RealBalanceTransaction` unique constraint по `related_obj`; для продлений подписок нужна отдельная payment-модель, иначе повторное продление может не создать новую транзакцию.
- VIP покупка сейчас JSON-only. Для новой страницы лучше добавить обычный HTML POST с `messages`, а JSON оставить для будущего AJAX.
