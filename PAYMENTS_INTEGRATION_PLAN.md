# План интеграции платёжных систем: CloudPayments + NOWPayments (Factory Method)

Дата: 2026-10-06. Ветка: `development`.

Цель: подключить приём оплат картами (CloudPayments, RUB) и криптовалютой (NOWPayments) через единый платёжный сервис. Конкретный провайдер создаётся фабрикой (паттерн **Factory Method**). Клиентский код (checkout, вебхуки, сверка) работает только с общим интерфейсом и не знает, какая платёжка под ним.

> ⚠️ Детали API CloudPayments (имена эндпоинтов, коды ответа, заголовки подписи, список IP, формат чека) указаны по документации `developers.cloudpayments.ru`. Перед реализацией их нужно сверить с актуальной версией: в этой среде сайт был недоступен. Такие места помечены **[сверить]**.

---

## 1. Что сейчас продаётся и где точки интеграции

| Товар | Модель | Как оплачивается сейчас | Точка интеграции |
|---|---|---|---|
| Пакет коинов | `wallets.CoinPackage` (`price_rub`, `coins`, `bonus_coins`) | Заглушка: «будет доступна после подключения платежного сценария» | `wallets/views.py:top_up_balance` (POST) |
| Платная подписка на каппера | `cabinet.AnalystPaidPlan` → `AnalystPaidSubscription` + `AnalystPaidSubscriptionPayment` | Списание с реального баланса (`cabinet/paid_predictions.py:subscribe_to_paid_predictions`) | `cabinet:paid_predictions_subscribe` |
| VIP-тариф каппера | `cabinet.VipPlan` → `UserVipSubscription` | Списание с реального баланса (`cabinet/vip.py:purchase_vip`) | `cabinet:vip_purchase` |
| (план) Отдельный прогноз в витрине | — | — | Будущая витрина каппера |

Главная проблема текущей модели: **читатель не может пополнить реальный баланс**, поэтому платную подписку фактически купить нельзя (см. `CODE_AUDIT.md`, п. 1.8).

### Рекомендуемая модель: прямая оплата товара

- Каждая покупка создаёт `Payment` на конкретный товар. После подтверждения провайдером товар выдаётся (fulfillment).
- Реальный баланс остаётся только для **дохода каппера** (подписки, призы, рефералы) и вывода. Хранить деньги пользователей на «кошельке» не нужно: так меньше регуляторных рисков (электронные деньги) и проще возвраты.
- Покупка подписки или VIP «с реального баланса» для капперов остаётся вторым способом оплаты.

---

## 2. Бизнес-решения до начала разработки

1. **Юрлицо и чеки 54-ФЗ.** Приём карт от физлиц в РФ требует онлайн-чеков. CloudPayments умеет передавать чек через CloudKassir (`CustomerReceipt` в `JsonData`) **[сверить]**. Нужны система налогообложения, ставка НДС и признаки предмета и способа расчёта.
2. **Валюта для крипты.** Цены в БД хранятся в рублях. Для NOWPayments нужно выбрать фиатную валюту счёта (`price_currency`), обычно `usd`. RUB использовать, только если он есть в списке поддерживаемых для аккаунта. Курс RUB → USD фиксируется в момент создания платежа и сохраняется в снимке.
3. **Холд дохода каппера.** Доход с подписки сейчас сразу доступен для вывода. Карточные платежи могут быть оспорены (chargeback), поэтому рекомендуется холд 7–14 дней: `PENDING` → `AVAILABLE`.
4. **Политика возвратов.** Решить, можно ли вернуть деньги за потраченные коины, как прекращается подписка при возврате и что происходит с долей каппера.
5. **Реферальный процент.** Считать его от комиссии площадки, а не от полной цены. Иначе платёж может стать убыточным (`CODE_AUDIT.md`, п. 1.9).
6. **Коины и денежные турниры.** Если коины продаются за деньги, а в турнирах с денежными призами побеждает тот, у кого больше коинов, нужна юридическая проверка (признаки азартной игры). Варианты: фиксированная ставка или отдельный банк в денежных турнирах, либо турнирные призы без денежного эквивалента.
7. **Минимальная сумма для крипты.** У NOWPayments есть минимальные суммы по монетам (`GET /v1/min-amount`). Дешёвые пакеты коинов криптой не оплатить, поэтому способ оплаты нужно скрывать ниже порога.

---

## 3. Архитектура

Новое приложение `payments`. Структура повторяет существующий паттерн провайдеров данных `game/services/providers/` (`BaseSportsProvider` → `NeurokeffSportsProvider`).

