# План выноса VIP в отдельную модель

## Решение по app

VIP лучше хранить в `cabinet`, а не в `wallets`.

Причина:

- VIP — это статус пользователя/аналитика и влияет на профиль, рейтинги, баннеры, доступы и отображение;
- `wallets` должен отвечать за оплату, списание коинов/денег и транзакции;
- покупка VIP из `wallets` может вызывать сервис из `cabinet`, который создаёт или продлевает VIP-подписку.

Итоговая граница:

- `cabinet` хранит VIP-тарифы и активные VIP-периоды;
- `wallets` только оплачивает и создаёт транзакцию;
- `User.is_vip` становится property, а не полем.

## Шаг 1: Добавить модели VIP-тарифов и VIP-периодов

В `cabinet/models.py` добавить модели:

- `VipPlan`
  - `title`
  - `duration_days`
  - `price_coins` или `price`
  - `is_active`
  - `order`
  - `created_at`
  - `updated_at`

- `UserVipSubscription`
  - `user`
  - `plan`
  - `starts_at`
  - `ends_at`
  - `duration_days`
  - `source`
  - `is_active`
  - `created_at`
  - `updated_at`

`source` нужен для различения покупки, админской выдачи, рулетки, бонуса.

Добавить индексы:

- `user, starts_at, ends_at`
- `user, is_active, ends_at`
- `ends_at`

## Шаг 2: Перенести `is_vip` в property

В `User` добавить property:

```python
@property
def is_vip(self) -> bool:
    ...
```

Логика:

- пользователь VIP, если есть активная запись `UserVipSubscription`;
- `starts_at <= now < ends_at`;
- `is_active=True`.

Для списков нельзя вызывать property в цикле без queryset-оптимизации. Для массовых страниц добавить аннотацию:

- `is_vip_active=Exists(...)`
- `vip_ends_at=Subquery(...)`
- `vip_activated_at=Subquery(...)`

В шаблонах и карточках использовать уже подготовленное значение, если оно есть.

## Шаг 3: Миграция со старого `AnalystProfile.is_vip`

Сделать data migration:

1. Для всех `AnalystProfile.is_vip=True` создать `UserVipSubscription`.
2. `starts_at` брать из `AnalystProfile.vip_activated_at`, если поле уже есть.
3. Если даты нет, fallback:
   - `AnalystProfile.updated_at`;
   - потом `User.date_joined`.
4. `ends_at` для старых VIP можно временно поставить далеко в будущее или сделать отдельный `source="legacy_admin"`.

После переноса:

- убрать прямую зависимость UI от `AnalystProfile.is_vip`;
- старое поле удалить отдельной миграцией только после проверки всех мест использования.

## Шаг 4: Обновить покупку, админку и выдачу VIP

Добавить сервис в `cabinet`, например:

- `activate_vip(user, plan, source, starts_at=None)`
- `extend_vip(user, days, source)`
- `get_active_vip(user)`

Логика продления:

- если активный VIP уже есть, новый срок начинается от текущего `ends_at`;
- если VIP закончился, новый срок начинается от `timezone.now()`;
- хранить фактические `starts_at`, `ends_at`, `duration_days`.

Обновить:

- админку: управлять `VipPlan` и `UserVipSubscription`;
- покупку VIP: после оплаты создавать/продлевать `UserVipSubscription`;
- рулетку: выдавать VIP через тот же сервис, а не отдельной логикой.

## Шаг 5: Обновить баннеры, рейтинги и шаблоны

Заменить все проверки:

- `analyst_profile.is_vip`
- `request.user.analyst_profile.is_vip`

на:

- `user.is_vip` для одиночного пользователя;
- queryset-аннотацию `is_vip_active` для списков;
- общий helper/service для карточек капперов.

Для `vip-cappers-banner`:

- брать только пользователей с активным VIP;
- сортировать по `starts_at DESC` или `created_at DESC` последней активной VIP-подписки;
- hero-card = последний купивший/получивший VIP;
- нижний список начинается с места `2`;
- показывать `ends_at`, если нужно будет добавить UI срока VIP.

После перехода проверить страницы:

- `/tournaments/`
- `/cappers-table/`
- `/favorites/`
- публичный профиль каппера
- карточки прогнозов
- header/avatar VIP badge

## Шаг 6: Обновить VIP-сторис на странице ленты

На странице `http://127.0.0.1:8000/feed/` в блоке `following-stories-row` нужно показывать всех активных VIP-пользователей.

Что сделать:

1. В `front/feed_views.py` заменить текущий источник сторис на queryset активных VIP:
   - брать пользователей/аналитиков, у которых есть активная `UserVipSubscription`;
   - условия: `is_active=True`, `starts_at <= now`, `ends_at > now`;
   - сортировка: последние купившие VIP первыми, то есть по `starts_at DESC` или `created_at DESC` последней активной подписки.
2. Не использовать `AnalystProfile.is_vip` для этого блока.
3. Для карточек сторис заранее подготовить данные одним queryset:
   - аватар;
   - имя;
   - username;
   - ссылка на публичный профиль;
   - `vip_activated_at`;
   - `vip_ends_at`.
4. Если текущий пользователь уже подписан на VIP-каппера, это не должно скрывать каппера из `following-stories-row`: блок должен показывать именно всех активных VIP.
5. Добавить лимит отображения, если блок горизонтальный:
   - например первые 20-30 активных VIP;
   - остальные могут открываться через страницу всех VIP капперов.

Ожидаемый результат:

- `/feed/` показывает актуальные VIP-сторис;
- новые покупки VIP появляются в начале `following-stories-row`;
- истёкшие VIP автоматически исчезают из блока;
- список не делает N+1 запросов по профилям и аватарам.
