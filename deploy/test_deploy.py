"""Exercise deploy orchestration without contacting Docker or the server."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class DeployTests(unittest.TestCase):
    def run_deploy(self, *, migration_fails=False, **flags):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "deploy").mkdir()
            (root / ".env").touch()
            (root / "entrypoint.sh").touch()
            shutil.copyfile(Path(__file__).with_name("deploy.sh"), root / "deploy/deploy.sh")
            executable = root / "docker"
            executable.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "with open(os.environ['DEPLOY_TEST_LOG'], 'a') as log:\n"
                "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                "if 'run' in sys.argv and 'migrate' in sys.argv:\n"
                "    sys.exit(int(os.environ['DEPLOY_TEST_MIGRATION_FAILS']))\n"
            )
            executable.chmod(0o755)
            log = root / "commands.jsonl"
            env = {
                **os.environ,
                **{key: "0" for key in (
                    "DEPLOY_BUILD", "DEPLOY_FULL_RECREATE", "DEPLOY_RESTART_APP",
                    "DEPLOY_RESTART_NGINX", "DEPLOY_PRUNE", "DEPLOY_LIVE_WS",
                )},
                **flags,
                "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                "DEPLOY_TEST_LOG": str(log),
                "DEPLOY_TEST_MIGRATION_FAILS": str(int(migration_fails)),
            }
            result = subprocess.run(
                ["bash", "deploy/deploy.sh"], cwd=root, env=env,
                capture_output=True, text=True,
            )
            commands = [json.loads(line) for line in log.read_text().splitlines()]
        return result, commands

    def test_code_deploy_reloads_app_and_live_services_without_building(self):
        result, commands = self.run_deploy(DEPLOY_RESTART_APP="1", DEPLOY_LIVE_WS="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any("build" in cmd or "--build" in cmd for cmd in commands))
        migration = next(i for i, cmd in enumerate(commands) if "run" in cmd and "migrate" in cmd)
        for service in ("web", "celery", "celery-beat", "telegram-bot", "neurokeff-live", "neurokeff-odds"):
            index, command = next((i, cmd) for i, cmd in enumerate(commands) if service in cmd)
            self.assertGreater(index, migration)
            for option in ("--no-build", "--force-recreate", "--no-deps"):
                self.assertIn(option, command)

    def test_requested_build_and_full_deploy_build_once_before_migrations(self):
        for flag in ("DEPLOY_BUILD", "DEPLOY_FULL_RECREATE"):
            with self.subTest(flag=flag):
                result, commands = self.run_deploy(**{flag: "1", "DEPLOY_LIVE_WS": "1"})
                self.assertEqual(result.returncode, 0, result.stderr)
                builds = [i for i, cmd in enumerate(commands) if "build" in cmd]
                self.assertEqual(len(builds), 1)
                migration = next(i for i, cmd in enumerate(commands) if "migrate" in cmd)
                self.assertLess(builds[0], migration)
                self.assertFalse(any("--build" in cmd for cmd in commands))
                self.assertTrue(any("web" in cmd and "--force-recreate" in cmd for cmd in commands))

    def test_migration_failure_stops_before_app_recreation_and_pruning(self):
        result, commands = self.run_deploy(
            DEPLOY_RESTART_APP="1", DEPLOY_LIVE_WS="1", DEPLOY_PRUNE="1",
            migration_fails=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("web" in cmd or "neurokeff-live" in cmd or "prune" in cmd for cmd in commands))

    def test_no_app_changes_only_ensures_live_services_are_running(self):
        result, commands = self.run_deploy(DEPLOY_LIVE_WS="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any("build" in cmd or "--build" in cmd or "--force-recreate" in cmd for cmd in commands))
        self.assertFalse(any("web" in cmd for cmd in commands))
        live = next(cmd for cmd in commands if "neurokeff-live" in cmd)
        self.assertIn("--no-build", live)
        self.assertIn("--no-deps", live)


if __name__ == "__main__":
    unittest.main()