```text
payments/
  __init__.py
  apps.py
  models.py                  # Payment, PaymentEvent
  admin.py                   # read-only админка + действия «сверить», «повторить выдачу», «возврат»
  urls.py
  views.py                   # checkout, return-страница, статус, вебхуки (csrf_exempt)
  tasks.py                   # fulfill_payment_task, reconcile_pending_payments, expire_stale_payments
  services/
    __init__.py
    checkout.py              # start_checkout(): товар → снимок → Payment → провайдер → redirect
    processing.py            # apply_provider_event(): блокировка, проверка суммы, смена статуса
    fulfillment.py           # fulfill_payment(): выдача товара по purpose (идемпотентно)
    refunds.py               # reverse_payment(): откат выдачи при возврате
    providers/
      __init__.py
      base.py                # PaymentProvider (ABC), CheckoutSession, ProviderEvent, ошибки
      factory.py             # PaymentProviderFactory — фабрика провайдеров
      cloudpayments.py       # CloudPaymentsProvider
      nowpayments.py         # NOWPaymentsProvider
  tests/
    test_factory.py
    test_cloudpayments.py
    test_nowpayments.py
    test_processing.py
    test_fulfillment.py
```

HTTP-клиент: `urllib.request`, как в `game/services/providers/neurokeff.py`. Новая зависимость не нужна.

---

## 4. Модели

### 4.1 `Payment`

```python
class Payment(models.Model):
    class Provider(models.TextChoices):
        CLOUDPAYMENTS = "cloudpayments", "CloudPayments (карта)"
        NOWPAYMENTS = "nowpayments", "NOWPayments (крипто)"

    class Purpose(models.TextChoices):
        COIN_PACKAGE = "coin_package", "Пакет коинов"
        PAID_SUBSCRIPTION = "paid_subscription", "Платная подписка"
        VIP_PLAN = "vip_plan", "VIP-тариф"

    class Status(models.TextChoices):
        CREATED = "created", "Создан"
        PENDING = "pending", "Ожидает оплаты"
        PROCESSING = "processing", "Обрабатывается"        # крипта: confirming/confirmed/sending
        PARTIALLY_PAID = "partially_paid", "Оплачен частично"
        SUCCEEDED = "succeeded", "Оплачен"
        FAILED = "failed", "Ошибка оплаты"
        CANCELED = "canceled", "Отменён"
        EXPIRED = "expired", "Истёк"
        REFUNDED = "refunded", "Возвращён"

    # BigAutoField PK: CoinTransaction/RealBalanceTransaction.related_id — это BigInteger,
    # UUID туда не поместится. Наружу отдаём только public_id.
    public_id = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)  # = InvoiceId / order_id
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments")
    provider = models.CharField(max_length=32, choices=Provider.choices, db_index=True)
    purpose = models.CharField(max_length=32, choices=Purpose.choices, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED, db_index=True)

    amount = models.DecimalField(max_digits=12, decimal_places=2)        # сумма к оплате в валюте провайдера
    currency = models.CharField(max_length=8, default="RUB")
    amount_rub = models.DecimalField(max_digits=12, decimal_places=2)    # базовая цена товара в рублях
    product_snapshot = models.JSONField(default=dict)                    # см. ниже

    coin_package = models.ForeignKey("wallets.CoinPackage", null=True, blank=True, on_delete=models.SET_NULL)
    paid_plan = models.ForeignKey("cabinet.AnalystPaidPlan", null=True, blank=True, on_delete=models.SET_NULL)
    vip_plan = models.ForeignKey("cabinet.VipPlan", null=True, blank=True, on_delete=models.SET_NULL)

    external_id = models.CharField(max_length=64, blank=True)            # CP TransactionId / NP payment_id
    external_invoice_id = models.CharField(max_length=64, blank=True)    # CP order Id / NP invoice id
    checkout_url = models.URLField(max_length=1000, blank=True)
    paid_amount = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    paid_currency = models.CharField(max_length=16, blank=True)
    is_test = models.BooleanField(default=False)
    failure_reason = models.CharField(max_length=255, blank=True)
    provider_payload = models.JSONField(default=dict, blank=True)        # последний ответ/вебхук

    expires_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_id"],
                condition=~Q(external_id=""),
                name="unique_payment_provider_external_id",
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive"),
        ]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["user", "created_at"]),
        ]
```

**Снимок товара (`product_snapshot`)** фиксирует условия покупки в момент оплаты. Выдача идёт **только по снимку**, даже если админ потом выключит пакет или изменит цену. Это устраняет ошибку из `CODE_AUDIT.md`, п. 2.4.

```json
// coin_package
{"package_id": 3, "title": "Старт", "coins": 1000, "bonus_coins": 100, "price_rub": "499.00"}
// paid_subscription
{"analyst_id": 42, "plan_id": 7, "plan_title": "30 дней", "duration_days": 30, "price_rub": "990.00",
 "platform_fee_percent": "20.00"}
// vip_plan
{"plan_id": 2, "title": "VIP 30", "duration_days": 30, "price_rub": "1490.00", "switch": false}
// для NOWPayments дополнительно
{"fx": {"from": "RUB", "to": "USD", "rate": "0.0108", "fixed_at": "2026-10-06T12:00:00Z"}}
```

