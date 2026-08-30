План: Анализ багов проекта Cappers
Провёл глубокий аудит кодовой базы. Вот что нашёл — сгруппировано по критичности.

🚨 Критические (могут привести к некорректным данным)
1. settle_finished_matches неатомарен
settlement.py — resolve_match_bets в @transaction.atomic, но весь цикл в settle_finished_matches — нет. При падении на середине часть матчей рассчитана, часть нет. settle_coupon вызывается без try/except.

2. settle_live_matches — та же проблема
live_settlement.py — идентичная структура, settle_coupon без обработки ошибок.

3. settle_predictions таска не включает live-settlement
game/tasks.py:175 — вызывает только settle_finished_matches(), пропуская settle_live_matches() и reconcile_pending_coupons().

⚠️ Высокие
4. Race condition в ensure_analyst_profile
signals.py — get_or_create без transaction.atomic() при двух одновременных запросах → IntegrityError.

5. Потенциальная рекурсия сигналов avatar
signals.py — sync_capper_avatar_to_user → User.save → ensure_analyst_profile → AnalystProfile.save → ... Нет флага для предотвращения цикла.

6. Двойная миграция при старте
start-web.sh + docker-compose.yml (migrate сервис) — миграция выполняется дважды. Избыточно и потенциально опасно.

7. Celery зависит от web (healthcheck)
docker-compose.yml — celery depends_on web condition: service_healthy. Celery worker не нуждается в web. При проблемах с web celery не запустится.

8. _refresh_local_match_state — возможно не определена
game/services/coupon_validation.py:66 — вызов функции, которая не видна в прочитанном коде. Нужно проверить строки 100+.

9. Match.build_slug — self.pk может быть None
models.py — f"match-{self.external_id or self.pk}" → None для несохранённого объекта.

⚡ Средние
10. Match.unique_constraint назван unique_football_match_... хотя применяется ко всем видам спорта.

11. Hardcoded LATEST_PREDICTIONS / DEMO_EXPERTS в views.py вместо запросов к БД.

12. website_settings context processor молча возвращает None при недоступности БД → шаблоны могут упасть с AttributeError.

13. _ensure_initial_bonus_locked в services.py — создаёт транзакцию INITIAL_BONUS даже при CAPPER_STARTING_BALANCE=0.

14. League.save() — slug из f"{self.name}-{self.external_id}" при пустом name даёт "-{id}".

15. Match._raw_localized — хардкод fallback "en"/"ru" не покрывает другие языки.

16. _telegram_payload в telegram_auth.py — не проверяет наличие auth_date до извлечения.

📋 Минорные
17. TG_BOT_TOKEN и TELEGRAM_BOT_TOKEN — дубликаты в settings.py.

18. NEUROKEFF_API_TOKEN пустой в .env.example — новички не поймут почему матчи не синхронизируются.