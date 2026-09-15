# План правок страницы личного кабинета

## Общие ограничения

- Не добавлять лишний JavaScript.
- Не создавать новые UI-компоненты, если уже есть готовые include или классы.
- Не делать глобальный редизайн.
- Не трогать бизнес-логику, кроме минимального получения promo banner, если он уже доступен в контексте.
- Не писать тесты.
- Изменения должны быть минимальными и касаться только страницы личного кабинета.

Основные файлы:

- `templates/cabinet/profile.html`
- `front/static/front/css/main.css`

## Шаг 1: Layout, Hero, Promo Banner

### Цель

Перестроить верхнюю часть личного кабинета так, чтобы страница была разделена на:

1. Левый sidebar menu.
2. Правый content.

Внутри правого content верхний блок должен делиться на:

1. Основной hero.
2. Promo banner справа, который добавлен через админку.

### Что сделать

#### 1. Проверить текущий layout

В `templates/cabinet/profile.html` уже есть структура:

```django
<section class="profile-page matches-page container">
    <div class="matches-shell">
        {% include "cabinet/includes/_profile_tabs_sidebar.html" %}

        <section class="matches-list-panel profile-page">
            ...
        </section>
    </div>
</section>
```

Ее нужно сохранить.

`matches-shell` должен оставаться основным layout-контейнером:

- sidebar слева
- content справа

Новые обертки для всего layout не добавлять.

#### 2. Перестроить `profile-dashboard-head`

Сейчас hero находится внутри:

```django
<div class="profile-dashboard-head is-reader">
    <div class="profile-hero...">
        ...
    </div>
</div>
```

Нужно сделать так:

```django
<div class="profile-dashboard-head">
    <div class="profile-hero{% if not request.user.is_analyst %} is-reader{% endif %}">
        ...
    </div>

    {% include "front/includes/_page_promo_banner.html" with promo_banner=promo_banner promo_banner_mod="is-home-sidebar" only %}
</div>
```

Важно:

- `promo_banner` должен быть рядом с `.profile-hero`, а не внутри hero.
- `profile-dashboard-head` должен быть grid-контейнером.
- `profile-hero` остается самостоятельным блоком.
- Админский баннер подключать через существующий include: `front/includes/_page_promo_banner.html`.

#### 3. Hero

Внутри `.profile-hero` оставить только текущий hero-контент:

- avatar
- username/name
- bio
- edit button
- profile meta
- profile status block для аналитика

Не переносить туда promo banner.

Не добавлять новый hardcoded promo HTML.

#### 4. Promo banner

Использовать только существующий partial:

```django
{% include "front/includes/_page_promo_banner.html" with promo_banner=promo_banner promo_banner_mod="is-home-sidebar" only %}
```

Не писать новый JS для получения баннера.

Если `promo_banner` уже приходит из context processor, использовать его.

Если баннер не отображается, проверить:

- есть ли `promo_banner` в контексте
- привязан ли promo banner в админке к странице кабинета
- корректный ли `route_name` или `exact_path`

#### 5. CSS

Править только существующие классы:

- `.profile-dashboard-head`
- `.profile-page .profile-hero`
- `.profile-page .profile-hero.is-reader`
- адаптивные media queries для этих же блоков

Можно добавить только точечное правило для баннера внутри кабинета:

```css
.profile-dashboard-head .page-promo-banner,
.profile-dashboard-head .adv-banners {
    min-width: 0;
}
```

Если нужно выровнять размеры:

```css
.profile-dashboard-head {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 310px;
    gap: 14px;
    align-items: stretch;
}
```

На планшетах и мобильных:

```css
@media (max-width: 1180px) {
    .profile-dashboard-head {
        grid-template-columns: minmax(0, 1fr);
    }
}
```

#### 6. Убрать конфликт `is-reader`

Сейчас может быть правило:

```css
.profile-dashboard-head.is-reader {
    grid-template-columns: minmax(0, 1fr);
}
```

Его нельзя оставлять, если promo banner должен быть справа.

Решение:

- убрать `is-reader` у `profile-dashboard-head` в шаблоне
- reader-режим оставить только на `.profile-hero`

Правильно:

```django
<div class="profile-dashboard-head">
    <div class="profile-hero{% if not request.user.is_analyst %} is-reader{% endif %}">
```

#### 7. Что не делать на первом шаге

- Не трогать блок статистики ниже hero.
- Не менять карточки.
- Не менять табы.
- Не менять JS.
- Не удалять старые CSS-блоки вроде `.profile-pro-promo`, если они не мешают.
- Не делать полную чистку CSS.

### Ожидаемый результат

На desktop:

- слева sidebar menu
- справа content
- вверху content:
  - большой hero слева
  - promo banner справа

На tablet/mobile:

- sidebar и мобильные табы работают как раньше
- hero и promo banner складываются в одну колонку
- остальной контент не ломается

## Шаг 2: Блок ключевых показателей

### Цель

После hero привести блок ключевых показателей к сетке под макет.

Текущий блок начинается с:

```django
{% widthratio achievement_overview.metrics.wins achievement_overview.metrics.predictions 100 as profile_win_rate %}
<section class="expert-public-stats expert-public-stats-compact">
```

### Что сделать

- Не менять данные.
- Не менять вычисления.
- Не менять порядок карточек без необходимости.
- Работать только с HTML-классами и CSS-сеткой.
- Проверить, чтобы блок занимал ширину content, а не всей страницы.
- На desktop карточки должны идти в одну строку, если хватает места.
- На mobile карточки должны переноситься без overflow.

## Шаг 3: Основной контент вкладки профиля

### Цель

После hero и stats привести нижний dashboard-контент к сетке, похожей на макет.

### Что сделать

- Работать с include: `cabinet/includes/_profile_overview_analytics.html`.
- Не менять логику данных.
- Не добавлять JS.
- Настроить CSS-grid для карточек.
- Сохранять существующие компоненты, если они уже есть.

## Шаг 4: Адаптив

### Цель

Проверить страницу на основных ширинах.

### Проверить

- desktop около `1440px`
- laptop около `1280px`
- tablet около `820px`
- mobile около `390px`

### Исправить только layout-проблемы

- горизонтальный скролл
- наложение текста
- слишком широкие карточки
- неправильный перенос hero/banner
- обрезанные кнопки

## Шаг 5: Минимальная чистка

### Цель

Удалить только явно лишнее, если оно мешает.

### Можно удалить

- CSS, который точно больше не используется после правки
- старый promo block, если он реально не подключен и не нужен

### Нельзя удалять

- общие классы, которые используются на других страницах
- стили `page-promo-banner`
- стили `adv-banners`
- sidebar/menu стили