### 4.2 `PaymentEvent` — журнал вебхуков

```python
class PaymentEvent(models.Model):
    provider = models.CharField(max_length=32, db_index=True)
    payment = models.ForeignKey(Payment, null=True, blank=True, on_delete=models.PROTECT, related_name="events")
    event_type = models.CharField(max_length=32)            # check/pay/fail/refund/cancel/ipn/reconcile
    dedup_key = models.CharField(max_length=128)            # provider-specific ключ идемпотентности
    external_id = models.CharField(max_length=64, blank=True)
    payload = models.JSONField(default=dict)
    signature_valid = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "dedup_key"], name="unique_payment_event_dedup"),
        ]
```

### 4.3 Изменения в существующих моделях

- `cabinet.AnalystPaidSubscriptionPayment`: добавить `payment = OneToOneField("payments.Payment", null=True, on_delete=PROTECT)` и `source` (`real_balance` / `external`).
- `wallets.CoinTransaction.Kind`: добавить `PACKAGE_REFUND`.
- `wallets.RealBalanceTransaction`: добавить `available_at` (для холда дохода каппера) и вид `SUBSCRIPTION_INCOME_REVERSAL`.
- Финансовые FK на пользователя перевести на `on_delete=PROTECT` (`CODE_AUDIT.md`, п. 1.10).

### 4.4 Машина состояний

```text
CREATED ──► PENDING ──► PROCESSING ──► SUCCEEDED ──► REFUNDED
               │  ▲          │              ▲
               │  └── FAILED ┘ (CloudPayments: можно повторить оплату того же заказа)
               ├──► PARTIALLY_PAID ──► SUCCEEDED (доплата) / EXPIRED
               ├──► CANCELED
               └──► EXPIRED ──► SUCCEEDED (поздний крипто-платёж → флаг ручной проверки)
```

Правила:
- `SUCCEEDED` нельзя понизить, кроме как в `REFUNDED`.
- Любой незавершённый статус может перейти в `SUCCEEDED`: успех всегда побеждает.
- Переход выполняется только под `select_for_update()` строки `Payment`.
- Таблица допустимых переходов — константа `ALLOWED_TRANSITIONS` в `processing.py`. Недопустимый переход логируется и пропускается, без исключения.

---

## 5. Factory Method: интерфейс и фабрика

### 5.1 Абстракция провайдера — `payments/services/providers/base.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import ClassVar


class PaymentProviderError(Exception):
    """Провайдер недоступен или вернул ошибку."""


class InvalidSignature(PaymentProviderError):
    """Подпись вебхука не прошла проверку."""


class PaymentProviderDisabled(PaymentProviderError):
    """Провайдер выключен в настройках."""


@dataclass(frozen=True)
class CheckoutSession:
    redirect_url: str = ""
    external_invoice_id: str = ""
    expires_at: datetime | None = None
    widget_params: dict = field(default_factory=dict)   # для JS-виджета CloudPayments (опционально)


@dataclass(frozen=True)
class ProviderEvent:
    event_type: str                 # check / pay / fail / refund / cancel / ipn / reconcile
    payment_public_id: str          # наш Payment.public_id (InvoiceId / order_id)
    status: str                     # Payment.Status
    external_id: str = ""
    amount: Decimal | None = None   # сумма в валюте счёта
    currency: str = ""
    paid_amount: Decimal | None = None
    paid_currency: str = ""
    is_test: bool = False
    dedup_key: str = ""
    failure_reason: str = ""
    raw: dict = field(default_factory=dict)


class PaymentProvider(ABC):
    """Контракт платёжного провайдера. Клиентский код зависит только от него."""

    code: ClassVar[str]
    title: ClassVar[str]

    @classmethod
    @abstractmethod
    def from_settings(cls) -> "PaymentProvider":
        """Фабричный метод: собрать провайдера из django.conf.settings."""

    @abstractmethod
    def is_enabled(self) -> bool: ...

    @abstractmethod
    def supports(self, payment) -> bool:
        """Можно ли оплатить этот платёж (валюта, минимальная сумма)."""

    @abstractmethod
    def create_checkout(self, payment, *, success_url: str, fail_url: str, webhook_url: str) -> CheckoutSession: ...

    @abstractmethod
    def verify_signature(self, request) -> None:
        """Проверить подпись по сырому request.body. Ошибка → InvalidSignature."""

    @abstractmethod
    def parse_webhook(self, request, *, event_type: str) -> ProviderEvent: ...

    @abstractmethod
    def fetch_status(self, payment) -> ProviderEvent | None:
        """Запросить актуальный статус у провайдера (сверка, защита от потерянных вебхуков)."""

    @abstractmethod
    def webhook_response(self, *, accepted: bool, code: int = 0):
        """HTTP-ответ в формате, который ожидает провайдер."""

    def refund(self, payment, amount: Decimal | None = None) -> None:
        raise PaymentProviderError(f"{self.title}: автоматический возврат не поддерживается.")
