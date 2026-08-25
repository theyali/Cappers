import logging

logger = logging.getLogger(__name__)


class MatchSyncService:
    """Provider-independent match synchronization facade.

    Real provider integration and persistence are intentionally deferred.
    """

    def sync_upcoming(self) -> dict:
        logger.info("Upcoming match sync stub executed")
        return {"status": "stub", "scope": "upcoming"}

    def sync_live(self) -> dict:
        logger.info("Live match sync stub executed")
        return {"status": "stub", "scope": "live"}

    def sync_finished(self) -> dict:
        logger.info("Finished match sync stub executed")
        return {"status": "stub", "scope": "finished"}
