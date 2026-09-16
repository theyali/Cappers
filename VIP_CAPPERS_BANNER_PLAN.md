# План внедрения VIP Cappers Banner

## Цель

Сделать единый переиспользуемый баннер `templates/front/banners/vip_cappers.html` по первому скрину и подключать его на разных страницах одним вызовом.

Ограничения:

- `font-size` не выше `17px`;
- `font-weight` не выше `600`;
- без лишнего JS;
- старые стили `vip-experts-panel` удалить или заменить;
- старый блок `predictions-filter-sidebar tournaments-left-sidebar` на странице турниров убрать полностью.

## Шаг 1: Подготовить единый источник VIP капперов

1. Найти текущий источник `{% vip_experts_sidebar 5 %}` в template tag `site_extras`.
2. Переделать/добавить новый template tag, например `{% vip_cappers_banner 6 %}`.
3. Сортировка должна быть единой для всех страниц:
   - первый сверху — каппер, который последним купил/получил VIP статус;
   - ниже — ещё 5 VIP капперов.
4. Если текущая модель хранит только `AnalystProfile.is_vip`, но не хранит дату покупки VIP, добавить поле/источник даты:
   - `vip_activated_at` или использовать существующий `UserRouletteRewardState.vip_until/updated_at`, если это корректный источник;
   - если точной даты нет, временный fallback: `AnalystProfile.updated_at` или `user.date_joined`, но это надо явно заменить на настоящую дату VIP.
5. В queryset сразу подготовить данные для карточки:
   - `user`;
   - avatar;
   - display name;
   - verified;
   - followers count;
   - success/winrate;
   - main sport/category text;
   - profile URL.

## Шаг 2: Собрать `templates/front/banners/vip_cappers.html`

1. Сделать структуру как на первом скрине:
   - общий темный panel;
   - header: корона, `VIP Капперы`, subtitle, стрелка;
   - hero-card для главного VIP каппера;
   - крупный avatar справа в синем glow/ring;
   - badge `ЭКСПЕРТ НЕДЕЛИ`;
   - имя + verified;
   - спорт/тип прогнозов;
   - 2 метрики: успешность и подписчики;
   - желтая кнопка `Подписаться`;
   - нижний список `Рейтинг недели` заменить смыслом на остальные VIP капперы;
   - 5 строк VIP капперов;
   - footer-link `Все VIP капперы`.
2. Не оставлять старую механику “рейтинг недели”, если она тянет другой порядок.
3. Все ссылки вести на публичный профиль каппера или на страницу VIP рейтинга.
4. Если VIP капперов меньше 6, шаблон должен аккуратно показывать сколько есть и не ломать layout.

## Шаг 3: Переписать стили `vip-experts-panel`

1. Удалить или заменить старые CSS блоки:
   - `.vip-experts-panel`;
   - `.vip-experts-list`;
   - `.vip-expert-card`;
   - старые mobile overrides в `front/static/front/css/mobile.css`.
2. Добавить новые scoped классы, например:
   - `.vip-cappers-banner`;
   - `.vip-cappers-hero`;
   - `.vip-cappers-main`;
   - `.vip-cappers-list`;
   - `.vip-cappers-row`.
3. Держать ограничения:
   - `font-size <= 17px`;
   - `font-weight <= 600`;
   - без фиксированной высоты контейнеров;
   - responsive без налезания текста;
   - не использовать JS для layout.
4. Визуально повторить первый скрин:
   - темный фон;
   - тонкие border/ring;
   - синий glow вокруг главного avatar;
   - желтые акценты;
   - компактные строки списка;
   - стрелки и info icon через inline svg или существующие icons.

## Шаг 4: Подключить на страницах

1. `templates/tournaments/index.html`:
   - удалить wrapper `predictions-filter-sidebar tournaments-left-sidebar`;
   - вместо него подключить новый баннер напрямую в левую колонку;
   - не оставлять старый `bookmakers-sidebar` вокруг VIP блока, если он мешает pixel perfect.
2. `templates/front/cappers_table.html`:
   - под фильтрами рейтинга добавить один вызов нового VIP баннера;
   - не дублировать данные, не делать отдельный queryset во view.
3. `templates/front/favorites.html`:
   - в правой колонке заменить старый `bookmakers-panel vip-experts-panel`;
   - оставить рекламные баннеры ниже, если они нужны;
   - вместо правого `bookmakers-panel` использовать новый VIP banner.
4. Проверить, что новый include/tag можно подключить одинаково на всех страницах без дополнительных context variables.

## Шаг 5: Проверка и чистка

1. Проверить страницы:
   - `http://127.0.0.1:8000/tournaments/`;
   - `http://127.0.0.1:8000/cappers-table/`;
   - `http://127.0.0.1:8000/favorites/`.
2. Проверить desktop и mobile:
   - текст не выходит за контейнер;
   - avatar не перекрывает имя/метрики;
   - кнопка помещается;
   - список из 5 капперов не ломает панель.
3. Проверить SQL:
   - template tag не должен делать N+1;
   - VIP капперы должны грузиться одним queryset;
   - followers/success metrics не считать в цикле.
4. Удалить неиспользуемые старые классы и include, если они больше нигде не нужны.
5. Сверить визуально с первым скрином и отдельно убедиться, что второй старый вид больше не появляется на tournaments/favorites/cappers-table.