```

### 5.2 Фабрика — `payments/services/providers/factory.py`

Явный словарь вместо магии регистрации через импорт: проще читать и отлаживать (см. `Agent.md`).

```python
from django.conf import settings

from .base import PaymentProvider, PaymentProviderDisabled, PaymentProviderError
from .cloudpayments import CloudPaymentsProvider
from .nowpayments import NOWPaymentsProvider


class UnknownPaymentProvider(PaymentProviderError):
    pass


class PaymentProviderFactory:
    _providers: dict[str, type[PaymentProvider]] = {
        CloudPaymentsProvider.code: CloudPaymentsProvider,
        NOWPaymentsProvider.code: NOWPaymentsProvider,
    }

    @classmethod
    def create(cls, code: str) -> PaymentProvider:
        provider_cls = cls._providers.get(code)
        if provider_cls is None:
            raise UnknownPaymentProvider(f"Неизвестный платёжный провайдер: {code}")
        provider = provider_cls.from_settings()          # фабричный метод конкретного класса
        if code not in settings.PAYMENTS_ENABLED_PROVIDERS or not provider.is_enabled():
            raise PaymentProviderDisabled(f"Провайдер {code} выключен.")
        return provider

    @classmethod
    def available_for(cls, payment) -> list[PaymentProvider]:
        """Провайдеры, которыми можно оплатить конкретный платёж (для кнопок на странице оплаты)."""
        result = []
        for code in settings.PAYMENTS_ENABLED_PROVIDERS:
            try:
                provider = cls.create(code)
            except PaymentProviderError:
                continue
            if provider.supports(payment):
                result.append(provider)
        return result
```

Как это использует клиентский код:

```python
provider = PaymentProviderFactory.create(payment.provider)
session = provider.create_checkout(payment, success_url=..., fail_url=..., webhook_url=...)
```

Чтобы добавить третью платёжку (ЮKassa, Stripe и т. п.), достаточно нового класса и одной строки в `_providers`. Checkout, вебхуки, сверка и выдача товара не меняются.

---

## 6. CloudPayments (карты, RUB)

### 6.1 Настройки

```env
CLOUDPAYMENTS_PUBLIC_ID=
CLOUDPAYMENTS_API_SECRET=
CLOUDPAYMENTS_API_URL=https://api.cloudpayments.ru
CLOUDPAYMENTS_ALLOW_TEST_MODE=False          # в production тестовые платежи не выдают товар
CLOUDPAYMENTS_RECEIPTS_ENABLED=True          # чеки 54-ФЗ через CloudKassir
CLOUDPAYMENTS_TAXATION_SYSTEM=               # [сверить] код СНО
CLOUDPAYMENTS_VAT=                           # [сверить] ставка НДС для товара
CLOUDPAYMENTS_ORDER_TTL_MINUTES=60
```

### 6.2 Создание оплаты

Есть два варианта, и оба укладываются в `CheckoutSession`:

**A. Ссылка на оплату (рекомендуется первым этапом, единый redirect-flow с NOWPayments).**
`POST {API_URL}/orders/create`, HTTP Basic (`PublicId` : `ApiSecret`) **[сверить]**:

```json
{
  "Amount": 499.00,
  "Currency": "RUB",
  "Description": "Пакет коинов «Старт»",
  "InvoiceId": "<payment.public_id>",
  "AccountId": "<user.pk>",
  "Email": "<user.email>",
  "RequireConfirmation": false,
  "SendEmail": false,
  "SuccessRedirectUrl": "https://capper-hub.com/payments/<public_id>/return/",
  "FailRedirectUrl": "https://capper-hub.com/payments/<public_id>/return/",
  "JsonData": {"CloudPayments": {"CustomerReceipt": {"...": "чек 54-ФЗ"}}}
}
```

В ответе приходит `Model.Url` (это `checkout_url`) и `Model.Id` (это `external_invoice_id`).

**B. JS-виджет (улучшение UX, без ухода с сайта).** Сервер отдаёт `widget_params` (`publicId`, `amount`, `currency`, `invoiceId`, `accountId`, `email`, `description`, `data`). Скрипт виджета подключается в отдельном статическом JS-файле, без inline-кода (правила `Agent.md`).

### 6.3 Вебхуки (уведомления)

В личном кабинете CloudPayments нужно указать URL для каждого типа уведомлений:

| Уведомление | URL | Действие |
|---|---|---|
| Check | `/payments/webhooks/cloudpayments/check/` | Проверка **до** списания денег: заказ существует, статус PENDING/FAILED, сумма, валюта и AccountId совпадают, срок не истёк, товар ещё доступен |
| Pay | `/payments/webhooks/cloudpayments/pay/` | → `SUCCEEDED`, выдача товара |
| Fail | `/payments/webhooks/cloudpayments/fail/` | → `FAILED` (не финальный, пользователь может повторить) |
| Refund | `/payments/webhooks/cloudpayments/refund/` | → `REFUNDED`, откат выдачи |
| Cancel / Confirm | `/payments/webhooks/cloudpayments/cancel/` | Для двухстадийной оплаты (пока не используется) |

**Подпись [сверить].** Заголовок `Content-HMAC` = `Base64(HMAC-SHA256(сырое тело запроса, ApiSecret))`. Проверять по `request.body` **до** парсинга, через `hmac.compare_digest`:

```python
def verify_signature(self, request) -> None:
    received = request.headers.get("Content-HMAC", "")
    expected = base64.b64encode(
        hmac.new(self.api_secret.encode(), request.body, hashlib.sha256).digest()
    ).decode()
    if not received or not hmac.compare_digest(received, expected):
        raise InvalidSignature("CloudPayments: неверная подпись уведомления.")
