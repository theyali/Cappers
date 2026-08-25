from django.db import models
from django.utils.text import slugify
from unidecode import unidecode
from transliterate import translit
from django.db import models
from unidecode import unidecode
from django.db.models import Q
from django.core.validators import FileExtensionValidator
from django.db import models
from django.conf import settings
from django.utils.text import slugify
from django.utils import timezone
from django.urls import reverse
from ckeditor.fields import RichTextField
# import pytz
from unidecode import unidecode as uni


SPORT_CHOICES = [
    ('soccer', 'Футбол'),
    ('hockey', 'Хоккеи'),
]
STATUS_CHOICES = (
    ('draft', 'Draft'),
    ('published', 'Published'),
)

def team_image_upload_path(instance, filename):
    """
    Возвращает путь вида 'team_images/<значение instance.sport>/<имя файла>'.
    """
    # instance.sport — это уже строка, например "soccer"
    return f'team_images/{instance.sport}/{filename}'


class Country(models.Model):
    code = models.CharField(max_length=10, unique=True, db_index=True)
    name = models.CharField(max_length=100, verbose_name="Название страны")  # без unique
    name_ru = models.CharField(max_length=100, blank=True, null=True)
    image_path = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self): return self.name

    class Meta:
        verbose_name = "Страна"
        verbose_name_plural = "Страны"


class Sport(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50)
    name_ru = models.CharField(max_length=100, blank=True, null=True)
    image = models.FileField(
        upload_to="sports/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=["png", "jpg", "jpeg", "webp", "svg"])],
    )

    def __str__(self):
        return self.name


class Venue(models.Model):
    api_id = models.IntegerField(blank=True, null=True, db_index=True)
    name = models.CharField(max_length=150)
    name_ru = models.CharField(max_length=150, blank=True, null=True)
    city = models.CharField(max_length=150, blank=True, default="")
    city_ru = models.CharField(max_length=150, blank=True, null=True)
    capacity = models.IntegerField(null=True, blank=True)
    image_path = models.CharField(max_length=255, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    surface = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["api_id"],
                condition=Q(api_id__isnull=False),
                name="uniq_venue_api_id_not_null",
            ),
        ]

class League(models.Model):
    sport = models.ForeignKey(Sport, related_name='leagues', on_delete=models.CASCADE)
    league_id = models.IntegerField(db_index=True, unique=True)
    name = models.CharField(max_length=100, verbose_name="Название лиги")
    name_ru = models.CharField(max_length=100, blank=True, null=True)
    image_path = models.CharField(max_length=255, blank=True, null=True)
    country = models.ForeignKey(Country, related_name='leagues', on_delete=models.CASCADE, blank=True, null=True)
    type = models.CharField(max_length=100, blank=True, null=True)
    league_rank = models.IntegerField(blank=True, null=True)

    def __str__(self): return f"{self.name} - {self.league_id} - {self.sport}"

    class Meta:
        verbose_name = "Лига"
        verbose_name_plural = "Лиги"


class LeagueSeason(models.Model):
    """
    Сезон конкретной лиги (API-Football: seasons[].year + coverage).
    """
    league = models.ForeignKey(League, related_name="seasons", on_delete=models.CASCADE)
    year = models.IntegerField(db_index=True)  # API-Football в soccer даёт один год (2025)
    start_date = models.DateField(blank=True, null=True)
    end_date   = models.DateField(blank=True, null=True)
    is_current = models.BooleanField(default=False, db_index=True)
    current_round_name = models.CharField(max_length=200, null=True, blank=True)
    current_rounde_name_ru = models.CharField(max_length=200, null=True, blank=True)
    current_round_updated_at = models.DateTimeField(null=True, blank=True)
    # Берём coverage "как есть", чтобы не мигрировать схему при изменениях у провайдера
    coverage = models.JSONField(default=dict, blank=True)
    sport = models.ForeignKey(Sport, related_name='seasons', on_delete=models.CASCADE, blank=True, null=True)
    full_season_value = models.CharField(max_length=150, blank=True, null=True, help_text="Полное значение сезона из API (напр. '2025-2026')")
    # coverage.games.statistics.teams
    coverage_games_statistics_teams = models.BooleanField(null=True, blank=True)
    # coverage.games.statistics.players
    coverage_games_statistics_players = models.BooleanField(null=True, blank=True)
    # coverage.standings
    coverage_standings = models.BooleanField(null=True, blank=True)
    # coverage.players
    coverage_players = models.BooleanField(null=True, blank=True)
    # coverage.odds
    coverage_odds = models.BooleanField(null=True, blank=True)

    class Meta:
        verbose_name = "Сезон лиги"
        verbose_name_plural = "Сезоны лиг"
        constraints = [
            models.UniqueConstraint(fields=["league", "year"], name="uniq_league_year"),
        ]
        indexes = [
            models.Index(fields=["league", "is_current"]),
        ]

    def __str__(self):
        return f"{self.league.name} {self.year}"


