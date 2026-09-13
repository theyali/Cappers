# План исправления рулетки

Ниже 10 шагов для выноса roulette в отдельный сервис внутри `cabinet` и исправления багов со спамом вращений, неверным подсчетом попыток и кликом по карточке выигрыша.

## 1. Сначала зафиксировать баги тестами

В `cabinet/tests/test_roulette_api.py` добавить тесты:

- пользователь с `available_spins=10` после 10 разных `operation_id` получает ровно 10 `RouletteSpin`, 11-й запрос возвращает `409 no_spins`;
- повтор одного и того же `operation_id` не списывает попытку второй раз;
- два быстрых POST с разными `operation_id` не могут списать больше доступного количества;
- приз `extra_spin` увеличивает попытки только один раз и корректно отражается в `attempts_after`.

## 2. Вынести рулетку в отдельный пакет внутри `cabinet`

Создать папку:

```text
cabinet/roulette/
```

Внутри разложить сервисные файлы:

```text
cabinet/roulette/__init__.py
cabinet/roulette/api.py
cabinet/roulette/spin_service.py
cabinet/roulette/state_service.py
cabinet/roulette/reward_service.py
cabinet/roulette/selectors.py
cabinet/roulette/errors.py
```

Важно: модели лучше пока не переносить физически, чтобы не ломать Django migrations. Оставить модели в текущих файлах:

```text
cabinet/roulette_models.py
cabinet/roulette_state.py
cabinet/roulette_history.py
cabinet/roulette_rewards.py
```

## 3. Оставить старые модули как совместимые обертки

Чтобы проект не сломался сразу, старые файлы должны импортировать новый код:

```python
# cabinet/roulette_spin_service.py
from .roulette.spin_service import *
```

Аналогично для:

```text
cabinet/roulette_api.py
cabinet/roulette_reward_service.py
cabinet/roulette_services.py
```

Потом постепенно поменять импорты в `cabinet/urls.py`, `front/context_processors.py`, тестах и админке.

## 4. Сделать один главный серверный метод вращения

В новом `cabinet/roulette/spin_service.py` оставить единственную точку входа:

```python
spin_roulette(user, operation_id, now=None)
```

Внутри обязательно:

- `transaction.atomic()`;
- нормализация `operation_id`;
- проверка существующего `RouletteSpin` по `operation_id`;
- `select_for_update()` для пользователя;
- `select_for_update()` для `UserRouletteState`;
- проверка `available_spins > 0`;
- списание попытки до выдачи награды;
- создание `RouletteSpin`;
- выдача награды;
- сохранение итогового `attempts_after`.

## 5. Усилить защиту от гонок на уровне базы

В `UserRouletteState.Meta.constraints` добавить constraint:

```python
models.CheckConstraint(
    check=models.Q(available_spins__gte=0),
    name="roulette_state_available_spins_nonneg",
)
```

Создать миграцию. Это защита от отрицательных попыток при ошибках кода.

## 6. Проверить daily refresh

В `UserRouletteState.refresh_daily_spins()` сейчас ежедневные попытки добавляются к текущим:

```python
self.available_spins += granted
```

Нужно явно решить бизнес-правило.

Если пользователю должно быть доступно максимум `daily_free_spins`, заменить логику на:

```python
self.available_spins = max(self.available_spins, granted)
```

Если дополнительные попытки должны сохраняться, добавить отдельные поля позже. Сейчас именно эта логика может объяснять ситуацию: должно быть 10, стало 16.

## 7. Разделить ежедневные и бонусные попытки

Правильное решение: добавить в `UserRouletteState` два поля:

```python
daily_spins
bonus_spins
```

А `available_spins` считать как сумму. Но если нужно быстро исправить баг, можно пока оставить одно поле и ограничить daily refresh через `max()`, как в шаге 6.

Для надежного варианта сделать так:

- `daily_spins` сбрасывается или выставляется раз в день;
- `bonus_spins` увеличивается только призом `extra_spin`;
- списание сначала из `daily_spins`, потом из `bonus_spins`;
- API возвращает `available_spins = daily_spins + bonus_spins`.

## 8. Исправить frontend state machine в `front/static/front/js/roulette.js`

Вместо отдельных флагов:

```js
spinning
requestPending
winCard
```

Ввести один статус:

