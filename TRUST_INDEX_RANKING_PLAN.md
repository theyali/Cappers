# План внедрения индекса доверия в рейтинг капперов

Проблема: общий индекс доверия каппера уже считается и отображается бейджем, но фактически почти не влияет на позиции. На `/cappers-statistics/` сортировка идет через `ranked_expert_profiles()` по ROI с поправкой на историю, а на `/cappers-table/...` строки сортируются через `_canonical_rank_order()`, который тоже берет этот ROI-based ranking. В таблице `/cappers-table/all/2026-08/` индекс доверия виден на аватаре, но не является явной колонкой и не объясняет позицию.

## 1. Сделать `trust_index` основой общего рейтинга, а ROI оставить вторичным фактором

В `front/expert_ranking.py` изменить `expert_ranking_score(profile)` так, чтобы главным фактором был `profile.trust_index`, а ROI/история использовались как tie-breaker или вспомогательная поправка.

Рекомендованная логика:

```text
ranking_score = trust_index * 1000
              + stabilized_roi_score
              + activity_bonus
```

Важно:

- `trust_index` должен быть главным фактором общего рейтинга;
- ROI не удалить, а использовать после trust index;
- новые капперы с 1 удачным прогнозом не должны обгонять стабильных экспертов;
- при `trust_index = 0` каппер не должен попадать наверх только из-за высокого ROI на малой выборке;
- сортировка должна оставаться детерминированной через username/id.

Обновить сортировку в `ranked_expert_profiles()`:

```python
profiles.sort(
    key=lambda profile: (
        profile.trust_index,
        profile.ranking_score,
        profile.roi_settled_count,
        profile.settled_count,
        profile.followers_count,
        profile.publications_count,
    ),
    reverse=True,
)
```

Если `ranking_score` уже включает `trust_index`, не дублировать его дважды. Главное условие: общий порядок `ranked_expert_profiles()` должен в первую очередь отражать индекс доверия.

Критерий готовности: `/cappers-statistics/` и все места, которые используют `ranked_expert_profiles()`, начинают ранжировать экспертов по trust index, а ROI становится вспомогательным показателем.

## 2. Внедрить trust index в таблицу капперов как видимую колонку и сортировку по умолчанию

В `front/capper_table_service.py` сейчас `_profile_payload()` уже кладет:

```python
"trust_index": profile.trust_index
```

Но таблица `templates/front/cappers_table.html` не имеет отдельной колонки индекса доверия. Нужно добавить колонку рядом с прогнозистом или после него:

```text
Индекс
```

В строке использовать тот же шаблон:

```django
{% capper_trust_badge expert.trust_index %}
```

Сортировка:

- для группы `all` и периода `all-time` сортировать по trust index как основной логике;
- для конкретного месяца, например `/cappers-table/all/2026-08/`, тоже учитывать trust index, но можно сделать месячные метрики tie-breaker;
- если выбран конкретный спорт, использовать trust index как общий показатель доверия, а sport metrics как вторичный порядок.

Пример ключа сортировки в `build_capper_table_context()`:

```python
rows.sort(
    key=lambda row: (
        row["trust_index"],
        row["roi"],
        row["bets"],
        row["wins"],
        row["followers"],
        row["username"].lower(),
    ),
    reverse=True,
)
```

Если нужно сохранить единый порядок с `/cappers-statistics/`, использовать `_canonical_rank_order()`, но сама `_canonical_rank_order()` после шага 1 уже должна быть trust-based.

Критерий готовности: в таблице есть явная колонка "Индекс", и позиции совпадают с идеей "выше тот, у кого выше общий индекс доверия", а не только ROI/прибыль.

## 3. Добавить пересчет, тесты и пояснение в UI

Проверить, что `trust_index` актуально пересчитывается:

- `cabinet/signals.py` уже вызывает `refresh_capper_trust_index`;
- есть команда `cabinet/management/commands/refresh_trust_indexes.py`;
- после изменения формулы/влияния запустить полный пересчет:

```bash
python manage.py refresh_trust_indexes
```

Добавить тесты:

- эксперт с более высоким `trust_index` должен быть выше эксперта с высоким ROI, но плохим trust index;
- при равном `trust_index` выше идет эксперт с лучшим стабилизированным ROI;
- `/cappers-table/all/2026-08/` возвращает строки в trust-based порядке;
- колонка индекса доверия есть в HTML таблицы;
- `cappers-statistics` и `cappers-table` используют один и тот же канонический порядок.

UI-пояснение:

- на `/cappers-statistics/` добавить короткий tooltip/подпись: "Индекс доверия учитывает ROI, просадку, стабильность, объем истории, средний коэффициент, активность и точность уверенности";
- на `/cappers-table/` добавить title к колонке "Индекс";
- не скрывать ROI: ROI остается метрикой эффективности, но не единственным рейтингом.

Команды проверки:

```bash
python manage.py refresh_trust_indexes
python manage.py test front cabinet
```

Критерий готовности: пользователь видит, что индекс доверия не просто бейдж, а главный фактор общего рейтинга и таблицы капперов.
