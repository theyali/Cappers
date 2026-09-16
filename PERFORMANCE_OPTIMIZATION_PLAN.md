# План оптимизации медленных публичных страниц

## Проблема

Медленно начали отвечать страницы:

- `/`
- `/predictions/`
- `/feed/`
- `/cappers-table/`
- `/tournaments/`

Основная вероятная причина: на каждый render выполняется много синхронных запросов к БД через глобальные context processors и тяжелые view/services. Из-за этого даже разные страницы получают общий overhead, а страницы с прогнозами и рейтингами дополнительно пересчитывают агрегаты на лету.

Ключевые места:

- `pages/context_processors.py`
- `front/context_processors.py`
- `wallets/context_processors.py`
- `front/home_views.py`
- `front/prediction_catalog_views.py`
- `front/feed_views.py`
- `front/capper_table_service.py`
- `front/expert_ranking.py`
- `tournaments/views.py`

## Шаг 1: Убрать общий overhead из context processors

### Что проверить

В `cappers/settings.py` подключены context processors:

- `front.context_processors.website_settings`
- `pages.context_processors.page_seo`
- `wallets.context_processors.coin_wallet`

Они выполняются почти на каждой HTML-странице.

### Главные риски

`pages.context_processors.page_seo`:

- трогает presence через `touch_user_presence()`
- ищет `PageSEO`
- ищет `adv_banners`
- ищет `promo_banners`
- может делать несколько запросов даже для простых страниц

`front.context_processors.website_settings`:

- грузит `WebsiteSettings`
- грузит footer groups и footer buttons
- проверяет roulette state для авторизованного пользователя
- на главной дополнительно грузит wiki video

`wallets.context_processors.coin_wallet`:

- для авторизованного пользователя вызывает `ensure_coin_wallet()`
- это может быть лишним для страниц, где баланс не нужен в шаблоне

### Что сделать

1. Добавить кеширование для `WebsiteSettings`, footer groups/footer buttons, SEO meta, adv banners и promo banners.
2. Не делать `touch_user_presence()` внутри SEO context processor. Presence лучше вынести в отдельный middleware/helper и обновлять только там, где статус реально нужен.
3. Для `coin_wallet` не делать `ensure_coin_wallet()` на каждой странице. Использовать легкий read-only запрос или кешировать баланс для nav.

### Ожидаемый результат

Все указанные страницы получат меньше базовых SQL-запросов до выполнения своей основной view-логики.

## Шаг 2: Закешировать рейтинги капперов и тяжелые агрегаты

### Что проверить

Самые подозрительные места:

- `front/capper_table_service.py`
- `front/expert_ranking.py`
- `front/home_views.py`

`/cappers-table/` строит рейтинг через `build_capper_table_context()`, который:

- получает публичные профили
- получает месяцы из `CapperMonthlyStat`
- сканирует `sports_data`
- вызывает `rank_experts()`
- внутри рейтинга считает annotate/aggregate по прогнозам
- для каждой строки вызывает `presence_payload(profile.user)`, что может дать N+1 запросы

Главная `/` тоже несколько раз вызывает ranking helpers:

- `ranked_expert_profiles(...)`
- `current_month_top_expert_ids(...)`
- `_best_home_experts(...)`
- `_top_home_experts(...)`

### Что сделать

1. Кешировать результат `rank_experts()` по ключу:
   - `period`
   - `sport_code`
   - `group`
   - `limit`
2. Кешировать `build_capper_table_context()` без user-specific полей.
3. Presence для таблицы капперов получать батчем:
   - одним запросом по `user_id__in`
   - не вызывать `presence_payload()` внутри цикла для каждой строки
4. Инвалидировать кеш рейтингов после пересчета `CapperMonthlyStat`, публикации/обновления прогноза или изменения публичности профиля.

### Ожидаемый результат

`/cappers-table/` и главная перестанут пересчитывать рейтинги на каждый запрос. Время ответа должно стать стабильным даже при росте количества прогнозов и аналитиков.

## Шаг 3: Оптимизировать списки прогнозов и ленту

### Что проверить

Основные файлы:

- `front/prediction_catalog_views.py`
- `front/feed_views.py`
- `front/prediction_views.py`
- `game/views.py`
- `tournaments/views.py`

`/predictions/` и `/feed/` используют:

- `_published_queryset()`
- `_decorate_predictions()`
- `Paginator`
- counts по статусам
- sport tabs
- likes/favorites/following flags
- paid/free predictions

`/feed/` дополнительно делает:

- список подписок
- платные подписки
- sport tabs через union queryset
- counts отдельно для free и paid
- отдельный count для paid predictions
- декорирование free и paid карточек
- author counts и locked paid counts

### Что сделать

1. В `_published_queryset()` и связанных queryset проверить `select_related()` и `prefetch_related()` для:
   - `author`
   - `author__analyst_profile`
   - `predictions`
   - `predictions__match`
   - `predictions__match__sport`
   - `predictions__match__league`
   - teams/odds, если они используются в карточках