```

**Формат тела:** по умолчанию `application/x-www-form-urlencoded`, в настройках можно включить JSON. Парсер должен поддерживать оба варианта.

**Ответ [сверить].** HTTP 200, `{"code": 0}`. Коды отказа для Check: `10` — неизвестный InvoiceId, `11` — неверный AccountId, `12` — неверная сумма, `13` — платёж не может быть принят (уже оплачен или отменён, товар недоступен), `20` — заказ просрочен.

**Сопоставление полей:** `InvoiceId` → `payment_public_id`; `TransactionId` → `external_id`; `Amount` и `Currency` сверяются со снимком; `TestMode=1` → `is_test=True`, и в production при `CLOUDPAYMENTS_ALLOW_TEST_MODE=False` товар не выдаётся; `Reason`/`ReasonCode` → `failure_reason`. Ключ идемпотентности: `dedup_key = f"{event_type}:{TransactionId}"`.

Check-уведомление особенно полезно: оно позволяет **отклонить** оплату, если между созданием заказа и оплатой каппер отключил платные прогнозы или тариф стал недоступен. Деньги тогда не списываются вовсе.

### 6.4 Сверка и возвраты [сверить]

- `fetch_status()`: `POST {API_URL}/v2/payments/find` с `{"InvoiceId": "<public_id>"}`. Статус `Completed` → `SUCCEEDED`, `Declined` → `FAILED`.
- `refund()`: `POST {API_URL}/payments/refund` с `{"TransactionId": ..., "Amount": ...}`. Итоговый статус подтверждает вебхук Refund.
- IP-адреса уведомлений CloudPayments (allowlist как дополнительная защита) нужно взять из актуальной документации **[сверить]**.

---

## 7. NOWPayments (криптовалюта)

### 7.1 Настройки

```env
NOWPAYMENTS_API_KEY=
NOWPAYMENTS_IPN_SECRET=
NOWPAYMENTS_API_URL=https://api.nowpayments.io/v1          # sandbox: https://api-sandbox.nowpayments.io/v1
NOWPAYMENTS_PRICE_CURRENCY=usd                             # валюта счёта; RUB — только если поддерживается аккаунтом
NOWPAYMENTS_RUB_RATE_SOURCE=cbr                            # откуда брать курс RUB → price_currency
NOWPAYMENTS_IS_FIXED_RATE=True
NOWPAYMENTS_IS_FEE_PAID_BY_USER=False
NOWPAYMENTS_MIN_PRICE_RUB=500                              # ниже — кнопку крипты не показывать
NOWPAYMENTS_INVOICE_TTL_HOURS=24
```

### 7.2 Создание счёта

`POST {API_URL}/invoice`, заголовок `x-api-key: <API_KEY>`:

```json
{
  "price_amount": 5.39,
  "price_currency": "usd",
  "order_id": "<payment.public_id>",
  "order_description": "Coins package Start",
  "ipn_callback_url": "https://capper-hub.com/payments/webhooks/nowpayments/",
  "success_url": "https://capper-hub.com/payments/<public_id>/return/",
  "cancel_url": "https://capper-hub.com/payments/<public_id>/return/",
  "partially_paid_url": "https://capper-hub.com/payments/<public_id>/return/",
  "is_fixed_rate": true,
  "is_fee_paid_by_user": false
}
```

В ответе приходит `id` (это `external_invoice_id`) и `invoice_url` (это `checkout_url`). Монету пользователь выбирает на странице NOWPayments.

`order_description` лучше писать латиницей. Кириллица может по-разному сериализоваться при проверке подписи IPN (см. ниже).

### 7.3 IPN (вебхук)

- URL: `/payments/webhooks/nowpayments/`, тело — JSON.
- Подпись: заголовок `x-nowpayments-sig` = `HMAC-SHA512(IPN_SECRET, JSON-строка тела с ключами, отсортированными по алфавиту)`, в hex.

```python
def verify_signature(self, request) -> None:
    received = request.headers.get("x-nowpayments-sig", "")
    try:
        payload = json.loads(request.body)
    except ValueError as exc:
        raise InvalidSignature("NOWPayments: некорректный JSON.") from exc
    message = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected = hmac.new(self.ipn_secret.encode(), message.encode(), hashlib.sha512).hexdigest()
    if not received or not hmac.compare_digest(received, expected):
        raise InvalidSignature("NOWPayments: неверная подпись IPN.")
