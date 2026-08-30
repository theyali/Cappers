-Во внешнем виде сайта не давай border элементам
-Избегай градиента и overlay
-Используй фирменные цвета сайта
    --blue: #0b56fa;
    --ink: #131313;
    --panel: #1f1f21;
    --muted: #707072;
    --yellow: #fbf110;


В проекте уже есть общий skeleton-сервис: front/static/front/js/skeleton.js и front/static/front/css/skeleton.css.

Нужно внедрять его во все блоки, которые заполняются или меняются через JS, чтобы не было layout shift.

Правила:
- Для async-блока добавить data-skeleton-block.
- Перед fetch вызывать window.CappersSkeleton?.loading(block).
- После вставки данных вызывать window.CappersSkeleton?.ready(block).
- Для изображений использовать wrapper с data-skeleton-image и обязательно width/height на img.
- Если JS меняет src изображения, после смены вызвать window.CappersSkeleton?.watchImage(wrapper).
- Не создавать большие блоки через JS без SSR/placeholder-контейнера финального размера.
- Сначала в шаблоне должен быть контейнер нужного размера, JS только заполняет его.

Обязательно не создавай лишние css файлы в проекте должен быь два css файла это  main и mobile