2. Убрать N+1 внутри `_decorate_predictions()`:
   - likes/favorites получать одним запросом по списку coupon ids
   - comments/counts не считать отдельно на карточку
   - following ids передавать уже готовым set
3. Для counts/status tabs/sport tabs добавить короткий кеш:
   - 30-120 секунд для `/predictions/`
   - user-specific кеш для `/feed/`, если пользователь авторизован
4. Для `/tournaments/` проверить, нет ли повторного вызова `_latest_predictions()` или тяжелых leaderboard/counts без кеша.

### Ожидаемый результат

`/predictions/`, `/feed/` и `/tournaments/` должны перестать делать повторяющиеся count/aggregate/decorate запросы на каждый заход и на каждую карточку.

## Как замерять

Перед правками и после каждого шага нужно смотреть:

- количество SQL-запросов на страницу
- общее время SQL
- время render
- общее время ответа

Минимальный способ:

- включить Django Debug Toolbar локально
- открыть каждый URL
- записать SQL count и total time

Целевые URL:

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/predictions/`
- `http://127.0.0.1:8000/feed/`
- `http://127.0.0.1:8000/cappers-table/`
- `http://127.0.0.1:8000/tournaments/`

## Шаг 4: Перевести все карточки на готовые PredictionMetrics

1. Найти все места с Count("likes"), Count("favorites"), coupon.likes.count(), coupon.favorites.count().
2. Для карточек прогнозов использовать только:
   - select_related("metrics")
   - Coalesce(F("metrics__likes_count"), 0)
   - Coalesce(F("metrics__favorites_count"), 0)
   - Coalesce(F("metrics__comments_count"), 0)
   - Coalesce(F("metrics__views_count"), 0)
3. Обновить:
   - tournaments/views.py::_tournament_prediction_cards()
   - front/templatetags/prediction_reactions.py
   - game/prediction_views.py проверить, там уже почти готово
   - favorites/catalog/feed проверить на отсутствие live Count по reactions
4. Не считать comments_count через Comment.objects на карточках.


## Шаг 5: Оптимизировать метрики комментариев и реакций комментариев

1. Проверить comment queryset:
   - likes_count/dislikes_count сейчас считаются через Count("reactions")
   - viewer_reaction берется отдельным батчем, это нормально
2. Если на странице может быть много комментариев/ответов, добавить CommentMetrics:
   - comment_id
   - likes_count
   - dislikes_count
   - replies_count
3. При toggle CommentReaction обновлять CommentMetrics атомарно.
4. Для replies использовать replies_count из метрик, а не COUNT по replies.
5. Для initial comments и load more отдавать уже готовые счетчики без annotate Count.

## Шаг 6: Финальный SQL-аудит, индексы и оставшиеся N+1

### Что проверить

После шагов 1-5 нужно пройтись по оставшимся источникам скрытых запросов:

- `PredictionCoverImage`
- template tags для реакций и карточек
- шаблоны карточек прогнозов
- `Paginator.count`
- фильтры/табы, которые вызывают `.count()` или `.aggregate()`
- индексы на таблицах метрик, реакций, комментариев и прогнозов

### Что сделать

1. Проверить `PredictionCoverImage`:
   - на публичных списках обложка должна приходить через `select_related("cover_image")`;
   - на главной пул обложек должен грузиться одним запросом и дальше выбираться из памяти;
   - `assign_cover_image()` не должен вызываться во время render публичных страниц;
   - если массовая публикация прогнозов тормозит, добавить кеш активных cover ids по ключу `cover_type + placement + sport_id`.
2. Найти все скрытые запросы в шаблонах и templatetags:
   - `coupon.likes.count`
   - `coupon.favorites.count`
   - `comment.reactions.count`
   - `prediction.predictions.count`
   - доступ к `author.analyst_profile` без `select_related`
   - доступ к `match.sport`, `match.league`, teams без `select_related`.
3. Проверить индексы:
   - `PredictionCoupon(published_status, audience, published_at/created_at)`
   - `PredictionCoupon(author, published_status, audience)`
   - `Prediction(coupon, match)`
   - `PredictionLike(prediction, user)`
   - `PredictionFavorite(prediction, user)`
   - `Comment(content_type, object_id, status, parent, created_at)`
   - `CommentReaction(comment, user)`
   - `PredictionMetrics(coupon)` и `CommentMetrics(comment)`, если CommentMetrics добавлен.
4. Проверить, что `Paginator` не делает тяжелый `COUNT()` поверх queryset с `annotate/prefetch/subquery`:
   - для `/feed/` использовать уже посчитанный cached count;
   - для `/predictions/` по возможности использовать cached count из metadata;
   - для страниц с фильтрами не считать count повторно в нескольких местах.
5. После всех правок сделать контрольный замер SQL по целевым URL:
   - записать SQL count до/после;
   - записать total SQL time;
   - отдельно проверить первый заход после очистки кеша и повторный заход с теплым кешем.

### Ожидаемый результат

После шага 6 не должно остаться скрытых N+1 в карточках, templatetags и обложках. Все тяжелые counts должны либо идти из готовых metrics-таблиц, либо кешироваться коротким TTL, либо выполняться один раз на страницу.
