# План: расширенные прогнозы, VIP-статьи и rich-карточки

Главный принцип: быстрый купон не ломать. `coupon-panel` остается быстрым способом создать только быстрый прогноз без описания, обложки и выбора платности. Полная страница доступна всем капперам, включая бесплатных, чтобы они видели форму и заблокированные VIP-возможности.

Ключевые правила:

- быстрый купон всегда остается быстрым и бесплатным;
- платные прогнозы создаются только на расширенной странице;
- расширенная страница доступна всем капперам;
- описание и обложки доступны только VIP-капперам;
- если прогноз платный, описание обязательно.

## Шаг 1. Зафиксировать текущие точки входа

Файлы только прочитать перед правками:

- `game/views.py` — текущая логика создания быстрого купона.
- `templates/game/_coupon_panel.html` — быстрый купон в сайдбаре.
- `templates/game/_coupon_sidebar.html` — сайдбар купона.
- `templates/game/_match_table_filter_sidebar.html` — `matches-table-filter-sidebar`.
- `game/models.py` — `PredictionCoupon`, `PredictionCoverImage`.
- `front/metric_models.py` — `PredictionMetrics.views_count`, `shares_count`.
- `front/metrics.py` — `increment_prediction_views`, `increment_prediction_shares`.
- `templates/front/includes/_feed_prediction_card.html` — текущая карточка с тремя точками.
- `templates/front/predictions.html`, `templates/front/following_feed.html`, `templates/front/favorites.html`.

Ничего из быстрого купона не удалять.

## Шаг 2. Добавить формат прогноза в `PredictionCoupon`

Файл:

- `game/models.py`

Добавить поле:

```python
class PredictionFormat(models.TextChoices):
    QUICK = "quick", "Быстрый купон"
    RICH = "rich", "Расширенный прогноз"

prediction_format = models.CharField(
    "Формат прогноза",
    max_length=16,
    choices=PredictionFormat.choices,
    default=PredictionFormat.QUICK,
    db_index=True,
)
```

Добавить поля для rich-прогноза:

- `headline = models.CharField("Заголовок", max_length=160, blank=True)`
- `description = models.TextField("Описание прогноза", blank=True)`
- `custom_cover_image = models.ImageField("Своя обложка", upload_to="prediction_covers/custom/%Y/%m/", blank=True)`
- `tags = models.JSONField("Теги", default=list, blank=True)`

Важно:

- не добавлять `views_count` в `PredictionCoupon`, метрики уже есть в `front.metric_models.PredictionMetrics`;
- не использовать имя `title`, потому что в проекте уже была миграция удаления `PredictionCoupon.title`;
- миграцию создать отдельно.

## Шаг 3. Добавить сервис для расширенного прогноза

Создать файл:

- `game/services/prediction_editor.py`

Что вынести в сервис:

- подготовка данных формы;
- проверка доступа;
- создание rich-прогноза;
- редактирование rich-прогноза;
- выбор системной обложки;
- загрузка своей обложки;
- подготовка preview/context.

Функции:

```python
def can_use_rich_prediction_fields(user) -> bool:
    return bool(user.is_authenticated and user.is_analyst and user.is_vip)

def build_prediction_editor_context(request, coupon=None) -> dict:
    ...

def create_rich_prediction(user, data, files) -> PredictionCoupon:
    ...

def update_rich_prediction(user, coupon, data, files) -> PredictionCoupon:
    ...
```

Правила:

- расширенная страница доступна всем капперам: `user.is_authenticated and user.is_analyst`;
- описание и своя/выбранная обложка доступны только `user.is_vip`;
- обычный каппер видит заблокированный блок с CTA “Доступно VIP-капперам”;
- если обычный каппер отправил `description` или `custom_cover_image`, сервис должен игнорировать эти поля или вернуть ошибку доступа;
- платный прогноз можно создать только на этой странице, не из быстрого `coupon-panel`;
- если `is_paid=True`, поле `description` обязательно и должно пройти валидацию;
- быстрый купон не должен использовать этот сервис.

## Шаг 4. Добавить форму расширенного прогноза