```

Подводные камни, которые нужно закрыть тестами на реальных IPN из sandbox:
- `sort_keys=True` сортирует и вложенные объекты (например `fee`). Это совпадает с рекурсивной сортировкой из документации NOWPayments.
- Сериализация в JS (`JSON.stringify`) и Python различается для кириллицы (`ensure_ascii`) и для чисел вида `1e-7`.

**Поэтому подпись — только первый фильтр. Статус и суммы для выдачи товара всегда перепроверяются запросом** `GET {API_URL}/payment/{payment_id}`. Сервер NOWPayments — единственный источник правды.

### 7.4 Сопоставление статусов

| `payment_status` NOWPayments | `Payment.Status` | Действие |
|---|---|---|
| `waiting` | `PENDING` | — |
| `confirming`, `confirmed`, `sending` | `PROCESSING` | Показать «ждём подтверждений сети» |
| `partially_paid` | `PARTIALLY_PAID` | Товар **не** выдаётся, ручная проверка или доплата |
| `finished` | `SUCCEEDED` | Выдача товара |
| `failed` | `FAILED` | — |
| `refunded` | `REFUNDED` | Откат выдачи |
| `expired` | `EXPIRED` | — |

- Ключ идемпотентности: `dedup_key = f"{payment_id}:{payment_status}"`.
- На один счёт может прийти несколько `payment_id` (пользователь сменил монету). Связь с заказом идёт через `order_id`. В `Payment.external_id` записывается тот `payment_id`, который дошёл до `finished`.
- Переплата (`actually_paid > pay_amount`) обрабатывается как обычная оплата, разница пишется в лог.
- Автоматического возврата нет: `refund()` выбрасывает исключение, возвраты делаются вручную в кабинете NOWPayments.

---

## 8. Сценарии

### 8.1 Checkout

```text
Пользователь → POST /payments/checkout/ {purpose, object_id, provider}
  └─ start_checkout()
       1. Проверить товар (активен, цена > 0, каппер принимает подписки, не сам на себя и т. д.)
       2. Лимит: не больше N незавершённых платежей на пользователя
       3. Снимок товара + amount_rub (+ курс для крипты)
       4. Payment(status=CREATED)
       5. provider = PaymentProviderFactory.create(provider_code)
       6. session = provider.create_checkout(payment, success_url, fail_url, webhook_url)
       7. Payment → PENDING, сохранить checkout_url / external_invoice_id / expires_at
  └─ redirect(session.redirect_url)   (или render с widget_params)
```

Return-страница `/payments/<public_id>/return/` **ничего не выдаёт**. Она показывает статус и опрашивает `/payments/<public_id>/status/`.

### 8.2 Вебхук

```python
@csrf_exempt
@require_POST
def provider_webhook(request, provider_code: str, event_type: str = "ipn"):
    provider = PaymentProviderFactory.create(provider_code)
    try:
        provider.verify_signature(request)
    except InvalidSignature:
        logger.warning("Invalid %s signature from %s", provider_code, request.META.get("HTTP_X_REAL_IP"))
        return HttpResponseForbidden()

    event = provider.parse_webhook(request, event_type=event_type)
    result = apply_provider_event(provider_code, event)   # транзакция + журнал PaymentEvent
    return provider.webhook_response(accepted=result.accepted, code=result.code)
```

`apply_provider_event()`:
1. `PaymentEvent.get_or_create(provider, dedup_key)`. Если событие уже обработано, ответить «принято» и выйти.
2. `Payment.objects.select_for_update().get(public_id=...)`.
3. Сверить сумму и валюту со снимком. При расхождении — статус не менять, записать ошибку, уведомить админа.
4. Проверить переход по `ALLOWED_TRANSITIONS` и сменить статус.
5. Если новый статус `SUCCEEDED`: выставить `paid_at` и вызвать `transaction.on_commit(lambda: fulfill_payment_task.delay(payment.pk))`.
6. Если новый статус `REFUNDED`: `on_commit(reverse_payment_task.delay(...))`.

Выдача товара идёт в отдельной задаче, поэтому ошибка выдачи не превращается в «вечный» ретрай вебхука у провайдера. Повторную выдачу обеспечивают ретраи Celery и сверка.

### 8.3 Выдача товара (`fulfillment.py`)

Диспетчер — обычный словарь, без лишних абстракций:

```python
FULFILLERS = {
    Payment.Purpose.COIN_PACKAGE: fulfill_coin_package,
    Payment.Purpose.PAID_SUBSCRIPTION: fulfill_paid_subscription,
    Payment.Purpose.VIP_PLAN: fulfill_vip_plan,
}