class SeasonStandingGroup(models.Model):
    """
    Группа/конференция/этап внутри standings (напр. 'Western Conference').
    В API это приходит как поле 'group' у каждой строки.
    """
    season = models.ForeignKey(LeagueSeason, related_name="standing_groups", on_delete=models.CASCADE)
    # Полное текстовое имя группы из API (часто содержит и стадию, и год)
    name = models.CharField(max_length=200, db_index=True)
    # Опционально можно попытаться выделить "stage" отдельно; оставим поле на будущее
    stage = models.CharField(max_length=120, blank=True, null=True)

    class Meta:
        verbose_name = "Группа таблицы сезона"
        verbose_name_plural = "Группы таблиц сезона"
        constraints = [
            models.UniqueConstraint(fields=["season", "name"], name="uniq_season_group"),
        ]

    def __str__(self):
        return f"{self.season} · {self.name}"


class SeasonStandingRow(models.Model):
    """
    Строка турнирной таблицы (позиция команды в группе).
    """
    group = models.ForeignKey(SeasonStandingGroup, related_name="rows", on_delete=models.CASCADE)

    rank = models.PositiveIntegerField(db_index=True)
    # Привязываемся к Team, но держим и «сырой» api id + имя — на случай, если Team ещё не создана
    team = models.ForeignKey("Team", related_name="season_standings", on_delete=models.SET_NULL, null=True, blank=True)
    team_api_id = models.IntegerField(db_index=True, null=True, blank=True)
    team_name   = models.CharField(max_length=255, blank=True, null=True)

    points     = models.IntegerField(default=0)
    goals_diff = models.IntegerField(default=0)
    form       = models.CharField(max_length=30, blank=True, null=True)     # "WLWWW"
    status     = models.CharField(max_length=30, blank=True, null=True)     # "same", "up", "down"
    description = models.CharField(max_length=120, blank=True, null=True)   # "Qualification Playoffs"

    # Общая статистика
    all_played = models.IntegerField(default=0)
    all_win    = models.IntegerField(default=0)
    all_draw   = models.IntegerField(default=0)
    all_lose   = models.IntegerField(default=0)
    all_goals_for     = models.IntegerField(default=0)
    all_goals_against = models.IntegerField(default=0)

    # Дом/Выезд
    home_played = models.IntegerField(default=0)
    home_win    = models.IntegerField(default=0)
    home_draw   = models.IntegerField(default=0)
    home_lose   = models.IntegerField(default=0)
    home_goals_for     = models.IntegerField(default=0)
    home_goals_against = models.IntegerField(default=0)

    away_played = models.IntegerField(default=0)
    away_win    = models.IntegerField(default=0)
    away_draw   = models.IntegerField(default=0)
    away_lose   = models.IntegerField(default=0)
    away_goals_for     = models.IntegerField(default=0)
    away_goals_against = models.IntegerField(default=0)

    # Штамп из API
    updated_at_api = models.DateTimeField(blank=True, null=True)

    # На всякий — сохраняем сырой фрагмент строки, чтобы не потерять поля при будущих изменениях API
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Строка турнирной таблицы"
        verbose_name_plural = "Строки турнирной таблицы"
        constraints = [
            models.UniqueConstraint(
                fields=["group", "team_api_id"],
                name="uniq_group_team_api",
                condition=models.Q(team_api_id__isnull=False),
            ),
        ]
        indexes = [
            models.Index(fields=["group", "rank"], name="ssr_group_rank_idx"),
        ]

    def __str__(self):
        return f"{self.group}: #{self.rank} {self.team_name or (self.team.team_name if self.team else '')} ({self.points} pts)"




class Club(models.Model):
    """
    Клуб бойца / команды (джим, академия и т.п.).
    Для MMA сюда кладём team.id/team.name из API.
    """
    api_id = models.PositiveIntegerField(
        unique=True,
        db_index=True,
        verbose_name="ID клуба в API",
    )
    name = models.CharField(
        max_length=255,
        verbose_name="Название клуба (EN)",
    )
    name_ru = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Название клуба (RU)",
    )

    class Meta:
        verbose_name = "MMA Клуб"
        verbose_name_plural = "MMA Клубы"

    def __str__(self) -> str:
        return self.name