Файл:

- `game/forms.py` если есть, иначе создать `game/forms.py`.

Форма:

```python
class RichPredictionCouponForm(forms.Form):
    match = forms.ModelChoiceField(...)
    coupon_type = forms.ChoiceField(...)
    is_paid = forms.BooleanField(required=False)
    coefficient = forms.DecimalField(...)
    prediction_text = forms.CharField(...)
    headline = forms.CharField(required=False)
    description = forms.CharField(required=False, widget=forms.Textarea)
    cover_image = forms.ModelChoiceField(required=False, queryset=PredictionCoverImage.objects.none())
    custom_cover_image = forms.ImageField(required=False)
    tags = forms.CharField(required=False)
```

В `__init__` принимать `user` и `match/sport`.

Ограничения:

- для не-VIP убрать/заблокировать `description`, `cover_image`, `custom_cover_image`;
- `is_paid` показывать только на расширенной странице;
- если `is_paid=True`, `description` обязательно;
- если `is_paid=True` и пользователь не VIP, вернуть ошибку “Платные прогнозы доступны VIP-капперам”;
- image validation: jpg/png/webp, разумный размер файла;
- теги нормализовать в список без `#`, максимум 5-7 тегов.

## Шаг 5. Добавить view страницы расширенного прогноза

Файл:

- `game/views.py`

Добавить view:

```python
@login_required
def rich_prediction_create(request):
    ...

@login_required
def rich_prediction_edit(request, coupon_id):
    ...
```

View должен только:

- проверить `request.user.is_analyst`;
- собрать form;
- вызвать сервис из `game/services/prediction_editor.py`;
- сделать `render` или `redirect`.

Не писать бизнес-логику во view.

## Шаг 6. Добавить URLs

Файл:

- `game/urls.py`

Добавить:

```python
path("predictions/new/", views.rich_prediction_create, name="rich_prediction_create"),
path("predictions/<int:coupon_id>/edit/", views.rich_prediction_edit, name="rich_prediction_edit"),
```

Имена использовать в шаблонах через `{% url %}`.

## Шаг 7. Сверстать страницу редактора прогноза

Создать файл:

- `templates/game/rich_prediction_form.html`

Структура:

- общий layout как у страниц кабинета/матчей;
- слева можно использовать существующий профильный/матчевый сайдбар;
- центр: форма прогноза;
- справа: preview карточки `prediction-card prediction-card-rich`.

Блоки формы:

- выбор матча;
- тип купона;
- прогноз;
- коэффициент;
- тип доступа: бесплатный / платный;
- заголовок;
- VIP-блок описания;
- VIP-блок обложки;
- теги;
- кнопки “Опубликовать”, “Сохранить черновик”.

В шаблоне не писать сложные условия. Все флаги передать из context:

- `can_use_rich_fields`;
- `vip_upgrade_url`;
- `available_covers`;
- `preview_prediction`;
- `submit_label`.

## Шаг 8. Добавить ссылки на новую страницу

Файлы:

- `templates/front/includes/_main_header.html`
- `templates/game/_coupon_panel.html`
- `templates/game/_coupon_sidebar.html`
- `templates/game/_match_table_filter_sidebar.html`

Что добавить:

- в `nav-profile-dropdown` ссылку “Расширенный прогноз”;
- в `coupon-panel` кнопку/ссылку “Написать расширенный прогноз”;
- в `coupon-sidebar` ссылку на полную форму;
- в `matches-table-filter-sidebar` ссылку “Создать прогноз”.

Для не-каппера:

- ссылку можно вести на `cabinet:become_capper`;
- текст: “Стать каппером”.

Для каппера без VIP:

- страницу открыть можно;
- VIP-поля на странице показать заблокированными.

## Шаг 8.1. Убрать выбор платности из быстрого купона

Файлы:

- `templates/game/_coupon_panel.html`
- `templates/game/_coupon_sidebar.html`
- `game/views.py`
- `game/services/coupon_validation.py`
- `front/static/front/js/coupon-constraints.js`

Что сделать:

