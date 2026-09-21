import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from PIL import Image

from game.models import (
    League,
    Sport,
    Team,
    league_logo_upload_path,
    team_logo_upload_path,
)
from game.services.local_logos import sync_entity_logo
from game.services.match_sync import MatchSyncService


class FakeImageResponse:
    def __init__(self, payload: bytes, content_type: str = "image/png"):
        self._buffer = BytesIO(payload)
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(payload)),
        }

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

    @patch("game.services.local_logos.urlopen")
    def test_team_logo_is_saved_as_webp_and_not_downloaded_twice(self, mocked_urlopen):
        mocked_urlopen.return_value = FakeImageResponse(png_bytes())
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

        mocked_urlopen.reset_mock()
        downloaded_again = sync_entity_logo(
            team,
            field_name="logo",
            remote_url=team.remote_logo_url,
            target_name=team_logo_upload_path(team, ""),
        )
        self.assertFalse(downloaded_again)
        mocked_urlopen.assert_not_called()

    @patch("game.services.local_logos.urlopen")
    def test_basketball_league_uses_basket_media_path(self, mocked_urlopen):
        mocked_urlopen.return_value = FakeImageResponse(png_bytes())
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
