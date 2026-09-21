import shutil
import tempfile
from io import BytesIO
from io import StringIO
from pathlib import Path
from urllib.error import URLError
from unittest.mock import patch

from django.core.management import call_command
from django.db.models.signals import post_save
from django.test import TestCase, override_settings
from PIL import Image

from game.models import (
    Country,
    League,
    Sport,
    Team,
    Venue,
    league_logo_upload_path,
    team_logo_upload_path,
)
from game.services.local_logos import sync_entity_logo
from game.services.match_sync import MatchSyncService


class FakeImageResponse:
    def __init__(
        self,
        payload: bytes,
        content_type: str = "image/png",
        *,
        content_length: int | str | None = None,
    ):
        self._buffer = BytesIO(payload)
        self.headers = {"Content-Type": content_type}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
        else:
            self.headers["Content-Length"] = str(len(payload))

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self._buffer.close()


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(output, format="PNG")
    return output.getvalue()


class LocalLogoServiceTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="cappers-local-logos-")
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_root,
            LOCAL_LOGO_DOWNLOAD_ENABLED=True,
            LOCAL_LOGO_TIMEOUT=2,
            LOCAL_LOGO_MAX_BYTES=1024 * 1024,
            LOCAL_LOGO_WEBP_QUALITY=82,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, True)

        self.football = Sport.objects.create(
            code="football",
            name="Football",
            name_ru="Футбол",
        )

    @patch("game.services.local_logos._logo_opener.open")
    def test_team_logo_is_saved_as_webp_and_not_downloaded_twice(self, mocked_open):
        mocked_open.return_value = FakeImageResponse(png_bytes())
        team = Team.objects.create(
            external_id=1001,
            sport=self.football,
            name="Test Team",
            remote_logo_url="https://cdn.example/team.png",
        )

        downloaded = sync_entity_logo(
            team,
            field_name="logo",
            remote_url=team.remote_logo_url,
            target_name=team_logo_upload_path(team, ""),
        )

        team.refresh_from_db()
        self.assertTrue(downloaded)
        self.assertEqual(team.logo.name, f"football/team/{team.pk}.webp")
        saved_path = Path(self.media_root) / team.logo.name
        self.assertTrue(saved_path.exists())
        with Image.open(saved_path) as image:
            self.assertEqual(image.format, "WEBP")

        mocked_open.reset_mock()
        downloaded_again = sync_entity_logo(
            team,
            field_name="logo",
            remote_url=team.remote_logo_url,
            target_name=team_logo_upload_path(team, ""),
        )
        self.assertFalse(downloaded_again)
        mocked_open.assert_not_called()

    @patch("game.services.local_logos._logo_opener.open")
    def test_basketball_league_uses_basket_media_path(self, mocked_open):
        mocked_open.return_value = FakeImageResponse(png_bytes())
        basketball = Sport.objects.create(
            code="basketball",
            name="Basketball",
            name_ru="Баскетбол",
        )
        league = League.objects.create(
            external_id=2001,
            sport=basketball,
            name="Test League",
            remote_logo_url="https://cdn.example/league.png",
        )

        sync_entity_logo(
            league,
            field_name="logo",
            remote_url=league.remote_logo_url,
            target_name=league_logo_upload_path(league, ""),
        )

        league.refresh_from_db()
        self.assertEqual(league.logo.name, f"basket/league/{league.pk}.webp")

    @patch("game.services.local_logos._logo_opener.open")
    def test_rejects_non_http_url_without_network_request(self, mocked_open):
        team = Team.objects.create(
            external_id=1002,
            sport=self.football,
            name="Bad URL Team",
            remote_logo_url="file:///tmp/team.png",
        )

        downloaded = sync_entity_logo(
            team,
            field_name="logo",
            remote_url=team.remote_logo_url,
            target_name=team_logo_upload_path(team, ""),
        )

        self.assertFalse(downloaded)
        mocked_open.assert_not_called()
        team.refresh_from_db()
        self.assertFalse(team.logo)

    @patch("game.services.local_logos._logo_opener.open")
    def test_passes_configured_timeout_to_remote_opener(self, mocked_open):
        mocked_open.return_value = FakeImageResponse(png_bytes())
        team = Team.objects.create(
            external_id=1003,
            sport=self.football,
            name="Timeout Team",
            remote_logo_url="https://cdn.example/timeout.png",
        )

        sync_entity_logo(
            team,
            field_name="logo",
            remote_url=team.remote_logo_url,
            target_name=team_logo_upload_path(team, ""),
        )

        _, kwargs = mocked_open.call_args
        self.assertEqual(kwargs["timeout"], 2)

    @override_settings(LOCAL_LOGO_MAX_BYTES=16)
    @patch("game.services.local_logos._logo_opener.open")
    def test_rejects_content_length_over_limit(self, mocked_open):
        mocked_open.return_value = FakeImageResponse(
            png_bytes(),
            content_length=1024,
        )
        team = Team.objects.create(
            external_id=1004,
            sport=self.football,
            name="Large Header Team",
            remote_logo_url="https://cdn.example/large-header.png",
        )

        downloaded = sync_entity_logo(
            team,
            field_name="logo",
            remote_url=team.remote_logo_url,
            target_name=team_logo_upload_path(team, ""),
        )

        self.assertFalse(downloaded)
        team.refresh_from_db()
        self.assertFalse(team.logo)

    @override_settings(LOCAL_LOGO_MAX_BYTES=16)
    @patch("game.services.local_logos._logo_opener.open")
    def test_rejects_actual_payload_over_limit_without_content_length(self, mocked_open):
        mocked_open.return_value = FakeImageResponse(
            b"x" * 32,
            content_type="application/octet-stream",
            content_length="invalid",
        )
        team = Team.objects.create(
            external_id=1005,
            sport=self.football,
            name="Large Body Team",
            remote_logo_url="https://cdn.example/large-body.png",
        )

        downloaded = sync_entity_logo(
            team,
            field_name="logo",
            remote_url=team.remote_logo_url,
            target_name=team_logo_upload_path(team, ""),
        )

        self.assertFalse(downloaded)
        team.refresh_from_db()
        self.assertFalse(team.logo)

    @patch("game.services.local_logos._logo_opener.open")
    def test_rejects_empty_response(self, mocked_open):
        mocked_open.return_value = FakeImageResponse(
            b"",
            content_type="application/octet-stream",
        )
        team = Team.objects.create(
            external_id=1006,
            sport=self.football,
            name="Empty Team",
            remote_logo_url="https://cdn.example/empty.png",
        )

        downloaded = sync_entity_logo(
            team,
            field_name="logo",
            remote_url=team.remote_logo_url,
            target_name=team_logo_upload_path(team, ""),
        )

        self.assertFalse(downloaded)
        team.refresh_from_db()
        self.assertFalse(team.logo)

    @patch("game.services.local_logos._logo_opener.open")
    def test_rejects_unsupported_content_type(self, mocked_open):
        mocked_open.return_value = FakeImageResponse(
            b"<html>not an image</html>",
            content_type="text/html",
        )
        team = Team.objects.create(
            external_id=1011,
            sport=self.football,
            name="HTML Team",
            remote_logo_url="https://cdn.example/logo",
        )

        downloaded = sync_entity_logo(
            team,
            field_name="logo",
            remote_url=team.remote_logo_url,
            target_name=team_logo_upload_path(team, ""),
        )

        self.assertFalse(downloaded)
        team.refresh_from_db()
        self.assertFalse(team.logo)

    @patch("game.services.local_logos._logo_opener.open")
    def test_generic_content_type_is_allowed_when_bytes_are_valid_image(self, mocked_open):
        mocked_open.return_value = FakeImageResponse(
            png_bytes(),
            content_type="application/octet-stream",
        )
        team = Team.objects.create(
            external_id=1007,
            sport=self.football,
            name="Generic Content Team",
            remote_logo_url="https://cdn.example/generic",
        )

        downloaded = sync_entity_logo(
            team,
            field_name="logo",
            remote_url=team.remote_logo_url,
            target_name=team_logo_upload_path(team, ""),
        )

        self.assertTrue(downloaded)
        team.refresh_from_db()
        self.assertTrue(team.logo)

    @patch("game.services.local_logos._logo_opener.open")
    def test_rejects_invalid_image_bytes(self, mocked_open):
        mocked_open.return_value = FakeImageResponse(
            b"not-an-image",
            content_type="image/png",
        )
        team = Team.objects.create(
            external_id=1008,
            sport=self.football,
            name="Broken Image Team",
            remote_logo_url="https://cdn.example/broken.png",
        )

        downloaded = sync_entity_logo(
            team,
            field_name="logo",
            remote_url=team.remote_logo_url,
            target_name=team_logo_upload_path(team, ""),
        )

        self.assertFalse(downloaded)
        team.refresh_from_db()
        self.assertFalse(team.logo)

    @patch("game.services.local_logos._logo_opener.open")
    def test_network_error_is_swallowed(self, mocked_open):
        mocked_open.side_effect = URLError("offline")
        team = Team.objects.create(
            external_id=1009,
            sport=self.football,
            name="Offline Team",
            remote_logo_url="https://cdn.example/offline.png",
        )

        downloaded = sync_entity_logo(
            team,
            field_name="logo",
            remote_url=team.remote_logo_url,
            target_name=team_logo_upload_path(team, ""),
        )

        self.assertFalse(downloaded)
        team.refresh_from_db()
        self.assertFalse(team.logo)

    @patch("game.services.local_logos._logo_opener.open")
    def test_force_replaces_existing_target(self, mocked_open):
        mocked_open.return_value = FakeImageResponse(png_bytes())
        team = Team.objects.create(
            external_id=1010,
            sport=self.football,
            name="Force Team",
            remote_logo_url="https://cdn.example/force.png",
        )
        target_name = team_logo_upload_path(team, "")

        self.assertTrue(
            sync_entity_logo(
                team,
                field_name="logo",
                remote_url=team.remote_logo_url,
                target_name=target_name,
            )
        )
        first_bytes = (Path(self.media_root) / target_name).read_bytes()

        replacement = BytesIO()
        Image.new("RGB", (8, 8), (0, 255, 0)).save(replacement, format="PNG")
        mocked_open.return_value = FakeImageResponse(replacement.getvalue())

        self.assertTrue(
            sync_entity_logo(
                team,
                field_name="logo",
                remote_url=team.remote_logo_url,
                target_name=target_name,
                force=True,
            )
        )
        second_bytes = (Path(self.media_root) / target_name).read_bytes()

        self.assertNotEqual(first_bytes, second_bytes)
        self.assertEqual(mocked_open.call_count, 2)

    @patch("game.services.local_logos._logo_opener.open")
    def test_sync_entity_logo_does_not_emit_post_save(self, mocked_open):
        mocked_open.return_value = FakeImageResponse(png_bytes())
        team = Team.objects.create(
            external_id=1012,
            sport=self.football,
            name="Signal Team",
            remote_logo_url="https://cdn.example/signal.png",
        )
        calls = []

        def receiver(**kwargs):
            calls.append(kwargs["instance"].pk)

        post_save.connect(receiver, sender=Team, weak=False)
        self.addCleanup(post_save.disconnect, receiver, sender=Team)

        downloaded = sync_entity_logo(
            team,
            field_name="logo",
            remote_url=team.remote_logo_url,
            target_name=team_logo_upload_path(team, ""),
        )

        self.assertTrue(downloaded)
        self.assertEqual(calls, [])

    def test_country_and_venue_keep_remote_logo_url_without_local_download(self):
        service = MatchSyncService()
        country_url = "https://cdn.example/country.png"
        venue_url = "https://cdn.example/venue.png"

        country = service._sync_country(
            {
                "id": 4001,
                "code": "AZ",
                "name": {"en": "Azerbaijan", "ru": "Азербайджан"},
                "logo": country_url,
            }
        )
        venue = service._sync_venue(
            {
                "id": 5001,
                "name": {"en": "Arena", "ru": "Арена"},
                "logo": venue_url,
            }
        )

        self.assertIsInstance(country, Country)
        self.assertIsInstance(venue, Venue)
        self.assertEqual(country.remote_logo_url, country_url)
        self.assertEqual(venue.remote_logo_url, venue_url)
        self.assertFalse(hasattr(country, "logo"))
        self.assertFalse(hasattr(venue, "logo"))

    @patch("game.services.local_logos._logo_opener.open")
    def test_logo_download_error_keeps_team_and_remote_url(self, mocked_open):
        mocked_open.side_effect = URLError("offline")
        team = Team.objects.create(
            external_id=1013,
            sport=self.football,
            name="Existing Team",
            remote_logo_url="https://cdn.example/old.png",
        )
        team.logo = team_logo_upload_path(team, "")
        team.save(update_fields=["logo"])
        existing_name = team.logo.name

        payload = {
            "id": 1013,
            "name": {"en": "Existing Team", "ru": "Существующая команда"},
            "logo": "https://cdn.example/new.png",
        }

        with self.captureOnCommitCallbacks(execute=True):
            synced = MatchSyncService()._sync_team(payload, self.football, None)

        synced.refresh_from_db()
        self.assertEqual(synced.remote_logo_url, payload["logo"])
        self.assertEqual(synced.logo.name, existing_name)

    def test_logo_url_properties_are_safe_for_empty_fields(self):
        team = Team.objects.create(
            external_id=1014,
            sport=self.football,
            name="No Logo Team",
        )
        league = League.objects.create(
            external_id=2014,
            sport=self.football,
            name="No Logo League",
        )

        self.assertEqual(team.logo_url, "")
        self.assertEqual(league.logo_url, "")

    @patch("game.management.commands.download_entity_logos.sync_entity_logo")
    def test_download_entity_logos_skips_existing_by_default(self, mocked_sync):
        team = Team.objects.create(
            external_id=1015,
            sport=self.football,
            name="Command Team",
            remote_logo_url="https://cdn.example/command-team.png",
            logo="football/team/existing.webp",
        )
        mocked_sync.return_value = False
        stdout = StringIO()

        call_command("download_entity_logos", "--model", "team", stdout=stdout)

        mocked_sync.assert_called_once_with(
            team,
            field_name="logo",
            remote_url=team.remote_logo_url,
            target_name=team_logo_upload_path(team, ""),
            force=False,
        )
        self.assertIn("пропущено 1", stdout.getvalue())

    @patch("game.management.commands.download_entity_logos.sync_entity_logo")
    def test_download_entity_logos_passes_force(self, mocked_sync):
        team = Team.objects.create(
            external_id=1016,
            sport=self.football,
            name="Forced Command Team",
            remote_logo_url="https://cdn.example/forced-team.png",
        )
        mocked_sync.return_value = True

        call_command(
            "download_entity_logos",
            "--model",
            "team",
            "--force",
            stdout=StringIO(),
        )

        mocked_sync.assert_called_once_with(
            team,
            field_name="logo",
            remote_url=team.remote_logo_url,
            target_name=team_logo_upload_path(team, ""),
            force=True,
        )

    @patch("game.management.commands.download_entity_logos.sync_entity_logo")
    def test_download_entity_logos_dry_run_does_not_download(self, mocked_sync):
        Team.objects.create(
            external_id=1017,
            sport=self.football,
            name="Dry Run Team",
            remote_logo_url="https://cdn.example/dry-run.png",
        )

        call_command(
            "download_entity_logos",
            "--model",
            "team",
            "--dry-run",
            stdout=StringIO(),
        )

        mocked_sync.assert_not_called()

    @patch("game.services.match_sync.sync_entity_logo")
    def test_match_sync_saves_remote_url_and_calls_local_logo_service(self, mocked_sync):
        payload = {
            "id": 3001,
            "name": {"en": "Synced Team", "ru": "Команда"},
            "logo": "https://cdn.example/synced-team.png",
        }

        with self.captureOnCommitCallbacks(execute=True):
            team = MatchSyncService()._sync_team(payload, self.football, None)

        self.assertEqual(team.remote_logo_url, payload["logo"])
        mocked_sync.assert_called_once_with(
            team,
            field_name="logo",
            remote_url=payload["logo"],
            target_name=team_logo_upload_path(team, ""),
        )