- убрать из быстрого купона UI выбора “платный / бесплатный”;
- при создании через быстрый купон всегда ставить `is_paid=False`;
- если быстрый endpoint получил `is_paid=True` из POST, игнорировать и сохранять `False`;
- оставить ссылку “Создать платный прогноз” на расширенную страницу;
- не удалять поле `is_paid` из модели, оно нужно для расширенной страницы.

Проверка:

- быстрый купон создает только быстрый бесплатный прогноз;
- платный прогноз нельзя создать через POST быстрого купона;
- платный прогноз создается только через `rich_prediction_create`.

## Шаг 9. Использовать существующие обложки прогнозов

Файл:

- `game/models.py`

Уже есть `PredictionCoverImage`.

Правила отображения:

1. Если есть `coupon.custom_cover_image` — показывать ее.
2. Иначе если есть `coupon.cover_image` — показывать системную обложку.
3. Иначе вызвать существующий `coupon.assign_cover_image()`.

Не создавать вторую модель системных обложек.

## Шаг 10. Подготовить queryset rich-прогнозов

Создать или расширить сервис:

- `front/prediction_metrics.py` или `front/prediction_catalog_views.py` helper, если там уже есть сбор queryset.

Функция:

```python
def get_rich_predictions_queryset(user=None):
    ...
```

Queryset должен:

- фильтровать `PredictionCoupon.prediction_format="rich"`;
- брать только опубликованные прогнозы;
- делать `select_related("user", "user__analyst_profile", "cover_image", ...)`;
- аннотировать `views_count`, `likes_count`, `comments_count`, `favorites_count`, `shares_count` из `PredictionMetrics`;
- не делать N+1 по автору, аватару, матчу, спорту.

## Шаг 11. Добавить таб “Текстовые прогнозы”

Файлы:

- `front/prediction_catalog_views.py`
- `front/feed_views.py`
- `front/favorites_views.py`
- `templates/front/predictions.html`
- `templates/front/following_feed.html`
- `templates/front/favorites.html`
- `templates/front/includes/_prediction_results_head.html`

Что сделать:

- добавить query param `prediction_type=classic|rich`;
- по умолчанию оставить текущие прогнозы;
- при `prediction_type=rich` показывать только rich-прогнозы;
- добавить табы:
  - “Прогнозы”
  - “Текстовые”

Важно:

- текущий вывод обычных прогнозов не менять;
- sport filter оставить общий;
- старые AJAX-фильтры должны передавать `prediction_type`.

## Шаг 12. Сверстать rich-карточку как на скрине

Создать include:

- `templates/front/includes/_rich_prediction_card.html`

Классы:

- `prediction-card`
- `prediction-card-rich`
- `prediction-card-rich-cover`
- `prediction-card-rich-body`
- `prediction-card-rich-meta`
- `prediction-card-rich-title`
- `prediction-card-rich-description`
- `prediction-card-rich-tags`
- `prediction-card-rich-stats`
- `prediction-card-rich-actions`

Содержимое:

- слева большая обложка;
- поверх обложки: спорт, время матча, лига;
- команды на обложке;
- центр: автор, VIP/verified badge, дата, тип прогноза, заголовок, описание, теги;
- справа: коэффициент, статус, просмотры;
- низ: лайк, комментарии, поделиться, сохранить.

Стили:

- только `front/static/front/css/main.css`;
- адаптив только `front/static/front/css/mobile.css`;
- без inline style;
- без новых CSS-файлов;
- не использовать border, если можно разделить фон/spacing.

## Шаг 13. Заменить три точки на share icon

Файл:

- `templates/front/includes/_feed_prediction_card.html`

Найти:

- `feed-prediction-action feed-prediction-menu`

Заменить на кнопку поделиться:

- класс: `feed-prediction-action feed-prediction-share prediction-share`;
- `data-prediction-id`;
- `data-share-url`;
- aria-label: “Поделиться прогнозом”.

Если rich-карточка использует отдельный include, там сразу ставить такую же кнопку.

## Шаг 14. Подключить JS для share

Файл:

- `front/static/front/js/prediction-reactions.js`

Добавить обработчик:

