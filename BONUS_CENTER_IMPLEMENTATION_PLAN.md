# План внедрения бонусного центра `/cabinet/bonuses/`

Цель: привести страницу `http://127.0.0.1:8000/cabinet/bonuses/` к виду как на скрине: рулетка/ежедневный бонус, ежедневные задания, XP-уровни, серии дней, последние подарки, реферальный бонус, последние выигрыши, уровни и CTA пополнения баланса.

План писать и выполнять по правилам `Agent.md`: минимальные изменения, без лишней архитектуры, без inline styles, стили только в `front/static/front/css/main.css` и `front/static/front/css/mobile.css`, бизнес-логика не в templates.

## Текущая база

Уже есть:

- view страницы: `cabinet/bonus_views.py`
- template страницы: `templates/cabinet/bonuses.html`
- API рулетки: `cabinet/roulette/api.py`
- модели рулетки: `cabinet/roulette/models.py`, `cabinet/roulette/state.py`, `cabinet/roulette/rewards.py`, `cabinet/roulette/history.py`
- сервис выдачи наград: `cabinet/roulette/reward_service.py`
- JS рулетки: `front/static/front/js/roulette.js`
- рефералы: `cabinet/referrals.py`, `cabinet/referral_views.py`, `cabinet/models.py::ReferralVisit`
- кошелёк/монеты: `wallets/services.py`, `wallets/models.py`
- текущие стили бонусов: `front/static/front/css/main.css` около блока `.bonus-*`

## Шаг 1. Зафиксировать целевой состав страницы

Собрать структуру страницы из скрина:

- левый sidebar профиля уже есть через `templates/cabinet/includes/_profile_tabs_sidebar.html`;
- центральная область:
  - hero-блок с заголовком, текстом, таймером до следующей попытки и рулеткой;
  - 3 карточки верхнего ряда: следующий бонус, ежедневные задания, серия дней;
  - 3 карточки нижнего ряда: бонус за рефералов, последние выигрыши, мои уровни;
- правый sidebar:
  - последние подарки;
  - прогресс к уровню;
  - CTA пополнения баланса.

Не делать страницу через canvas целиком. Canvas оставить только для колеса, остальная страница должна быть обычной SSR-разметкой.

## Шаг 2. Создать единый builder context для страницы

Добавить файл `cabinet/services/bonus_center.py` или, если папки `services/` нет и не хочется раздувать, использовать существующий `cabinet/bonus_views.py` только как view и создать `cabinet/utils.py` функцию.

Предпочтительно:

- `cabinet/services/bonus_center.py`
- функция `build_bonus_center_context(user, request=None) -> dict`

View `cabinet/bonus_views.py` должен остаться простым:

```python
@login_required
def bonuses(request):
    context = build_bonus_center_context(request.user, request=request)
    context.update({"active_tab": "bonuses", "page_class": "cabinet-bonuses-page"})
    return render(request, "cabinet/bonuses.html", context)
```

В builder сразу готовить все данные для шаблона, без запросов из template.

## Шаг 3. Добавить модели ежедневных заданий

В `cabinet/models.py` добавить модели:

- `DailyTask`
  - `title`
  - `description`
  - `task_type`
  - `target_value`
  - `reward_xp`
  - `reward_coins`
  - `reward_spins`
  - `is_active`
  - `order`
  - `created_at`
  - `updated_at`
- `UserDailyTaskProgress`
  - `user`
  - `task`
  - `progress_date`
  - `current_value`
  - `is_completed`
  - `completed_at`
  - `reward_claimed_at`
  - unique constraint по `user + task + progress_date`

Типы заданий держать простыми `TextChoices`:

- `daily_login`
- `spin_roulette`
- `open_feed`
- `view_prediction`
- `add_favorite`
- `follow_capper`

Не добавлять сложный rule engine.

## Шаг 4. Добавить модели XP и уровней

В `cabinet/models.py` добавить:

- `UserXpState`
  - `user OneToOne`
  - `level`
  - `xp`
  - `created_at`
  - `updated_at`