class FighterData(models.Model):
    team = models.OneToOneField(
        "Team",
        on_delete=models.CASCADE,
        related_name="fighter_data",
        verbose_name="Команда / боец",
    )
    # категории бойца = весовые дивизионы
    categories = models.ManyToManyField(
        "League",
        related_name="fighters",
        blank=True,
        verbose_name="Категории (дивизионы)",
        limit_choices_to={
            "sport__code": "mma",
            "type": "mma_category",
        },
    )

    # базовые атрибуты – на будущее
    height_cm = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Рост (см)"
    )
    weight_kg = models.FloatField(
        null=True, blank=True, verbose_name="Вес (кг)"
    )
    reach_cm = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Размах рук (см)"
    )
    stance = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        verbose_name="Стойка (orthodox, southpaw и т.п.)",
    )
    country_name = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        verbose_name="Страна (текстом)",
    )

    record_wins = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Победы"
    )
    record_losses = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Поражения"
    )
    record_draws = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Ничьи / no contest"
    )
    record_wins = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Победы"
    )
    record_losses = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Поражения"
    )
    record_draws = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="Ничьи / no contest"
    )
    record_raw = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Сырой рекорд из API",
    )
    class Meta:
        verbose_name = "Данные бойца MMA"
        verbose_name_plural = "Данные бойцов MMA"

    def __str__(self) -> str:
        return f"FighterData({self.team_id} - {self.team.team_name})"