- сначала использовать `navigator.share`, если доступен;
- иначе копировать ссылку в clipboard;
- после успешного share/copy вызвать endpoint счетчика shares.

Для маленького AJAX skeleton не использовать.

Endpoint можно добавить в:

- `front/reaction_views.py`

Функция:

```python
@require_POST
def share_prediction(request, coupon_id):
    metrics = increment_prediction_shares(coupon_id)
    return JsonResponse({"ok": True, "shares_count": metrics.shares_count})
```

## Шаг 15. Показать просмотры прогноза

Метрика уже есть:

- `front/metric_models.py::PredictionMetrics.views_count`
- `front/metrics.py::increment_prediction_views`

Что сделать:

- не создавать новое поле просмотров;
- в списках `/predictions/`, `/feed/`, `/favorites/` аннотировать `views_count`;
- в `prediction-card-rich` показывать `{{ prediction.views_count }} просмотров`;
- на detail-странице оставить текущий `increment_prediction_views`;
- не считать показ карточки в ленте как просмотр, если это не оговорено отдельно.

## Шаг 16. Добавить VIP-статьи капперов

Создать модель в:

- `cabinet/models.py`

Модель:

```python
class CapperArticle(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        PENDING = "pending", "На модерации"
        APPROVED = "approved", "Опубликована"
        REJECTED = "rejected", "Отклонена"

    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="capper_articles")
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=220, blank=True)
    cover_image = models.ImageField(upload_to="capper_articles/%Y/%m/", blank=True)
    excerpt = models.TextField(blank=True)
    content = HTMLField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    moderation_note = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

`HTMLField` взять так же, как в `front/models.py::Article`.

Доступ:

- создавать/отправлять могут только VIP-капперы: `user.is_analyst and user.is_vip`;
- обычный каппер видит locked CTA “Стать VIP, чтобы публиковать статьи”.

## Шаг 17. Добавить сервис VIP-статей

Создать:

- `cabinet/services/capper_articles.py`

Функции:

```python
def can_create_capper_article(user) -> bool:
    ...

def build_capper_articles_context(user) -> dict:
    ...

def save_capper_article(user, data, files, article=None) -> CapperArticle:
    ...

def submit_capper_article_for_moderation(user, article) -> CapperArticle:
    ...

def approve_capper_article(article, moderator) -> CapperArticle:
    ...

def reject_capper_article(article, moderator, note: str) -> CapperArticle:
    ...