- `XpLevel`
  - `level`
  - `title`
  - `required_xp`
  - `reward_coins`
  - `reward_spins`
  - `is_active`
  - `order`

XP хранить суммарно в `UserXpState.xp`, уровень вычислять сервисом после начисления. Не хранить много производных полей.

## Шаг 5. Добавить модели серий дней

В `cabinet/models.py` добавить:

- `UserDailyStreak`
  - `user OneToOne`
  - `current_days`
  - `best_days`
  - `last_seen_date`
  - `updated_at`
- `StreakReward`
  - `day_number`
  - `reward_xp`
  - `reward_coins`
  - `reward_spins`
  - `title`
  - `is_active`

Серия увеличивается один раз в день при входе на бонусную страницу или при первом daily action за день.

## Шаг 6. Добавить журнал бонусных событий

Добавить `BonusEvent` в `cabinet/models.py`:

- `user`
- `event_type`
- `title`
- `description`
- `xp_delta`
- `coin_delta`
- `spin_delta`
- `related_model`
- `related_id`
- `created_at`

Использовать его для блоков “Последние подарки” и “Последние выигрыши”, объединяя туда задания, серии, рулетку и рефералы. Для рулетки можно создавать `BonusEvent` после успешного spin.

## Шаг 7. Админка для новых сущностей

В `cabinet/admin.py` зарегистрировать:

- `DailyTask`
- `UserDailyTaskProgress`
- `XpLevel`
- `UserXpState`
- `UserDailyStreak`
- `StreakReward`
- `BonusEvent`

Для справочников добавить `list_display`, `list_filter`, `ordering`. Для пользовательских состояний сделать read-only поля по журналам.

## Шаг 8. Сервис начисления бонусов

Создать `cabinet/services/bonus_rewards.py`:

- `grant_bonus_reward(user, *, xp=0, coins=0, spins=0, event_type, title, description="", related_obj=None)`
- внутри `transaction.atomic()`;
- для coins использовать `wallets.services.credit_coins`;
- для spins использовать `cabinet.roulette.services.get_user_roulette_state(user).grant_spins(...)`;
- для XP использовать отдельную функцию `grant_xp(...)`;
- создавать `BonusEvent`.

Важно: не дублировать логику кошелька, не менять баланс напрямую.

## Шаг 9. Сервис XP-уровней

В `cabinet/services/bonus_rewards.py` или отдельном `cabinet/services/xp.py` добавить:

- `get_user_xp_state(user)`
- `grant_xp(user, amount, related_obj=None, note="")`
- `sync_user_level(user_or_state)`
- `build_level_progress(user)`

`build_level_progress` должен вернуть готовые поля для UI:

- `level`
- `level_title`
- `xp`
- `current_level_xp`
- `next_level_xp`
- `progress_percent`
- `xp_to_next_level`
- `levels_preview` для карточки “Мои уровни”.

## Шаг 10. Сервис ежедневных заданий

Создать `cabinet/services/daily_tasks.py`:

- `get_today_task_progress(user, now=None)`
- `record_daily_task_action(user, task_type, amount=1, related_obj=None)`
- `claim_daily_task_reward(user, task_id)`
- `build_daily_tasks_card(user)`

Задания обновлять по дате проекта через `timezone.localdate()`.

Если задание выполнено, но награда не забрана, UI должен показать кнопку/статус “Получить”. Если награда уже выдана, показать completed.

## Шаг 11. Сервис серий

Создать `cabinet/services/streaks.py`:

- `touch_daily_streak(user, now=None)`
- `build_streak_card(user)`
- `grant_streak_reward_if_needed(user, streak)`

Логика:

- если `last_seen_date == today` — ничего не увеличивать;
- если `last_seen_date == yesterday` — `current_days += 1`;
- иначе `current_days = 1`;
- `best_days = max(best_days, current_days)`;
- если на текущий день есть `StreakReward`, начислить через `grant_bonus_reward`.

## Шаг 12. Встроить события заданий в существующие действия

Найти через `rg` места действий и добавить вызовы `record_daily_task_action`:

