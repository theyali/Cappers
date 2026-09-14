# План внедрения комментариев к прогнозам

Цель: добавить комментарии к прогнозам для всех авторизованных пользователей, но сразу заложить общий сервис модерации и антиспама, который потом можно использовать для статей, матчей и других разделов. Также нужно сохранять метрики прогнозов/матчей в базе, чтобы не пересчитывать лайки, комментарии, избранное и другие счетчики на каждой странице.

## 1. Спроектировать общую модель комментариев

Создать универсальную модель комментария, которую можно привязать не только к прогнозу, но и в будущем к статье, матчу, новости или другому объекту.

Рекомендуемый вариант: использовать `ContentType` + `object_id`.

```python
class Comment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    target = GenericForeignKey("content_type", "object_id")
    text = models.TextField(max_length=1000)
    status = models.CharField(...)
    moderation_reason = models.CharField(max_length=255, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

Статусы:

```text
published
pending
rejected
deleted
```

На первом этапе можно разрешить только плоские комментарии без ответов, но `parent` лучше заложить сразу.

## 2. Сделать общий comment moderation service

Создать единый сервис, например:

```text
comments/services/moderation.py
```

И публичный API:

```python
validate_comment_text(text, user=None) -> ModerationResult
normalize_comment_text(text) -> str
contains_forbidden_link(text) -> bool
contains_profanity(text) -> bool
```

Сервис должен использоваться везде:

- комментарии к прогнозам;
- будущие комментарии к статьям;
- будущие комментарии к матчам;
- любые пользовательские тексты, где нужна автомодерация.

Правила:

- запретить ссылки: `http://`, `https://`, `www.`, домены вида `site.ru`, `t.me/...`, `@channel`, email;
- запретить HTML;
- нормализовать пробелы;
- ограничить длину;
- запретить пустые комментарии;
- запретить повтор одного и того же комментария много раз.

Важно: не писать отдельную проверку ссылок в каждом view. Только общий moderation service.

## 3. Добавить словарь мата и вариаций

Создать отдельный файл словаря, например:

```text
comments/data/profanity_ru.txt
comments/data/profanity_patterns.py
```

Нужно учитывать:

- разные регистры;
- пробелы между буквами;
- точки, дефисы, подчеркивания между буквами;
- замены букв цифрами;
- латиницу вместо кириллицы;
- частичные маскировки.

Пример подхода:

```python
normalize_obfuscated_text("м.а.т") -> "мат"
normalize_obfuscated_text("m a t") -> "мат"
```

Сервис не должен быть идеальным NLP, но должен закрывать базовые обходы.

Результат модерации:

```python
ModerationResult(
    allowed=False,
    status="rejected",
    reason="profanity",
    public_message="Комментарий содержит запрещенные слова."
)
```

## 4. Добавить антиспам и rate limits

Сделать сервис антиспама:

```text
comments/services/anti_spam.py
```

Правила на старте:

- не больше `N` комментариев в минуту;
- не больше `M` комментариев в час;
- запрет одинакового текста подряд;
- запрет слишком коротких повторяющихся сообщений;
- запрет массовых комментариев к разным прогнозам за короткое время;
- для новых пользователей можно сделать более строгий лимит.

Хранить можно через БД-запросы по `Comment.created_at` или через cache, если уже используется Redis.

При нарушении возвращать понятную ошибку:

```text
Слишком много комментариев. Попробуйте позже.
```

## 5. Добавить API для комментариев к прогнозам

Сделать endpoints, например:

```text
GET  /predictions/<id>/comments/
POST /predictions/<id>/comments/
POST /comments/<id>/delete/
```

Для POST:

- только авторизованный пользователь;
- проверить, что прогноз существует и доступен публично;
- прогнать текст через moderation service;
- прогнать пользователя через anti-spam;
- создать комментарий;
- обновить счетчики метрик;
- вернуть JSON с HTML или данными комментария.

Удаление:

- пользователь может удалить свой комментарий;
- модератор/админ может удалить любой;
- физически лучше не удалять, а ставить `status="deleted"`.

## 6. Сохранять метрики прогнозов и матчей в базе

Не считать каждый раз на страницах:

- лайки;
- комментарии;
- избранное;
- просмотры;
- репосты, если появятся;
- активность по матчу;
- количество прогнозов на матч.

Создать модели-счетчики, например:

```python
class PredictionMetrics(models.Model):
    coupon = models.OneToOneField("game.PredictionCoupon", ...)
    likes_count = models.PositiveIntegerField(default=0)
    comments_count = models.PositiveIntegerField(default=0)
    favorites_count = models.PositiveIntegerField(default=0)
    views_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
```

Для матчей:

```python
class MatchMetrics(models.Model):
    match = models.OneToOneField("game.Match", ...)
    predictions_count = models.PositiveIntegerField(default=0)
    comments_count = models.PositiveIntegerField(default=0)
    favorites_count = models.PositiveIntegerField(default=0)
    views_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
```

Все изменения делать через сервисы:

```python
increment_prediction_comments(coupon_id)
decrement_prediction_comments(coupon_id)
refresh_prediction_metrics(coupon_id)
refresh_match_metrics(match_id)
```

Не обновлять счетчики руками в шаблонах или views.

## 7. Добавить иконку комментариев и счетчик во все карточки прогнозов

Добавить UI comments counter во все варианты карточек:

```text
prediction-card
prediction-card-rich
feed-prediction-card
content-table-row
prediction-table-row
```

Нужно использовать один include, например:

```text
templates/front/includes/_comment_metric.html
```

Он должен показывать:

- иконку комментария;
- количество комментариев;
- ссылку на прогноз или открытие комментариев;
- `aria-label`.

Пример:

```django
<a class="prediction-comment-metric" href="{{ prediction.comments_url }}">
    {% include "front/svgs/comment.svg" %}
    <span>{{ prediction.comments_count }}</span>
</a>
```

Если `comment.svg` нет, добавить SVG в:

```text
templates/front/svgs/comment.svg
```

Не копировать SVG-разметку в каждую карточку.

## 8. Добавить UI комментариев на странице прогноза

На странице детального прогноза добавить блок:

```text
Комментарии
```

Функции:

- список опубликованных комментариев;
- форма добавления;
- loading state;
- empty state;
- ошибка модерации;
- ошибка rate limit;
- удаление своего комментария;
- обновление счетчика после отправки/удаления.

Форма:

- textarea;
- счетчик символов;
- кнопка отправки;
- disabled state во время отправки;
- текст подсказки: без ссылок и запрещенной лексики.

JS можно вынести в:

```text
front/static/front/js/comments.js
```

## 9. Добавить админку и модераторские инструменты

В админке:

- список комментариев;
- фильтр по статусу;
- фильтр по причине модерации;
- поиск по тексту и пользователю;
- быстрые actions: publish, reject, delete;
- просмотр target object;
- readonly audit fields.

Также добавить возможность редактировать словарь запрещенных слов через админку позже. На первом этапе достаточно файла словаря, но архитектура должна позволять заменить его на модель:

```python
ForbiddenWord
ForbiddenPattern
```

Не нужно давать обычным пользователям редактировать комментарии на первом этапе, чтобы не усложнять модерацию.

## 10. Покрыть тестами и сделать проверку производительности

Тесты:

- авторизованный пользователь может оставить комментарий к прогнозу;
- гость не может оставить комментарий;
- ссылки запрещены;
- мат и вариации запрещены;
- HTML вычищается или отклоняется;
- повтор одинакового комментария блокируется;
- rate limit работает;
- удаление комментария уменьшает `comments_count`;
- карточки получают `comments_count` из базы;
- прогнозы и матчи не делают `COUNT()` на каждый рендер списка.

Проверки:

```bash
rg -n "comments_count|PredictionMetrics|MatchMetrics|validate_comment_text|contains_forbidden_link" front cabinet game comments templates
python manage.py test comments front game
```

Критерии готовности:

- комментарии работают на прогнозах;
- ссылки и мат блокируются единым сервисом;
- счетчик комментариев отображается на всех карточках прогнозов;
- метрики прогнозов и матчей сохраняются в базе;
- списки прогнозов не считают лайки/комментарии через тяжелые `COUNT()` на каждый объект.