class Team(models.Model):
    sport = models.ForeignKey(Sport, related_name='teams', on_delete=models.CASCADE)
    team_id = models.IntegerField(unique=True, db_index=True)
    team_name = models.CharField(max_length=255)
    team_name_ru = models.CharField(max_length=255, blank=True, null=True)
    image_path = models.CharField(max_length=255, blank=True, null=True)
    founded = models.IntegerField(blank=True, null=True)
    country = models.ForeignKey(Country, related_name='teams', on_delete=models.CASCADE, blank=True, null=True)
    team_venue = models.ForeignKey(Venue, related_name='teams', on_delete=models.CASCADE, blank=True, null=True)
    pari_id = models.IntegerField(blank=True, null=True)
    squad = models.JSONField(default=list, blank=True)
    squad_updated_at = models.DateTimeField(auto_now=True)
    club = models.ForeignKey("Club", related_name="teams", on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Клуб")
    slug = models.SlugField(max_length=255, unique=True, db_index=True, blank=True)  # ✅ ДОБАВЬ

    def _generate_unique_slug(self):
        # Transliterate the team_name to ASCII characters
        transliterated_name = unidecode(self.team_name)

        base_slug = slugify(f"{transliterated_name}-{self.team_id}", allow_unicode=False)
        unique_slug = base_slug
        num = 1
        while self.__class__.objects.filter(slug=unique_slug).exists():
            unique_slug = f"{base_slug}-{num}"
            num += 1
        return unique_slug

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.team_name
    
    class Meta:
        verbose_name = "Команда"
        verbose_name_plural = "Команды"


WINNER_CHOICES = (
    ("home", "Home"),
    ("away", "Away"),
    ("draw", "Draw"),
)
class Game(models.Model):
    TIME_STATUS_CHOICES = (
        ('0','Прематч'),('1','Live'),('2','Потеряна связь со скаутом'),('3','Завершен'),
        ('4','Отложен'),('5','Отменен'),('6','Выигранный из-за неявки'),('7','Прерванный'),('8','Прерванный и не будет доигран'),
    )
    sport = models.ForeignKey(Sport, related_name='games', on_delete=models.CASCADE)
    api_id = models.IntegerField(db_index=True, unique=True)
    game_date_time = models.DateTimeField(blank=True, null=True)
    league = models.ForeignKey(League, related_name='games', on_delete=models.CASCADE)
    league_season = models.ForeignKey(LeagueSeason, related_name="games", on_delete=models.SET_NULL, null=True, blank=True)
    home_team = models.ForeignKey(Team, related_name='home_games', on_delete=models.CASCADE)
    away_team = models.ForeignKey(Team, related_name='away_games', on_delete=models.CASCADE)
    time_status = models.CharField(max_length=100, choices=TIME_STATUS_CHOICES, default='1')
    first_time_score = models.CharField(max_length=150, blank=True, null=True)
    score = models.CharField(max_length=250, blank=True, null=True)
    event_name = models.CharField(max_length=511, blank=True, db_index=True)
    event_name_ru = models.CharField(max_length=511, blank=True, null=True)
    ai_generated_text = models.TextField(null=True, blank=True, default="", verbose_name="AI Generated Text", help_text="AI Generated Text")
    referee = models.CharField(max_length=150, blank=True, null=True)
    venue = models.ForeignKey(Venue, related_name='games', on_delete=models.CASCADE, blank=True, null=True)
    live_minute = models.IntegerField(null=True, blank=True)          # 47
    live_minute_str = models.CharField(max_length=16, null=True, blank=True)  # "45+2"
    tennis_serve = models.CharField(max_length=16, null=True, blank=True, verbose_name="Теннис Серв 1 / 2 (текущий игрок) ", help_text="Теннис Серв 1 / 2 (текущий игрок)")
    periods = models.JSONField(default=dict, blank=True, null=True)              # {"1H": "1-0", "2H": "0-1"}
    scoreboard = models.JSONField(default=dict, blank=True)           # всё, что распарсили (минуты, тексты, отладка)
    events = models.JSONField(default=list, blank=True, null=True)               # все события
    live_odds = models.JSONField(default=dict, blank=True)
    live_odds_updated_at = models.DateTimeField(null=True, blank=True)

    prematch_odds = models.JSONField(default=dict, blank=True)
    prematch_odds_updated_at = models.DateTimeField(null=True, blank=True)
    has_odds = models.BooleanField(default=False, db_index=True, verbose_name="Есть коэффициенты")
    odds_attempt = models.PositiveSmallIntegerField(default=0, db_index=True, verbose_name="Попыток получить коэффициенты")

    lineups = models.JSONField(default=dict, blank=True, null=True)  # { "items": [ ...api response... ] }
    lineups_updated_at = models.DateTimeField(null=True, blank=True)

    predictions = models.JSONField(default=dict, blank=True)  # NEW
    predictions_updated_at = models.DateTimeField(null=True, blank=True)  # NEW

    stats = models.JSONField(default=dict, blank=True, null=True)  # NEW
    stats_updated_at = models.DateTimeField(null=True, blank=True)  # NEW

    players = models.JSONField(default=dict, blank=True, null=True)
    players_updated_at = models.DateTimeField(null=True, blank=True)

    provider_status = models.CharField(max_length=16, null=True, blank=True, db_index=True)  # сырой статус от API
    current_period = models.CharField(max_length=50, null=True, blank=True, db_index=True)  # P1|P2|P3|OT|SO|INT|FT
    outcome = models.CharField(max_length=8, null=True, blank=True, db_index=True)  # 'REG'|'OT'|'SO'
    week = models.CharField(max_length=100,null=True,blank=True,db_index=True,help_text="Неделя тура (из API, например '8')",)
    stage = models.CharField(max_length=100,null=True,blank=True,db_index=True,help_text="Стадия турнира (из API, например 'Round of 16')",)
    is_ready = models.BooleanField(default=False, db_index=True)      # готов к выдаче клиентам
    last_seen_live_at = models.DateTimeField(null=True, blank=True, db_index=True)  # <— НОВОЕ
    not_seen_count = models.PositiveSmallIntegerField(default=0, db_index=True)  # ← НОВОЕ
    has_events = models.BooleanField(default=False, db_index=True)
    has_h2h = models.BooleanField(default=False, db_index=True)
    updated_standings = models.BooleanField(default=False, db_index=True)
    results_checked = models.BooleanField(default=False,db_index=True,
        help_text="Уже пробовали финализировать игру через results.json.php и не нашли её там",
    )
    results_checked_at = models.DateTimeField(null=True,blank=True,db_index=True,
        help_text="Когда последний раз пытались найти игру в results.json.php",
    )
    player_url = models.URLField(null=True,blank=True,db_index=True, default=None)

    mma_won_type = models.CharField( max_length=32, null=True, blank=True,
        db_index=True,
        help_text="Способ победы: KO, TKO, SUB, Points и т.п. (MMA)",
    )
    mma_ko_type = models.CharField(max_length=64,null=True,blank=True,
        db_index=True,
        help_text="Тип нокаута: Punch, Head Kick и т.п. (MMA)",
    )
    mma_target = models.CharField(max_length=64,null=True,blank=True,
        db_index=True,
        help_text="Цель удара/приёма: Head, Body и т.п. (MMA)",
    )
    mma_sub_type = models.CharField(max_length=128,null=True,blank=True,
        help_text="Тип сабмишна: Rear Naked Choke и т.п. (MMA)",
    )
    mma_finish_round = models.PositiveSmallIntegerField(null=True,blank=True,db_index=True,
        help_text="Раунд, в котором завершился бой (MMA)",
    )
    mma_finish_time_str = models.CharField(max_length=16,null=True,blank=True,
        help_text="Время окончания раунда в формате 'M:SS' (MMA)",
    )
    mma_finish_time_sec = models.PositiveIntegerField(null=True,blank=True,
        help_text="Время окончания раунда в секундах (MMA, удобно для сортировки/агрегаций)",
    )
    winner = models.CharField( max_length=8, choices=WINNER_CHOICES, null=True, blank=True,
        db_index=True,
        help_text="Победитель матча по финальному счёту: home/away/draw",
    )

    first_time_winner = models.CharField(max_length=8,choices=WINNER_CHOICES,null=True, blank=True,
        db_index=True,
        help_text="Победитель 1-го тайма (football) по first_time_score: home/away/draw",
    )

    # сколько игр реально использовано для формы (может быть < limit)
    home_form_games_count = models.PositiveIntegerField(default=0, verbose_name="Форма хозяев: игр")
    away_form_games_count = models.PositiveIntegerField(default=0, verbose_name="Форма гостей: игр")

    # форма: забито/пропущено (avg + total)
    home_team_conceded = models.FloatField(default=0, verbose_name="Пропущено хозяев (среднее)")
    away_team_conceded = models.FloatField(default=0, verbose_name="Пропущено гостей (среднее)")

    home_team_goals_total = models.PositiveIntegerField(default=0, verbose_name="Забито хозяев (всего)")
    away_team_goals_total = models.PositiveIntegerField(default=0, verbose_name="Забито гостей (всего)")
    home_team_conceded_total = models.PositiveIntegerField(default=0, verbose_name="Пропущено хозяев (всего)")
    away_team_conceded_total = models.PositiveIntegerField(default=0, verbose_name="Пропущено гостей (всего)")

    # h2h: пропущено (avg + total) + totals забитых
    h2h_home_conceded = models.FloatField(default=0, verbose_name="Пропущено хозяев (среднее) в h2h")
    h2h_away_conceded = models.FloatField(default=0, verbose_name="Пропущено гостей (среднее) в h2h")

    h2h_home_goals_total = models.PositiveIntegerField(default=0, verbose_name="Забито хозяев (всего) в h2h")
    h2h_away_goals_total = models.PositiveIntegerField(default=0, verbose_name="Забито гостей (всего) в h2h")
    h2h_home_conceded_total = models.PositiveIntegerField(default=0, verbose_name="Пропущено хозяев (всего) в h2h")
    h2h_away_conceded_total = models.PositiveIntegerField(default=0, verbose_name="Пропущено гостей (всего) в h2h")

    games_count = models.PositiveIntegerField(default=1, verbose_name="Количество игр")
    home_team_wins = models.PositiveIntegerField(default=0, verbose_name="Победы хозяев")
    away_team_wins = models.PositiveIntegerField(default=0, verbose_name="Победы гостей")
    home_team_loses = models.PositiveIntegerField(default=0, verbose_name="Поражения хозяев")
    away_team_loses = models.PositiveIntegerField(default=0, verbose_name="Поражения гостей")
    home_team_goals = models.FloatField(default=0, verbose_name="Голы хозяев среднее")
    away_team_goals = models.FloatField(default=0, verbose_name="Голы гостей среднее")
    h2h_home_wins = models.PositiveIntegerField(default=0,)
    h2h_away_wins = models.PositiveIntegerField(default=0,)
    h2h_home_goals = models.FloatField(default=0, verbose_name="Голы хозяев среднее в h2h")
    h2h_away_goals = models.FloatField(default=0, verbose_name="Голы гостей среднее в h2h")
    h2h_games_count = models.PositiveIntegerField(default=0,)

    home_mma_points_avg = models.FloatField(default=0, verbose_name="MMA: очки судей хозяев (среднее)")
    away_mma_points_avg = models.FloatField(default=0, verbose_name="MMA: очки судей гостей (среднее)")

    home_mma_points_conceded_avg = models.FloatField(default=0, verbose_name="MMA: очки судей против хозяев (среднее)")
    away_mma_points_conceded_avg = models.FloatField(default=0, verbose_name="MMA: очки судей против гостей (среднее)")

    home_mma_points_games_count = models.PositiveIntegerField(default=0, verbose_name="MMA: боёв с судейским счётом у хозяев")
    away_mma_points_games_count = models.PositiveIntegerField(default=0, verbose_name="MMA: боёв с судейским счётом у гостей")

    slug = models.SlugField(max_length=255, unique=True, db_index=True, blank=True)

    def __str__(self):
        return f"{self.home_team} vs {self.away_team}"

    def _legacy_slug(self):
        slug = (self.slug or "").strip()
        if not slug:
            return str(self.api_id)
        parts = slug.split("-", 1)
        if len(parts) > 1 and parts[0].isdigit() and parts[1]:
            return parts[1]
        return slug

    def _sport_slug(self):
        sport_value = (
            getattr(self.sport, "code", None)
            or getattr(self.sport, "name_ru", None)
            or getattr(self.sport, "name", None)
            or ""
        )
        return slugify(unidecode(sport_value), allow_unicode=False) or "sport"

    def _league_slug(self):
        league_value = (
            getattr(self.league, "name_ru", None)
            or getattr(self.league, "name", None)
            or ""
        )
        return slugify(unidecode(league_value), allow_unicode=False) or f"league-{self.league_id}"

    def get_absolute_url(self):
        slug_part = self._legacy_slug()
        return reverse(
            "single_match",
            kwargs={
                "sport": self._sport_slug(),
                "league": self._league_slug(),
                "game_id": self.api_id,
                "slug": slug_part,
            },
        )

    def get_time_status_display(self):
        return dict(self.TIME_STATUS_CHOICES).get(self.time_status, 'Unknown')

    def save(self, *args, **kwargs):
        if not self.slug:
            home_team_name_translit = slugify(translit(self.home_team.team_name, 'ru', reversed=True))
            away_team_name_translit = slugify(translit(self.away_team.team_name, 'ru', reversed=True))
            self.slug = f"{self.api_id}-{home_team_name_translit}-{away_team_name_translit}"
        super().save(*args, **kwargs)

    class Meta:
        indexes = [
            models.Index(fields=['sport', 'game_date_time']),
            models.Index(fields=['league', 'game_date_time']),
            models.Index(fields=['time_status']),
        ]
        verbose_name = "Игра"
        verbose_name_plural = "Игры"


class GameOdds(models.Model):
    game = models.OneToOneField(Game, on_delete=models.CASCADE, related_name="odds")
    home_win_bet = models.FloatField(null=True, blank=True)
    x_bet = models.FloatField(null=True, blank=True)
    away_win_bet = models.FloatField(null=True, blank=True)
    goals_over_2_5 = models.FloatField(null=True, blank=True)
    goals_under_2_5 = models.FloatField(null=True, blank=True)
    fora_1_0 = models.FloatField(null=True, blank=True)
    fora_2_0 = models.FloatField(null=True, blank=True)
    btts_yes = models.FloatField(null=True, blank=True)
    btts_no = models.FloatField(null=True, blank=True)
    d_1x = models.FloatField(null=True, blank=True)
    d_2x = models.FloatField(null=True, blank=True)

    first_time_home_win_bet = models.FloatField(null=True, blank=True)
    first_time_x_bet = models.FloatField(null=True, blank=True)
    first_time_away_win_bet = models.FloatField(null=True, blank=True)
    totals_all = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=['home_win_bet','x_bet','away_win_bet'])]
        verbose_name = "Коэффициенты"; verbose_name_plural = "Коэффициенты"