- открытие `/cabinet/bonuses/` — `daily_login`;
- успешный spin в `cabinet/roulette/api.py::roulette_spin` — `spin_roulette`;
- просмотр ленты в `front/feed_views.py` — `open_feed`;
- просмотр прогноза в `front/prediction_views.py` или detail-view прогноза — `view_prediction`;
- добавление избранного — найти ajax/view через `rg "favorite|избран"`;
- подписка на каппера — `cabinet/referral_views.py` или текущий follow endpoint.

Не добавлять skeleton для этих маленьких AJAX-действий. Только обычные состояния кнопок/ответов.

## Шаг 13. Интеграция рулетки с бонусными событиями

В `cabinet/roulette/reward_service.py` после выдачи награды добавить создание `BonusEvent` через сервис из шага 8.

Не ломать существующие `RouletteSpin`, `UserRouletteState`, `UserRouletteRewardState`.

В `cabinet/roulette/api.py::roulette_state` расширить JSON:

- `level_progress`
- `daily_tasks_summary`
- `streak`
- `recent_gifts`

Только если эти данные нужны JS. Если блоки SSR и обновляются после reload, в API не добавлять лишнего.

## Шаг 14. Реферальная модель бонусов

Не ломать текущий `ReferralVisit` и `credit_referral_income`.

Добавить отдельную настройку бонусов за рефералов:

- либо модель `ReferralBonusSettings` в `cabinet/models.py`;
- либо поля в существующие настройки сайта, если там уже хранятся проценты.

Минимальный набор:

- `registration_reward_coins`
- `registration_reward_xp`
- `first_topup_reward_coins`
- `first_subscription_reward_coins`
- `max_visible_reward_text`
- `is_enabled`

Добавить сервис `cabinet/services/referral_bonuses.py`:

- `grant_referral_registration_bonus(visit)`
- `grant_referral_first_topup_bonus(referred_user, amount, related_obj=None)`
- `build_referral_bonus_card(user, request=None)`

Награды выдавать через `grant_bonus_reward`, чтобы они попадали в общий журнал.

## Шаг 15. Подключить реферальные бонусы к существующим событиям

Точки подключения:

- `cabinet/referrals.py::mark_referral_registration` — после привязки регистрации;
- `cabinet/referrals.py::credit_referral_income` — дополнить bonus-event для заработка;
- место пополнения баланса/покупки coin package в `wallets/services.py::purchase_coin_package` или платежном callback, если он есть.

Важно: защита от повторной выдачи. Использовать `related_model + related_id + event_type` в `BonusEvent` или отдельные уникальные проверки.

## Шаг 16. Собрать context бонусной страницы

В `build_bonus_center_context` подготовить:

- `roulette_state_url`
- `roulette_spin_url`
- `roulette_bg`
- `next_bonus`
- `daily_tasks_card`
- `streak_card`
- `referral_card`
- `recent_wins`
- `recent_gifts`
- `level_progress`
- `levels_preview`
- `balance_cta`

Для запросов:

- `select_related("user")` там, где нужен user;
- последние события брать одним queryset из `BonusEvent`;
- последние spins брать одним queryset из `RouletteSpin`;
- не обращаться из шаблона к `user.roulette_state`, `user.xp_state` и похожим цепочкам.

## Шаг 17. Переверстать `templates/cabinet/bonuses.html`

Сделать структуру:

- outer: текущий `profile-page matches-page container`;
- `matches-shell` оставить, чтобы sidebar совпадал с профилем;
- внутри создать `bonus-center-layout`;
- центр: `bonus-center-main`;
- право: `bonus-center-aside`;
- hero: `bonus-hero`;
- canvas только внутри `bonus-wheel`;
- карточки: общий include `templates/cabinet/includes/_bonus_dashboard_card.html`, если карточки повторяются.

В шаблоне не писать бизнес-условия сложнее простого `{% if %}`. Все тексты, проценты, ссылки и статусы должны прийти из context.

## Шаг 18. Обновить JS рулетки аккуратно