```js
let spinPhase = 'idle';
// idle | requesting | animating | showing_result
```

`canSpin()` должен возвращать `true` только при:

```js
spinPhase === 'idle'
&& stateLoaded
&& enabled
&& availableSpins > 0
&& prizes.length > 0
```

## 9. Запретить новый spin при открытой карточке выигрыша

После `animateWinCard()` выставлять:

```js
spinPhase = 'showing_result';
```

При клике по canvas, если `spinPhase === 'showing_result'`, нужно только закрыть карточку:

```js
winCard = null;
spinPhase = 'idle';
draw();
return;
```

Новый запрос на `/spin/` в этот же клик отправлять нельзя. Это исправит баг: нажал на карточку "Ваш приз", и счетчик попыток поехал криво.

## 10. Финальная проверка

После изменений запустить:

```bash
python manage.py test cabinet.tests.test_roulette_api
```

Затем вручную проверить сценарии:

- 10 попыток дают ровно 10 вращений;
- спам кликами во время анимации не отправляет новые POST;
- клик по карточке выигрыша только закрывает карточку;
- повторный `operation_id` возвращает тот же `spin_id`;
- fixed badge обновляется через событие `cappers:roulette-attempts`;
- приз `extra_spin` корректно прибавляет попытку и не дублируется при повторе запроса.

## 11. Физически перенести отмеченные roulette-файлы в пакет

После того как совместимые обертки из шага 3 работают, перенести отмеченные файлы из корня `cabinet` внутрь `cabinet/roulette/`.

Целевая структура:

```text
cabinet/roulette/admin.py
cabinet/roulette/api.py
cabinet/roulette/history_admin.py
cabinet/roulette/history.py
cabinet/roulette/models.py
cabinet/roulette/reward_service.py
cabinet/roulette/rewards_admin.py
cabinet/roulette/rewards.py
cabinet/roulette/services.py
cabinet/roulette/spin_service.py
cabinet/roulette/state_admin.py
cabinet/roulette/state.py
```

Старые файлы в корне `cabinet` временно оставить как thin wrappers, чтобы Django imports и миграции не сломались:

```python
from .roulette.models import *
```

Так сделать для каждого старого `cabinet/roulette_*.py`. После полного обновления импортов и прохождения тестов эти wrappers можно удалить отдельной задачей.

## 12. Обновить импорты после переноса

После переноса заменить импорты по проекту с корневых файлов на новый пакет.

Примеры:

```python
from cabinet.roulette_spin_service import spin_roulette
```

заменить на:

```python
from cabinet.roulette.spin_service import spin_roulette
```

Проверить и обновить места:

- `cabinet/urls.py`;
- `front/context_processors.py`;
- `cabinet/tests/test_roulette_api.py`;
- все admin-файлы;
- все сервисы, которые импортируют `RouletteSpin`, `RoulettePrize`, `UserRouletteState`, `UserRouletteRewardState`.

После замены выполнить:

```bash
rg "roulette_" cabinet front templates
python manage.py test cabinet.tests.test_roulette_api
```

В `rg` не должно остаться импортов старых сервисных файлов, кроме временных wrappers и миграций.

## 13. Добавить фронтовую защиту от флуда с видимым состоянием кнопки

В `front/static/front/js/roulette.js` запретить повторный запуск, пока колесо крутится или результат показывается.

Для этого:

- при старте запроса выставлять `spinPhase = 'requesting'`;
- во время анимации выставлять `spinPhase = 'animating'`;
- после показа выигрыша выставлять `spinPhase = 'showing_result'`;
- разрешать новый spin только при `spinPhase === 'idle'`;
- клики во время `requesting` и `animating` полностью игнорировать.

Также изменить визуальное состояние центральной кнопки на canvas:

- текст в обычном состоянии: `Крутить`;
- во время запроса: `Загрузка...`;
- во время вращения: `Крутится...`;
- при открытой карточке выигрыша: `Закрыть приз`;
- цвет кнопки плавно менять через интерполяцию или CSS-подобную анимацию в `drawCenter()`;
- курсор во время блокировки менять с `pointer` на `wait` или `default`;
- `aria-label` тоже должен отражать текущее состояние, чтобы не было ложного "Нажмите, чтобы крутить".

Главное условие: пока колесо крутится, ни один новый POST на `data-roulette-spin-url` не должен уходить с фронта.