class Faq(models.Model):
    question = models.CharField(max_length=255, verbose_name="Вопрос")
    answer = models.TextField(verbose_name="Ответ")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")
    order = models.PositiveIntegerField(default=0, verbose_name="Порядок", help_text="Порядок отображения вопросов")
    def __str__(self):
        return self.question
    class Meta:
        verbose_name = "Вопрос"
        verbose_name_plural = "Вопросы"


class PredictionExpert(models.Model):
    name = models.CharField(max_length=150, verbose_name="Имя эксперта")
    slug = models.SlugField(max_length=180, unique=True, blank=True, verbose_name="Слаг")
    photo = models.ImageField(upload_to="experts/", blank=True, null=True, verbose_name="Фото")
    short_bio = models.TextField(blank=True, verbose_name="Краткая биография")
    experience = models.CharField(max_length=255, blank=True, verbose_name="Опыт в спортивной аналитике")
    qualification = models.TextField(blank=True, verbose_name="Квалификация")
    success_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name="Проходимость прогнозов, %",
    )
    predictions_count = models.PositiveIntegerField(default=0, verbose_name="Количество прогнозов")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")

    class Meta:
        verbose_name = "Эксперт прогнозов"
        verbose_name_plural = "Эксперты прогнозов"
        ordering = ("name", "pk")

    def __str__(self):
        return self.name

    def _generate_unique_slug(self):
        base_slug = slugify(unidecode(self.name or ""), allow_unicode=False) or "expert"
        unique_slug = base_slug
        num = 1

        while PredictionExpert.objects.filter(slug=unique_slug).exclude(pk=self.pk).exists():
            unique_slug = f"{base_slug}-{num}"
            num += 1

        return unique_slug

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("expert_detail", kwargs={"slug": self.slug})