В `front/static/front/js/roulette.js`:

- оставить canvas-отрисовку колеса;
- не рисовать весь экран в canvas;
- синхронизировать таймеры `[data-bonus-countdown]`;
- после успешного spin обновить:
  - количество попыток;
  - следующий бонус;
  - последние выигрыши/подарки, если API отдаёт новые данные;
- для маленьких обновлений не использовать skeleton;
- skeleton оставить только для крупного блока recent wins, если он реально грузится async.

## Шаг 19. Стили под скрин

В `front/static/front/css/main.css` добавить/переработать только классы бонусного центра:

- `.bonus-center-layout`
- `.bonus-center-main`
- `.bonus-center-aside`
- `.bonus-hero`
- `.bonus-wheel`
- `.bonus-dashboard-grid`
- `.bonus-dashboard-card`
- `.bonus-progress-card`
- `.bonus-gifts-list`
- `.bonus-level-list`
- `.bonus-balance-cta`

Правила:

- без inline styles;
- не создавать новый CSS-файл;
- не добавлять адаптивы в `main.css`;
- не использовать `border`, градиенты и overlay;
- использовать `background`, `box-shadow`, `border-radius`, фирменные цвета;
- текст не должен вылезать из карточек;
- изображения и canvas должны иметь стабильные размеры.

## Шаг 20. Мобильные стили

В `front/static/front/css/mobile.css` добавить адаптив:

- на планшете: sidebar скрывается/становится верхними табами как сейчас;
- центральные карточки в 2 колонки;
- правый sidebar уходит под центральный контент;
- на мобильном: всё в 1 колонку;
- hero не должен ломать canvas, колесо можно уменьшить через max-width.

Не добавлять `@media` в `main.css`.

## Шаг 21. Демо-данные для локальной проверки

Добавить management command только если без него трудно проверять:

- `cabinet/management/commands/seed_bonus_center.py`

Она должна создать:

- 4 ежедневных задания;
- 5 уровней XP;
- 7 streak rewards;
- несколько призов рулетки, если их нет.

Команду делать идемпотентной через `get_or_create/update_or_create`.

## Шаг 22. Проверки после внедрения

Проверить вручную:

- `/cabinet/bonuses/` открывается авторизованным пользователем;
- неавторизованного редиректит на login;
- ежедневная попытка появляется один раз в день;
- серия дней увеличивается один раз в день;
- выполненное задание даёт XP/coins/spins один раз;
- уровень пересчитывается после XP;
- последние подарки показывают свежие события;
- реферальная карточка показывает ссылку/прогресс/награду;
- canvas рулетки крутится и не ломает layout;
- нет N+1 по Django Debug Toolbar или по `connection.queries`;
- мобильная версия не разваливается.

## Шаг 23. Минимальные тесты для слабого ИИ

Если тесты всё же будут добавляться, начать с малого:

- `DailyTaskProgress` нельзя задублировать за день;
- `grant_bonus_reward` начисляет XP/coins/spins и создаёт `BonusEvent`;
- `touch_daily_streak` правильно обрабатывает today/yesterday/gap;
- `roulette_spin` создаёт событие бонуса;
- реферальный бонус не выдаётся два раза за одну регистрацию.

## Шаг 24. Что не делать

- Не переписывать всю систему рулетки.
- Не переносить всё в canvas.
- Не делать универсальный engine заданий с JSON-условиями.
- Не хранить balance/XP/streak в session.
- Не делать запросы из template.
- Не создавать отдельные CSS-файлы.
- Не использовать skeleton для лайков, submit, маленьких AJAX, счётчиков и inline-status.
- Не менять публичное поведение рефералки без отдельной проверки.

## Рекомендуемый порядок коммитов

1. Models/admin для daily tasks, XP, streak, events.
2. Services: rewards, tasks, streaks, level progress.
3. Интеграции в roulette/referrals/actions.
4. Context builder и `bonus_views.py`.
5. Template `templates/cabinet/bonuses.html`.
6. CSS/JS страницы.
7. Seed command и ручная проверка.