def fulfill_payment(payment_id: int) -> Payment:
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_id)
        if payment.status != Payment.Status.SUCCEEDED or payment.fulfilled_at:
            return payment
        FULFILLERS[payment.purpose](payment)        # идемпотентно: related_obj=payment
        payment.fulfilled_at = timezone.now()
        payment.save(update_fields=["fulfilled_at", "updated_at"])
    return payment
```

Что нужно переделать в существующих сервисах:

| Сервис | Изменение |
|---|---|
| `wallets/services.py:purchase_coin_package` | Новая функция `fulfill_coin_package(payment)`: `credit_coins(user, coins + bonus_coins, PACKAGE_PURCHASE, related_obj=payment)` по **снимку**, без перепроверки `is_active`. Реферальные начисления считаются от `amount_rub` снимка. |
| `cabinet/paid_predictions.py:subscribe_to_paid_predictions` | Выделить ядро `_grant_paid_subscription(subscriber, analyst, *, price, duration_days, plan, payment=None, source)`. Старая функция = ядро + `debit_real_balance`. Новая `fulfill_paid_subscription(payment)` = ядро без списания. Доход каппера уходит в холд. Реферальный процент считается от комиссии. |
| `cabinet/vip.py:purchase_vip` | Аналогично: ядро `_grant_vip(user, plan, switch)` + две точки входа. |
| `wallets/views.py:top_up_balance` | Вместо заглушки — кнопки провайдеров из `PaymentProviderFactory.available_for(...)` → `start_checkout`. |
| `cabinet/views.py` (checkout подписки), `cabinet/vip_views.py` | Добавить «Оплатить картой / криптой» рядом с оплатой с баланса. |

### 8.4 Возвраты (`refunds.py`)

- **Коины:** списать `PACKAGE_REFUND` в пределах остатка. Если коины уже потрачены, это решает политика из раздела 2 (запрет возврата или частичный возврат).
- **Подписка:** `expires_at = now`. Доход каппера: если ещё в холде — отменить; если уже доступен — `SUBSCRIPTION_INCOME_REVERSAL` (баланс может уйти в минус, тогда нужен «долг» и блокировка вывода). Реферальное начисление откатить.
- **VIP:** деактивировать период.
- Все откаты идемпотентны через `related_obj=payment`.

### 8.5 Фоновые задачи (`payments/tasks.py`)

| Задача | Расписание | Что делает |
|---|---|---|
| `fulfill_payment_task(payment_id)` | по событию | Выдача товара; `autoretry_for`, экспоненциальный backoff |
| `reconcile_pending_payments` | каждые 10 мин | `PENDING`/`PROCESSING` старше 10 мин → `provider.fetch_status()` → `apply_provider_event()`; также `SUCCEEDED` без `fulfilled_at` → повторная выдача |
| `expire_stale_payments` | каждый час | `PENDING` старше TTL → `EXPIRED` |
| `release_held_income` | раз в день | Доход каппера с истёкшим холдом → доступен к выводу |

В `CELERY_BEAT_SCHEDULE` использовать `"options": {"expires": ...}`, а не `expire_seconds` (`CODE_AUDIT.md`, п. 2.3).

---

## 9. Безопасность (чек-лист)

- [ ] Подпись вебхука проверяется по **сырому** `request.body` через `hmac.compare_digest`.
- [ ] Статус и сумма перепроверяются через API провайдера (обязательно для NOWPayments; при сверке — для обоих).
- [ ] Сумма и валюта вебхука сверяются со снимком; при расхождении товар не выдаётся.
- [ ] Идемпотентность: `PaymentEvent(provider, dedup_key)` unique, блокировка строки `Payment`, выдача через `related_obj=payment`.
- [ ] Return URL ничего не выдаёт.
- [ ] `csrf_exempt` стоит только на вебхуках; вебхуки принимают только POST; размер тела ограничен.
- [ ] `public_id` (UUID) используется наружу вместо последовательного id.
- [ ] Тестовые платежи CloudPayments (`TestMode`) в production товар не выдают.
- [ ] Секреты только в `.env`, не попадают в логи и в админку.
- [ ] `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`, иначе `build_absolute_uri()` построит `http://` для return и callback URL (`CODE_AUDIT.md`, п. 1.12).
- [ ] Лимит незавершённых платежей на пользователя и rate-limit на `/payments/checkout/`.
- [ ] Опционально: allowlist IP провайдеров по `X-Real-IP` (nginx его передаёт).
- [ ] Отдельный logger `payments` и алерты на неверную подпись, расхождение суммы и ошибки выдачи.