class Article(models.Model):
    title = models.CharField(max_length=200)
    content = RichTextField(verbose_name="Содержание")
    excerpt = models.TextField(verbose_name="Краткое описание", blank=True)
    published_date = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    image = models.ImageField(upload_to='articles_images/', null=True, blank=True, verbose_name="Изображение для превью")
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    meta_title = models.CharField(max_length=200, blank=True, null=True, verbose_name="Meta Title")
    meta_description = models.TextField(blank=True, null=True, verbose_name="Meta Description")
    categories = models.ManyToManyField('blocks.Category', blank=True, verbose_name="Категории")
    bg_image = models.ImageField(upload_to='news_bg_images/', null=True, blank=True, verbose_name="Фоновое изображение для статьи")
    block_link = models.URLField(max_length=500, blank=True, null=True, verbose_name="Ссылка для блока статьи на главной странице")
    block_content = models.TextField(blank=True, null=True, verbose_name="Текст для блока статьи на главной странице")
    quote_text = models.TextField(blank=True, null=True, verbose_name="Текст цитаты для статьи")

    class Meta:
        verbose_name = "Статья"
        verbose_name_plural = "Статьи"

    def __str__(self):
        return self.title

    def _generate_unique_slug(self):
        base_slug = slugify(unidecode(self.title or ""), allow_unicode=False) or "article"
        unique_slug = base_slug
        num = 1

        while Article.objects.filter(slug=unique_slug).exclude(pk=self.pk).exists():
            unique_slug = f'{base_slug}-{num}'
            num += 1

        return unique_slug

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"/article/{self.slug}/"


