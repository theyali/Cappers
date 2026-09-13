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