```

Модерация:

- переиспользовать `cabinet/comments/services/anti_spam.py`;
- переиспользовать `cabinet/comments/services/moderation.py`;
- не копировать списки мата/ссылок;
- если текст не проходит проверку, статья не должна сразу публиковаться.

## Шаг 18. Добавить страницы VIP-статей в кабинет

Файлы:

- `cabinet/views.py`
- `cabinet/urls.py`
- `templates/cabinet/capper_articles.html`
- `templates/cabinet/capper_article_form.html`

URLs:

```python
path("articles/", views.capper_articles, name="capper_articles"),
path("articles/new/", views.capper_article_create, name="capper_article_create"),
path("articles/<int:article_id>/edit/", views.capper_article_edit, name="capper_article_edit"),
path("articles/<int:article_id>/submit/", views.capper_article_submit, name="capper_article_submit"),
```

Страницы:

- список моих статей;
- статус: черновик / на модерации / опубликована / отклонена;
- форма создания/редактирования;
- кнопка отправки на модерацию.

## Шаг 19. Добавить модерацию VIP-статей в админку

Файл:

- `cabinet/admin.py`

Добавить `CapperArticleAdmin`:

- `list_display`: author, title, status, submitted_at, published_at;
- `list_filter`: status, created_at, published_at;
- `search_fields`: title, author username;
- actions:
  - approve selected;
  - reject selected.

При approve:

- status = approved;
- published_at = now;
- reviewed_by = request.user;
- reviewed_at = now.

## Шаг 20. Показать статьи в публичном профиле каппера

Файлы:

- `cabinet/expert_profile_views.py`
- `templates/cabinet/expert_profile.html`

Что сделать:

- выбрать только `CapperArticle.Status.APPROVED`;
- сортировка `published_at DESC`;
- добавить таб/секцию “Статьи”;
- показать title, excerpt, cover, дату;
- не показывать черновики и pending.

Если у каппера нет статей:

- показывать компактный empty state без больших блоков.

## Шаг 21. Добавить ссылки на VIP-статьи в меню

Файлы:

- `templates/front/includes/_main_header.html`
- `templates/cabinet/includes/_profile_tabs_sidebar.html`

Добавить пункт:

- “Мои статьи”

Логика:

- VIP-капперу вести на `cabinet:capper_articles`;
- обычному капперу вести туда же, но страница показывает locked CTA;
- обычному пользователю пункт можно скрыть.

## Шаг 22. Обновить CSS

Файлы:

- `front/static/front/css/main.css`
- `front/static/front/css/mobile.css`

Добавить стили для:

- `prediction-card-rich`;
- `rich-prediction-form`;
- `rich-prediction-cover-picker`;
- `capper-articles-page`;
- `capper-article-form`;
- locked VIP CTA.

Правила:

- без новых CSS-файлов;
- без `<style>` в templates;
- адаптив только в `mobile.css`;
- не дублировать существующие классы, сначала найти похожие через `rg`;
- не использовать skeleton для submit/share/upload маленьких AJAX-действий.

## Шаг 23. Обновить JS без лишней архитектуры

Файлы:

- `front/static/front/js/prediction-reactions.js`
- при необходимости `front/static/front/js/profile.js`

Что добавить:

- share/copy handler;
- preview выбранной обложки в форме;
- disable кнопки при отправке формы;
- обработку ошибок.

Не создавать новый JS-файл, если хватает существующего.

## Шаг 24. Проверить права доступа

Проверки вручную:

- обычный пользователь не создает прогнозы и статьи;
- обычный каппер может быстрый купон;
- обычный каппер видит rich-страницу, но VIP-поля заблокированы;
- быстрый купон не показывает выбор платности;
- быстрый купон всегда сохраняет `is_paid=False`;
- VIP-каппер может описание, теги, системную обложку, свою обложку;
- VIP-каппер может создать платный прогноз только с заполненным описанием;
- VIP-каппер может создать статью и отправить на модерацию;
- статья не появляется в публичном профиле до approve;
- после approve статья появляется в публичном профиле.

## Шаг 25. Добавить минимальные тесты

Файлы:

- `game/test_rich_prediction_editor.py`
- `cabinet/tests/test_capper_articles.py`
- `front/test_rich_prediction_cards.py`

Проверить:

- не-VIP не сохраняет описание/обложку rich-прогноза;
- быстрый купон игнорирует `is_paid=True` и сохраняет `is_paid=False`;
- платный rich-прогноз без описания не сохраняется;
- VIP сохраняет описание/обложку;
- VIP сохраняет платный rich-прогноз с описанием;
- rich-прогноз попадает только в таб “Текстовые”;
- `views_count` берется из `PredictionMetrics`;
- share endpoint увеличивает `shares_count`;
- VIP-статья после submit получает `pending`;
- approved статья видна в публичном профиле;
- rejected/pending/draft статья не видна в публичном профиле.

## Шаг 26. Ручная проверка страниц

Открыть:

- `/games/`
- `/predictions/`
- `/predictions/?prediction_type=rich`
- `/feed/`
- `/feed/?prediction_type=rich`
- `/favorites/`
- `/favorites/?prediction_type=rich`
- `/games/predictions/new/` или фактический URL из `game:rich_prediction_create`
- `/cabinet/articles/`
- публичный профиль VIP-каппера

Проверить:

- быстрый купон работает как раньше;
- новая ссылка есть в `nav-profile-dropdown`;
- новая ссылка есть в `coupon-panel`;
- новая ссылка есть в `matches-table-filter-sidebar`;
- rich-карточка не ломает мобильную верстку;
- вместо трех точек в карточке стоит share icon;
- просмотры отображаются;
- нет N+1 по автору, аватару, матчу и метрикам.