class News(models.Model):
    title = models.CharField(max_length=200)
    content = RichTextField(verbose_name="Содержание")
    excerpt = models.TextField(verbose_name="Краткое описание", blank=True)
    published_date = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    image = models.ImageField(upload_to='articles_images/', null=True, blank=True, verbose_name="Изображение для превью")
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    meta_title = models.CharField(max_length=200, blank=True, null=True, verbose_name="Meta Title")
    meta_description = models.TextField(blank=True, null=True, verbose_name="Meta Description")
    categories = models.ManyToManyField('blocks.Category', blank=True, verbose_name="Категории")
    bg_image = models.ImageField(upload_to='news_bg_images/', null=True, blank=True, verbose_name="Фоновое изображение для новости")
    block_link = models.URLField(max_length=500, blank=True, null=True, verbose_name="Ссылка для блока новости на главной странице")
    block_content = models.TextField(blank=True, null=True, verbose_name="Текст для блока новости на главной странице")
    quote_text = models.TextField(blank=True, null=True, verbose_name="Текст цитаты для новости")
    sport = models.ForeignKey(Sport, related_name='news', on_delete=models.CASCADE, blank=True, null=True, verbose_name="Вид спорта")
    class Meta:
        verbose_name = "Новость"
        verbose_name_plural = "Новости"

    def __str__(self):
        return self.title

    def _generate_unique_slug(self):
        base_slug = slugify(unidecode(self.title or ""), allow_unicode=False) or "news"
        unique_slug = base_slug
        num = 1

        while News.objects.filter(slug=unique_slug).exclude(pk=self.pk).exists():
            unique_slug = f'{base_slug}-{num}'
            num += 1

        return unique_slug

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)
    def get_absolute_url(self):
        return f"/news/{self.slug}/"



class Bk(models.Model):
    name = models.CharField(max_length=100, verbose_name="Название")
    url = models.URLField(max_length=200, verbose_name="Ссылка")
    rate = models.FloatField(default=0.00, verbose_name="Рейтинг")
    logo = models.ImageField(upload_to='bk_logos/', verbose_name="Логотип")
    accordion_text = models.CharField(max_length=255, blank=True, null=True, verbose_name="Текст для аккордеона")
    bonuses_count = models.IntegerField(default=0, verbose_name="Количество бонусов")
    ios_link = models.URLField(max_length=500, blank=True, null=True, verbose_name="Ссылка на iOS приложение")
    android_link = models.URLField(max_length=500, blank=True, null=True, verbose_name="Ссылка на Android приложение")
    reviews_count = models.IntegerField(default=0, verbose_name="Количество отзывов")
    advantages = models.ManyToManyField('blocks.Element', blank=True, verbose_name="Преимущества букмекера", related_name="bk_advantages")
    disadvantages = models.ManyToManyField('blocks.Element', blank=True, verbose_name="Недостатки букмекера", related_name="bk_disadvantages")
    faqs = models.ManyToManyField(Faq, blank=True, verbose_name="FAQ букмекера")
    reviews = models.ManyToManyField('blocks.Review', blank=True, verbose_name="Отзывы о букмекере")
    status_str = models.CharField(max_length=255, blank=True, null=True, verbose_name="Статус букмекера")
    min_deposit = models.CharField(max_length=255, blank=True, null=True, verbose_name="Минимальный депозит")
    rating_place = models.IntegerField(blank=True, null=True, verbose_name="Место в рейтинге")
    margin_value = models.FloatField(blank=True, null=True, verbose_name="Маржа букмекера")
    accordions = models.ManyToManyField('blocks.Element', blank=True, verbose_name="Аккордеоны букмекера", related_name="bk_accordions")
    free_translations = models.ManyToManyField('blocks.Element', blank=True, verbose_name="Бесплатные трансляции букмекера", related_name="bk_free_translations")
    sport = models.ManyToManyField(Sport, blank=True, verbose_name="Виды спорта букмекера", related_name="bk_sports")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")
    slug = models.SlugField(unique=True, verbose_name="Слаг", blank=True, null=True)
    seo_title = models.CharField(max_length=255, blank=True, null=True, verbose_name="SEO заголовок")
    seo_description = models.TextField(max_length=500, blank=True, null=True, verbose_name="SEO описание")

    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name = "Букмекер"
        verbose_name_plural = "Букмекеры"

    def _generate_unique_slug(self):
        base_slug = slugify(unidecode(self.name or ""), allow_unicode=False) or "bks"
        unique_slug = base_slug
        num = 1

        while Bk.objects.filter(slug=unique_slug).exclude(pk=self.pk).exists():
            unique_slug = f"{base_slug}-{num}"
            num += 1

        return unique_slug

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"/bk/{self.slug}/"

    def get_reviews_count(self):
        return self.reviews.count()


