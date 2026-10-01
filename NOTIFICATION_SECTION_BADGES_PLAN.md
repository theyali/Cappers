# Notification Section Badges Plan

## Goal

Show a small unread dot next to the exact site/profile section that has unread notification activity, for example copybetting, predictions, followers, achievements, bonuses, referrals, and header dropdown items.

The templates must not calculate notification state. They should only read prepared boolean/count values.

## Performance Contract

- No per-template unread counts.
- No per-section `Notification.objects.filter(...).count()` on normal page render.
- One cheap indexed query per authenticated request to load current section states.
- Writes update an aggregate table when notifications are created or marked read.
- The system must remain fine for 1k+ users and scale by indexed user/section rows.

## Data Model

Add `NotificationSectionState`:

- `user`
- `section`
- `unread_count`
- `latest_notification`
- `updated_at`

Unique key: `(user, section)`.

Main read path:

```python
NotificationSectionState.objects.filter(user=request.user, unread_count__gt=0)
```

## Section Mapping

Initial mapping:

- `prediction_like`, `prediction_favorite`, `own_coupon_settled` -> `predictions`
- `copybetting` -> `copybetting`
- `new_follower` -> `followers`
- `paid_subscription` -> `earnings`
- `achievement` -> `achievements`
- `bonus_daily_task` -> `bonus_tasks`
- `bonus_streak`, `bonus_level` -> `bonus_levels`
- `bonus_roulette` -> `bonuses`
- `bonus_referral` -> `referrals`
- `new_prediction`, `requested_match_prediction`, `favorite_settled` -> `following`
- `match_prediction`, `match_reminder` -> `matches`
- `tournament_started`, `tournament_finished` -> `tournaments`
- `admin_campaign` -> no profile section by default

## Rendering

Expose prepared context:

- `notification_section_badges`: `{section: bool}`
- `notification_section_counts`: `{section: unread_count}`

Use it in:

- `templates/front/includes/_main_header.html`
- `templates/cabinet/includes/_profile_tab_links.html`
- `templates/cabinet/includes/_profile_tabs_sidebar.html`

The dot class remains `nav-profile-dropdown-dot` for visual consistency.

## Read Handling

When a notification is marked read:

1. Mark the row read.
2. Decrement the mapped section aggregate.
3. Return fresh section badge payload in JSON.

When all notifications are marked read:

1. Mark all unread rows read.
2. Clear all section aggregates for the user.
3. Return empty section badge payload.

## Realtime Handling

The existing summary endpoint should include section badge payload so the header/dropdown/sidebar can update dots without full reload.

## Rollout Steps

1. Add model and migration.
2. Add section mapping and aggregate update helpers.
3. Wire notification creation/read paths to aggregate helpers.
4. Add context processor for prepared flags/counts.
5. Render dots in header dropdown and profile sidebar.
6. Add lightweight JS update for realtime and mark-read responses.
7. Add tests for create, read-one, read-all, and template dots.
8. Backfill aggregate rows for existing unread notifications.