---

## 10. Админка

- `PaymentAdmin`: всё read-only. Фильтры: провайдер, назначение, статус, дата. Поиск: `public_id`, `external_id`, username, email. Inline со списком `PaymentEvent`.
  - Действия: «Сверить статус у провайдера», «Повторить выдачу» (только `SUCCEEDED` без `fulfilled_at`), «Вернуть платёж» (только CloudPayments, с подтверждением).
- `PaymentEventAdmin`: read-only, без добавления и удаления.

---

## 11. Тесты

- **Фабрика:** неизвестный код → `UnknownPaymentProvider`; выключенный провайдер → `PaymentProviderDisabled`; `available_for()` скрывает NOWPayments ниже минимальной суммы.
- **CloudPayments:** корректная и подделанная подпись (HMAC по фикстуре тела); form-urlencoded и JSON; коды ответа Check (10/11/12/13/20); повтор Pay не выдаёт товар дважды; `TestMode` в production не выдаёт товар.
- **NOWPayments:** подпись с вложенным `fee` и кириллицей; `partially_paid` не выдаёт товар; `finished` выдаёт; IPN без подтверждения через `GET /payment/{id}` не выдаёт.
- **Обработка событий:** таблица переходов; `SUCCEEDED` не понижается; расхождение суммы.
- **Выдача товара:** для каждого назначения — идемпотентность; выключенный пакет всё равно выдаётся по снимку; подписка продлевается от хвоста; доход каппера уходит в холд.
- **Возвраты:** откат коинов, подписки, дохода каппера и реферала.
- **Сверка:** HTTP провайдера мокается (`urllib.request.urlopen`), как в тестах Neurokeff.
- **Ручной E2E:** sandbox NOWPayments и тестовый режим/тестовые карты CloudPayments.

---

## 12. Пошаговый план внедрения

Каждый шаг — отдельный небольшой PR в `development`.

1. **Подготовка (из аудита):** `SECURE_PROXY_SSL_HEADER` и secure-настройки; `PROTECT` на финансовых FK; холд дохода каппера; реферальный процент от комиссии.
2. **Каркас `payments`:** модели `Payment` и `PaymentEvent`, миграции, админка, настройки в `settings.py` и `.env.example`, `PAYMENTS_ENABLED_PROVIDERS=[]` (всё выключено).
3. **Factory Method:** `base.py`, `factory.py`, тесты фабрики.
4. **CloudPayments:** провайдер (orders/create, подпись, парсер, Check/Pay/Fail/Refund), вебхуки, тесты.
5. **Выдача товара:** рефакторинг `purchase_coin_package`, `subscribe_to_paid_predictions`, `purchase_vip` на ядро + точки входа; `fulfillment.py`; задачи `fulfill`, `reconcile`, `expire`; тесты.
6. **UI:** кнопки оплаты на `wallets/top_up`, на checkout подписки и на странице VIP; return-страница со статусом. Стили — только в `main.css`/`mobile.css`, без inline.
7. **Запуск CloudPayments** в production за флагом `PAYMENTS_ENABLED_PROVIDERS=["cloudpayments"]`, сначала на пакетах коинов.
8. **NOWPayments:** провайдер, IPN, перепроверка через API, курс RUB → USD, минимальные суммы, тесты на sandbox → включение.
9. **Возвраты и чеки 54-ФЗ:** `refunds.py`, Refund-вебхук, CloudKassir.
10. **Мониторинг:** алерты, отчёт сверки с выписками провайдеров.

Позже, отдельными этапами:
- автопродление подписок (рекуррентные платежи CloudPayments);
- выплаты капперам через API (выплаты на карту CloudPayments / payouts NOWPayments) вместо ручного подтверждения заявок;
- покупка отдельного прогноза в витрине каппера (новый `Purpose`).

---

## 13. Открытые вопросы к владельцу продукта

1. Кто принимает платежи (ИП, ООО, самозанятый) и нужна ли онлайн-касса (CloudKassir)? Какие СНО и НДС?
2. В какой валюте выставлять крипто-счёт (USD?) и по какому курсу пересчитывать рублёвые цены?
3. Сколько дней холдить доход каппера и какая политика возвратов за коины и подписки?
4. Выплаты капперам: оставить ручное подтверждение или автоматизировать?
5. Сохраняем ли денежные призы в турнирах, где участвуют купленные коины (юридическая проверка)?
6. Нужны ли автопродление подписок и оплата «одним кликом» сохранённой картой?