class Bonus(models.Model):
    title = models.CharField(max_length=255, verbose_name="Заголовок бонуса")
    slug = models.SlugField(max_length=255, unique=True, blank=True, null=True, verbose_name="Слаг")
    description = models.TextField(verbose_name="Описание бонуса")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")
    bonus_value_text = models.CharField(max_length=255, blank=True, null=True, verbose_name="Текстовое описание размера бонуса (напр. '100% до 10 000₽')")
    bonus_image_preview = models.ImageField(upload_to='bonus_previews/', blank=True, null=True, verbose_name="Изображение для превью бонуса")
    bonus_link = models.URLField(max_length=500, blank=True, null=True, verbose_name="Ссылка для получения бонуса")
    is_forever_bonus = models.BooleanField(default=False, verbose_name="Постоянный бонус")
    show_in_comparison = models.BooleanField(default=False, verbose_name="Показывать в сравнении букмекеров")
    caterories = models.ManyToManyField('blocks.Category', blank=True, verbose_name="Категории бонуса")
    min_odds = models.FloatField(null=True, blank=True, verbose_name="Минимальный коэффициент для отыгрыша бонуса")
    expired_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата истечения бонуса")
    win_days = models.IntegerField(null=True, blank=True, verbose_name="Количество дней для отыгрыша бонуса")
    win = models.CharField(max_length=255, blank=True, null=True, verbose_name="Отыгрыш")
    min_depoit = models.CharField(max_length=255, blank=True, null=True, verbose_name="Минимальный депозит")
    how_to_get = models.TextField(blank=True, null=True, verbose_name="Как получить бонус")
    how_to_get_bonus_img = models.ImageField(upload_to='bonus_how_to_get_images/', blank=True, null=True, verbose_name="Изображение для раздела 'Как получить бонус'")
    how_to_withdraw = models.TextField(blank=True, null=True, verbose_name="Как вывести бонус")
    advantages = models.ManyToManyField('blocks.Element', blank=True, verbose_name="Преимущества бонуса", related_name="bonus_advantages")
    disadvantages = models.ManyToManyField('blocks.Element', blank=True, verbose_name="Недостатки бонуса", related_name="bonus_disadvantages")
    reviews = models.ManyToManyField('blocks.Review', blank=True, verbose_name="Отзывы о бонусе")
    bk = models.ForeignKey(Bk, related_name='bonuses', on_delete=models.CASCADE, blank=True, null=True, verbose_name="Букмекер")
    seo_title = models.CharField(max_length=255, blank=True, null=True, verbose_name="SEO заголовок")
    seo_description = models.TextField(max_length=500, blank=True, null=True, verbose_name="SEO описание")

    def _generate_unique_slug(self):
        base_slug = slugify(unidecode(self.title or ""), allow_unicode=False) or "bonus"
        unique_slug = base_slug
        num = 1

        while Bonus.objects.filter(slug=unique_slug).exclude(pk=self.pk).exists():
            unique_slug = f"{base_slug}-{num}"
            num += 1

        return unique_slug

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"/bonus/{self.slug}/"

    def __str__(self):
        return f"{self.id}-{self.title}"

    class Meta:
        verbose_name = "Бонус"
        verbose_name_plural = "Бонусы"
