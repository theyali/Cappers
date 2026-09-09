План в 4 шага:

1
Модель и миграция
В front/models.py (line 13) расширить Article:

is_main = BooleanField(default=False) для главной статьи.
reading_time = PositiveSmallIntegerField(...).
tags = CharField/TextField или отдельная M2M-модель, если нужны нормальные фильтры по тегам.
category = ForeignKey(ArticleCategory, ...), где ArticleCategory отдельная модель с name, slug, is_active, sort_order.


2
Админка и выборки
В front/admin.py (line 11):

добавить ArticleCategoryAdmin;
вывести is_main, reading_time, category в списки/фильтры;
добавить поля в fieldsets.
В front/home_views.py (line 472):

выбирать одну главную статью is_main=True;
остальные статьи брать отдельно, исключая главную;
желательно select_related("category").
В front/article_views.py (line 12):

подготовить категории для будущего фильтра;
сразу сделать ?category=slug, если хотим фильтрацию уже сейчас.


3
Шаблоны под макет
В templates/front/index.html (line 429) заменить текущий слайдер статей на структуру как на скрине:

header: “Редакция”, “Новые статьи”, описание, кнопка “Все статьи”, стрелки;
большой featured/main article: картинка слева, справа категория, дата, время чтения, заголовок, описание, CTA, теги;
ниже сетка из 3 карточек.
В templates/front/articles.html (line 9) привести список /articles/ к той же карточной системе: дата, время чтения, категория, теги, новые карточки.


4
CSS: убрать старое и добавить новое
В front/static/front/css/main.css (line 7520):

удалить/заменить старые стили .home-article-*, .home-articles-window, .home-articles-track, footer/dots если слайдер больше не нужен;
удалить/заменить старые стили .article-list-* для страницы /articles/;
добавить новые стили под featured-блок и 3 карточки, с адаптивом под mobile/tablet.
Важно: в main.css уже есть несохранённые изменения в блоке .predictions-layout, их не трогать и не откатывать.

