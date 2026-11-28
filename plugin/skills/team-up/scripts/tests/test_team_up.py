import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "team_up.py"
REPO = SCRIPT.parents[4]


V3_SCHEMA = """
CREATE TABLE repository (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    common_dir TEXT NOT NULL
);
CREATE TABLE runs (
    id INTEGER PRIMARY KEY,
    goal TEXT NOT NULL,
    slots INTEGER NOT NULL CHECK (slots > 0),
    base TEXT,
    cursor INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    worker TEXT NOT NULL CHECK (worker IN ('claude', 'codex')),
    goal TEXT NOT NULL,
    scope TEXT NOT NULL,
    evidence_requirement TEXT NOT NULL,
    completed_at TEXT,
    merged_base TEXT,
    merged_commit TEXT
);
CREATE INDEX tasks_run ON tasks(run_id);
CREATE TABLE dependencies (
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    prerequisite_id INTEGER NOT NULL REFERENCES tasks(id),
    condition TEXT NOT NULL CHECK (condition IN ('finish', 'merge')),
    PRIMARY KEY (task_id, prerequisite_id),
    CHECK (prerequisite_id < task_id)
);
CREATE TABLE gates (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    name TEXT NOT NULL,
    decision TEXT CHECK (decision IN ('approve', 'reject')),
    note TEXT,
    PRIMARY KEY (run_id, name)
);
CREATE TABLE task_gates (
    run_id INTEGER NOT NULL,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    name TEXT NOT NULL,
    PRIMARY KEY (task_id, name),
    FOREIGN KEY (run_id, name) REFERENCES gates(run_id, name)
);
CREATE TABLE dispatches (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    attempt INTEGER NOT NULL,
    retry_of INTEGER REFERENCES dispatches(id),
    phase TEXT NOT NULL CHECK (phase IN ('reserved', 'running', 'turn-ended', 'waiting', 'closed')),
    turn INTEGER NOT NULL DEFAULT 0,
    runtime TEXT,
    session TEXT,
    worktree TEXT,
    branch TEXT,
    review_main INTEGER NOT NULL DEFAULT 0,
    unresumable INTEGER NOT NULL DEFAULT 0,
    reserved_at TEXT NOT NULL,
    heartbeat_at TEXT,
    turn_ended_at TEXT,
    exited_at TEXT,
    exit_code INTEGER,
    outcome TEXT,
    stop_requested INTEGER NOT NULL DEFAULT 0,
    abandon_reason TEXT,
    evidence TEXT,
    keep_open INTEGER NOT NULL DEFAULT 0,
    taken_over INTEGER NOT NULL DEFAULT 0,
    delivered INTEGER NOT NULL DEFAULT 0,
    UNIQUE (task_id, attempt)
);
CREATE UNIQUE INDEX one_open_task ON dispatches(task_id) WHERE phase != 'closed';
CREATE UNIQUE INDEX one_open_worktree ON dispatches(worktree) WHERE phase != 'closed';
CREATE INDEX worktree_history ON dispatches(worktree);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    dispatch_id INTEGER NOT NULL REFERENCES dispatches(id),
    turn INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('question', 'instruction')),
    text TEXT NOT NULL,
    answer TEXT,
    consumed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX messages_dispatch ON messages(dispatch_id, turn);
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    task_id INTEGER REFERENCES tasks(id),
    dispatch_id INTEGER REFERENCES dispatches(id),
    kind TEXT NOT NULL,
    at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX events_run ON events(run_id, id);
"""


class TeamUpTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / "state with spaces.db"
        self.command = [sys.executable, "-B", str(SCRIPT), "--db", str(self.db)]
        self.cwd = REPO
        self.fake_gh = self.db.parent / "fake gh"

    def invoke(self, *args, expected=0, stderr=None, env=None):
        result = subprocess.run(
            [*self.command, *map(str, args)],
            cwd=self.cwd, env={**os.environ, **(env or {}), "TEAM_UP_GH": str(self.fake_gh)},
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, expected, result.stderr or result.stdout)
        if stderr is not None:
            self.assertEqual(result.stderr, stderr)
        if expected == 0:
            return json.loads(result.stdout)
        return result

    def run_create(self, slots=4, *options):
        self.invoke("init")
        return self.invoke("run-create", "--goal", "Run goal", "--slots", slots, *options)["id"]

    def create_legacy_db(self, version):
        repo_common_dir = subprocess.check_output(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=self.cwd, text=True,
        ).strip()
        with sqlite3.connect(self.db) as db:
            schema = V3_SCHEMA
            if version == 4:
                schema = schema.replace("('claude', 'codex')", "('claude', 'codex', 'agy')")
            db.executescript(schema)
            db.execute(f"PRAGMA user_version={version}")
            db.executescript("""
                PRAGMA foreign_keys=ON;
                INSERT INTO runs VALUES (7, 'Run goal', 2, 'main', 3);
                INSERT INTO tasks VALUES
                    (11, 7, 'claude', 'Review', 'src/', 'Show tests', 'finished', 'main', 'abc123'),
                    (19, 7, 'codex', 'Implement', 'tests/', 'Show patch', NULL, NULL, NULL);
                INSERT INTO dependencies VALUES (19, 11, 'merge');
                INSERT INTO gates VALUES (7, 'review', 'approve', 'Approved');
                INSERT INTO task_gates VALUES (7, 19, 'review');
                INSERT INTO dispatches (id, task_id, attempt, phase, turn, reserved_at)
                    VALUES (29, 19, 1, 'waiting', 2, 'reserved');
                INSERT INTO messages VALUES (31, 29, 2, 'question', 'Proceed?', 'Yes', 1);
                INSERT INTO events VALUES (37, 7, 19, 29, 'question', 'recorded', '{}');
            """)
            if version == 4:
                db.execute("UPDATE tasks SET worker = 'agy' WHERE id = 11")
            db.execute("INSERT INTO repository VALUES (1, ?)", (str(Path(repo_common_dir).resolve()),))

    def task(self, run, goal, *constraints, worker="codex"):
        return self.invoke(
            "task-create", run, "--worker", worker, "--goal", goal,
            "--scope", "src/", "--evidence", "Show the verification result", *constraints,
        )["id"]

    def make_legacy_agy(self, task):
        # Restore the historical worker identity after creating the lifecycle state.
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 5)
            db.execute("UPDATE tasks SET worker = 'agy' WHERE id = ?", (task,))

    def assert_legacy_execution_rejected(self, *args, error="worker 'agy' is not supported for new work"):
        with closing(sqlite3.connect(self.db)) as db:
            before = list(db.iterdump())
        result = self.invoke(*args, expected=1)
        self.assertIn(error, result.stderr)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(list(db.iterdump()), before)

    def begin(self, dispatch):
        return self.invoke("begin", dispatch)["turn"]

    def start(self, run, task, *worktree):
        dispatch = self.invoke("reserve", run, "--task", task, *worktree)["id"]
        turn = self.begin(dispatch)
        self.started(dispatch, turn)
        return dispatch, turn

    def started(self, dispatch, turn):
        self.invoke(
            "started", dispatch, "--turn", turn, "--runtime", f"job-{turn}",
            "--session", f"session-{dispatch}",
        )

    def report(self, dispatch, turn, expected=0, *, changed_code=True):
        evidence = {
            "status": "success", "result": "Full result\nSecond line",
            "verification": [
                {"command": "python3 -m unittest", "exit_code": 0, "location": "test.log"}
            ],
            "changed_code": changed_code,
        }
        if changed_code:
            evidence["diff"] = "artifacts/task.patch"
        return self.invoke(
            "done", dispatch, "--turn", turn, "--evidence", json.dumps(evidence),
            expected=expected,
        )

    def exit_worker(self, dispatch, turn, *flags, code=0):
        return self.invoke("exited", dispatch, "--turn", turn, "--code", code, *flags)

    def linked_worktree(self):
        checkout = self.db.parent / "checkout"
        worktree = self.db.parent / "linked worktree"
        subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(REPO), str(checkout)],
            check=True, capture_output=True, timeout=30,
        )
        subprocess.run(
            ["git", "-C", str(checkout), "worktree", "add", "--quiet", "-b", "assigned", str(worktree)],
            check=True, capture_output=True, timeout=30,
        )
        self.cwd = checkout
        return worktree

    def pr_fixture(self, **overrides):
        if not self.fake_gh.exists():
            self.fake_gh.write_text(
                "#!/usr/bin/python3\n"
                "import json, os, sys, time\n"
                "from pathlib import Path\n"
                "root = Path(__file__).parent\n"
                "args = sys.argv[1:]\n"
                "with (root / 'gh.log').open('a') as log:\n"
                "    print(json.dumps(args), file=log)\n"
                "if args[:2] == ['pr', 'view']:\n"
                "    failure = root / 'fail-view'\n"
                "    if failure.exists():\n"
                "        failure.unlink()\n"
                "        sys.exit('temporary GitHub failure')\n"
                "    time.sleep(float(os.environ.get('TEAM_UP_TEST_GH_SLEEP', '0')))\n"
                "    print((root / 'pr.json').read_text())\n"
                "elif args[:2] == ['pr', 'merge'] and '--disable-auto' in args:\n"
                "    if os.environ.get('TEAM_UP_TEST_GH_FAIL_DISABLE'):\n"
                "        sys.exit('temporary disarm failure')\n"
                "    fixture = root / 'pr.json'\n"
                "    data = json.loads(fixture.read_text())\n"
                "    data['autoMergeRequest'] = None\n"
                "    fixture.write_text(json.dumps(data))\n"
                "elif args[:2] != ['pr', 'merge'] and args[:2] != ['pr', 'update-branch']:\n"
                "    sys.exit('Unexpected gh command')\n",
                encoding="utf-8",
            )
            self.fake_gh.chmod(0o700)
        state = {
            "headRefOid": "a" * 40,
            "statusCheckRollup": [{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": ""}],
            "mergeable": "MERGEABLE", "mergeStateStatus": "BLOCKED",
            "autoMergeRequest": None, "state": "OPEN", "mergeCommit": None,
            "files": [{"path": "src/example.py"}], "changedFiles": 1, "baseRefName": "main",
            "url": "https://github.example/owner/repo/pull/42",
        }
        (self.db.parent / "pr.json").write_text(json.dumps({**state, **overrides}), encoding="utf-8")

    def gh_writes(self):
        log = self.db.parent / "gh.log"
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return [args for args in calls if args[:2] != ["pr", "view"]]

    def delivered_pr_dispatch(self, slots=2, *run_options):
        checkout = self.linked_worktree()
        run = self.run_create(slots, *run_options)
        task = self.task(run, "Follow the PR")
        dispatch, turn = self.start(run, task, "--worktree", checkout, "--branch", "assigned")
        self.report(dispatch, turn)
        self.exit_worker(dispatch, turn)
        self.invoke("delivered", dispatch)
        return run, task, dispatch

    def approve_pr(self, run, task):
        self.invoke("gate", run, "merge", "--decision", "approve")
        self.assertEqual(self.invoke("pr-policy", task, "auto", "--gate", "merge")["policy"], "auto")

    def test_slow_pr_sync_leaves_worker_writes_available(self):
        run, _, dispatch = self.delivered_pr_dispatch()
        self.pr_fixture()
        self.invoke("pr-open", dispatch, "--number", 42)
        worker, turn = self.start(run, self.task(run, "Keep working during sync"))
        log = self.db.parent / "gh.log"
        log.unlink()
        with ThreadPoolExecutor(max_workers=1) as pool:
            sync = pool.submit(self.invoke, "pr-sync", run, env={"TEAM_UP_TEST_GH_SLEEP": "6"})
            deadline = time.monotonic() + 5
            while not (log.exists() and log.stat().st_size) and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(log.exists() and log.stat().st_size, "fake gh did not start")
            self.assertEqual(self.invoke("heartbeat", worker, "--turn", turn)["turn"], turn)
            self.assertFalse(sync.done(), "heartbeat must complete while fake gh is sleeping")
            sync.result()

    def test_pr_open_tracks_hold_before_disarming_and_can_retry(self):
        run, _, dispatch = self.delivered_pr_dispatch()
        self.pr_fixture(autoMergeRequest={"enabledAt": "now"})
        self.invoke("pr-open", dispatch, "--number", 42, expected=1,
                    env={"TEAM_UP_TEST_GH_FAIL_DISABLE": "1"})
        pr = self.invoke("status", run)["pull_requests"][0]
        self.assertEqual((pr["policy"], pr["auto_merge"]), ("hold", 1))
        retried = self.invoke("pr-open", dispatch, "--number", 42)
        self.assertEqual((retried["id"], retried["auto_merge"]), (pr["id"], 0))

    def test_pr_approval_gate_is_dedicated_to_one_pr(self):
        run, task, dispatch = self.delivered_pr_dispatch()
        self.pr_fixture()
        self.invoke("pr-open", dispatch, "--number", 42)
        other = self.task(run, "Another PR", "--gate", "start-work")
        self.invoke("gate", run, "start-work", "--decision", "approve")
        self.invoke("pr-policy", task, "auto", "--gate", "start-work", expected=1)
        other_dispatch, turn = self.start(run, other)
        self.report(other_dispatch, turn)
        self.exit_worker(other_dispatch, turn)
        self.invoke("delivered", other_dispatch)
        self.invoke("pr-open", other_dispatch, "--number", 43)
        self.approve_pr(run, task)
        self.invoke("pr-policy", task, "hold")
        self.invoke("pr-policy", other, "auto", "--gate", "merge", expected=1)
        self.assertEqual(self.invoke("status", run)["pull_requests"][0]["approval_gate"], "merge")
        self.invoke("task-create", run, "--worker", "codex", "--goal", "Reuse PR gate",
                    "--scope", "src/", "--evidence", "Show tests", "--gate", "merge", expected=1)
        self.approve_pr(run, task)

    def test_wait_retries_a_failed_pr_sync(self):
        run, _, dispatch = self.delivered_pr_dispatch()
        self.pr_fixture(statusCheckRollup=[{"state": "FAILURE"}])
        self.invoke("pr-open", dispatch, "--number", 42)
        self.invoke("ack", run, self.invoke("wait", run, "--timeout", 0)["cursor"])
        failure = self.db.parent / "fail-view"
        failure.touch()
        rejected = self.invoke("pr-sync", run, expected=1)
        self.assertIn("temporary GitHub failure", rejected.stderr)
        failure.touch()
        watched = subprocess.run(
            [*self.command, "wait", str(run), "--timeout", "10", "--sync-prs", "1"],
            cwd=self.cwd, env={**os.environ, "TEAM_UP_GH": str(self.fake_gh)},
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(watched.returncode, 0, watched.stderr)
        self.assertIn("temporary GitHub failure", watched.stderr)
        self.assertEqual([event["kind"] for event in json.loads(watched.stdout)["events"]], ["pr-checks-failed"])

    def test_pr_arm_requires_auto_policy_and_healthy_checks(self):
        run, task, dispatch = self.delivered_pr_dispatch()
        self.pr_fixture()
        self.invoke("pr-open", dispatch, "--number", 42, "--policy", "auto", expected=1)
        pr = self.invoke("pr-open", dispatch, "--number", 42)
        self.assertEqual((pr["policy"], pr["auto_merge"]), ("hold", 0))
        self.invoke("pr-open", dispatch, "--number", 43, expected=1)
        self.invoke("pr-arm", task, expected=1)
        self.invoke("pr-policy", task, "manual")
        self.invoke("pr-arm", task, expected=1)
        self.invoke("pr-policy", task, "auto", "--gate", "merge", expected=1)
        self.assertEqual(self.gh_writes(), [])
        self.approve_pr(run, task)
        self.pr_fixture(statusCheckRollup=[{"state": "FAILURE"}])
        refused = self.invoke("pr-arm", task, expected=1)
        self.assertIn("failing checks", refused.stderr)
        self.assertEqual(self.gh_writes(), [])
        self.pr_fixture()
        self.assertEqual(self.invoke("pr-arm", task)["auto_merge"], 1)
        self.assertEqual(self.gh_writes(), [
            ["pr", "merge", "42", "--auto", "--squash", "--match-head-commit", "a" * 40],
        ])

    def test_pr_path_policy_downgrades_and_disables_an_armed_pr_on_new_head(self):
        run, task, dispatch = self.delivered_pr_dispatch()
        policy = self.cwd / ".github" / "merge-policy"
        policy.parent.mkdir(exist_ok=True)
        policy.write_text("# Approval paths\nprotected/**/*.py\nconfig/**/live/**/settings.yml\n", encoding="utf-8")
        self.pr_fixture(files=[{"path": "protected/direct.py"}])
        self.assertEqual(self.invoke("pr-open", dispatch, "--number", 42, "--policy", "manual")["policy"], "hold")
        self.invoke("gate", run, "merge", "--decision", "approve")
        self.invoke("pr-policy", task, "auto", "--gate", "merge", expected=1)
        self.pr_fixture()
        self.assertEqual(self.invoke("pr-sync", run)["pull_requests"][0]["policy"], "hold")
        self.approve_pr(run, task)
        self.invoke("pr-arm", task)
        self.pr_fixture(headRefOid="b" * 40, autoMergeRequest={"enabledAt": "now"},
                        files=[{"path": "config/live/subdir/settings.yml"}])
        pr = self.invoke("pr-sync", run)["pull_requests"][0]
        self.assertEqual((pr["policy"], pr["auto_merge"]), ("hold", 0))
        self.assertEqual(self.gh_writes()[-1], ["pr", "merge", "42", "--disable-auto"])
        self.pr_fixture(headRefOid="c" * 40)
        self.assertEqual(self.invoke("pr-sync", run)["pull_requests"][0]["policy"], "hold")
        result = self.invoke("wait", run, "--timeout", 0)
        self.assertEqual([event["kind"] for event in result["events"]].count("pr-policy-downgraded"), 1)
        self.approve_pr(run, task)
        self.pr_fixture(headRefOid="d" * 40, changedFiles=101)
        refused = self.invoke("pr-arm", task, expected=1)
        self.assertIn("merge-policy", refused.stderr)
        self.assertEqual(self.invoke("status", run)["pull_requests"][0]["policy"], "hold")
        self.assertEqual(sum("--auto" in call for call in self.gh_writes()), 1)

    def test_pr_sync_updates_only_auto_and_records_merge_for_dependents(self):
        run, task, dispatch = self.delivered_pr_dispatch(2, "--base", "origin/main")
        self.pr_fixture(mergeStateStatus="BEHIND")
        self.invoke("pr-open", dispatch, "--number", 42)
        self.invoke("pr-sync", run)
        self.assertEqual(self.gh_writes(), [])
        self.approve_pr(run, task)
        self.invoke("pr-sync", run)
        self.assertEqual(self.gh_writes(), [["pr", "update-branch", "42"]])
        dependent = self.task(run, "After the merge", "--after-merge", task)
        self.assertIsNone(self.invoke("reserve", run, "--task", dependent))
        sha = "d" * 40
        self.pr_fixture(state="MERGED", mergeCommit={"oid": sha})
        self.assertEqual(self.invoke("pr-sync", run)["pull_requests"][0]["merged_commit"], sha)
        self.assertEqual(self.invoke("pr-sync", run)["pull_requests"], [])
        current = self.invoke("status", run)["tasks"][0]
        self.assertEqual((current["merged_base"], current["merged_commit"]), ("origin/main", sha))
        self.assertEqual(self.invoke("reserve", run, "--task", dependent)["task_id"], dependent)
        events = self.invoke("wait", run, "--timeout", 0)["events"]
        self.assertEqual([event["kind"] for event in events].count("pr-merged"), 1)

    def test_pr_wait_and_fix_rounds_require_a_slot_and_stop_after_three(self):
        run, task, dispatch = self.delivered_pr_dispatch(1)
        self.pr_fixture(statusCheckRollup=[{"state": "SUCCESS"}])
        self.invoke("pr-open", dispatch, "--number", 42)
        self.invoke("ack", run, self.invoke("wait", run, "--timeout", 0)["cursor"])
        watched = self.invoke("wait", run, "--timeout", 0.1, "--sync-prs", 1)
        self.assertEqual([event["kind"] for event in watched["events"]], ["pr-checks-passed"])
        board = self.invoke("board", run, "--json")
        self.assertEqual(board["groups"][0]["tasks"][0]["fact"], "PR #42 승인 필요")
        self.invoke("ack", run, watched["cursor"])
        self.pr_fixture(statusCheckRollup=[{"status": "COMPLETED", "conclusion": "FAILURE"}],
                        mergeable="CONFLICTING", mergeStateStatus="DIRTY")
        watched = self.invoke("wait", run, "--timeout", 30, "--sync-prs", 1)
        self.assertEqual([event["kind"] for event in watched["events"]], ["pr-checks-failed", "pr-conflict"])
        self.invoke("ack", run, watched["cursor"])
        self.assertEqual(self.invoke("wait", run, "--timeout", 0, "--sync-prs", 1)["events"], [])
        other = self.task(run, "Occupy the only slot")
        occupied = self.invoke("reserve", run, "--task", other)["id"]
        self.invoke("instruct", dispatch, "Fix the PR")
        refused = self.invoke("begin", dispatch, expected=1)
        self.assertIn("no run slot", refused.stderr)
        self.assertEqual(self.invoke("status", run)["pull_requests"][0]["fix_rounds"], 0)
        self.invoke("abandon", occupied, "--reason", "Free the slot")
        for round_number in range(1, 4):
            turn = self.begin(dispatch)
            self.assertEqual(self.invoke("status", run)["pull_requests"][0]["fix_rounds"], round_number)
            self.started(dispatch, turn)
            self.report(dispatch, turn)
            self.exit_worker(dispatch, turn)
            self.invoke("delivered", dispatch)
            self.invoke("instruct", dispatch, "Fix the PR")
        refused = self.invoke("begin", dispatch, expected=1)
        self.assertIn("3 fix rounds", refused.stderr)
        board = self.invoke("board", run, "--json")
        self.assertEqual(board["groups"][0]["tasks"][0]["fact"], "수정 3회 · 확인 필요")
        self.assertEqual(self.gh_writes(), [])

    def test_pr_fix_waits_until_auto_merge_is_disarmed(self):
        run, task, dispatch = self.delivered_pr_dispatch()
        self.pr_fixture()
        self.invoke("pr-open", dispatch, "--number", 42)
        self.approve_pr(run, task)
        self.pr_fixture(statusCheckRollup=[{"state": "FAILURE"}], autoMergeRequest={"enabledAt": "now"})
        self.invoke("pr-sync", run)
        self.invoke("instruct", dispatch, "Fix checks")
        refused = self.invoke("begin", dispatch, expected=1)
        self.assertIn("disable auto-merge", refused.stderr)
        self.assertEqual(self.invoke("status", run)["pull_requests"][0]["fix_rounds"], 0)
        self.invoke("pr-policy", task, "hold")
        self.assertEqual(self.gh_writes(), [["pr", "merge", "42", "--disable-auto"]])
        self.assertEqual(self.begin(dispatch), 2)

    def test_only_init_creates_or_changes_journal(self):
        self.invoke("run-create", "--goal", "Run", "--slots", 1, expected=1)
        self.assertFalse(self.db.exists())
        self.assertEqual(self.invoke("init")["schema_version"], 5)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(db.execute("PRAGMA journal_mode=DELETE").fetchone()[0], "delete")

        env = {**os.environ, "TEAM_UP_DB": str(self.db)}
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "status", "1"],
            env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        self.invoke("init")
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_init_and_status_warn_on_affected_sqlite_versions(self):
        run = self.run_create()
        launcher = (
            "import runpy, sqlite3, sys; sqlite3.sqlite_version = sys.argv.pop(1); "
            "runpy.run_path(sys.argv.pop(1), run_name='__main__')"
        )
        for version, affected in (
            ("3.6.23", False), ("3.7.0", True),
            ("3.44.5", True), ("3.44.6", False), ("3.44.7", False),
            ("3.45.0", True), ("3.50.6", True), ("3.50.7", False), ("3.50.8", False),
            ("3.51.2", True), ("3.51.3", False),
        ):
            self.command = [sys.executable, "-B", "-c", launcher, version, str(SCRIPT), "--db", str(self.db)]
            for args in (("init",), ("status", run)):
                with self.subTest(version=version, command=args[0]):
                    result = self.invoke(*args)
                    warning = result.get("warning")
                    if affected:
                        self.assertIn(f"SQLite {version}", warning or "")
                        self.assertIn("WAL-reset", warning)
                    else:
                        self.assertIsNone(warning)

    def test_concurrent_writers_keep_every_task_and_event(self):
        run = self.run_create()
        workers = 5
        tasks_per_worker = 10
        barrier = threading.Barrier(workers)

        def create_tasks(worker):
            barrier.wait(timeout=10)
            return [
                self.task(run, f"Worker {worker} task {index}")
                for index in range(tasks_per_worker)
            ]

        with ThreadPoolExecutor(max_workers=workers) as pool:
            ids = {task for batch in pool.map(create_tasks, range(workers)) for task in batch}

        self.assertEqual(len(ids), workers * tasks_per_worker)
        status = self.invoke("status", run)
        self.assertEqual({task["id"] for task in status["tasks"]}, ids)
        with sqlite3.connect(self.db) as db:
            events = db.execute("SELECT kind, task_id FROM events WHERE run_id = ?", (run,)).fetchall()
        self.assertCountEqual(events, [("run-created", None), *(("task-created", task) for task in ids)])

    def test_concurrent_reservation_does_not_double_book_task(self):
        run = self.run_create()
        task = self.task(run, "One Task")
        contenders = 6
        barrier = threading.Barrier(contenders)

        def reserve(_):
            barrier.wait(timeout=10)
            return self.invoke("reserve", run, "--task", task)

        with ThreadPoolExecutor(max_workers=contenders) as pool:
            reservations = list(pool.map(reserve, range(contenders)))

        self.assertEqual(sum(reservation is not None for reservation in reservations), 1)
        self.assertEqual(len(self.invoke("status", run)["dispatches"]), 1)

    def test_concurrent_workers_publish_reports(self):
        count = 5
        run = self.run_create(slots=count)
        dispatches = [self.start(run, self.task(run, f"Task {index}")) for index in range(count)]
        barrier = threading.Barrier(count)

        def finish(pair):
            barrier.wait(timeout=10)
            self.report(*pair)
            self.exit_worker(*pair)

        with ThreadPoolExecutor(max_workers=count) as pool:
            list(pool.map(finish, dispatches))

        for dispatch, _ in dispatches:
            self.invoke("retry", dispatch, expected=1)
        self.assertIsNone(self.invoke("reserve", run))

    def test_reservation_respects_decision_dependencies_and_slot(self):
        run = self.run_create(slots=1)
        first = self.task(run, "First")
        second = self.task(run, "Second", "--after", first, "--gate", "Choose path")
        self.assertIsNone(self.invoke("reserve", run, "--task", second))
        dispatch, turn = self.start(run, first)
        self.invoke("gate", run, "Choose path", "--decision", "approve")
        self.assertIsNone(self.invoke("reserve", run, "--task", second))
        self.report(dispatch, turn)
        self.invoke("turn-ended", dispatch, "--turn", turn)
        self.assertIsNone(self.invoke("reserve", run, "--task", second))
        self.exit_worker(dispatch, turn)
        self.assertIsNotNone(self.invoke("reserve", run, "--task", second))

    def test_rejection_keeps_gate_blocked_until_explicit_approval(self):
        run = self.run_create()
        task = self.task(run, "Rollout", "--gate", "rollout")
        self.invoke("gate", run, "rollout", "--decision", "hold", expected=2)
        self.assertIsNone(self.invoke("reserve", run, "--task", task))
        rejected = self.invoke("gate", run, "rollout", "--decision", "reject", "--note", "Hold until Monday")
        self.assertEqual(rejected["decision"], "reject")
        self.assertEqual(self.invoke("status", run)["gates"][0]["note"], "Hold until Monday")
        self.assertIsNone(self.invoke("reserve", run, "--task", task))
        self.invoke("gate", run, "rollout", "--decision", "approve")
        self.assertEqual(self.invoke("reserve", run, "--task", task)["task_id"], task)
        self.invoke("gate", run, "rollout", "--decision", "reject", expected=1)

    def test_init_upgrades_v3_and_preserves_data_and_foreign_keys(self):
        self.assert_init_upgrades_legacy_db(3)

    def test_init_upgrades_v4_and_preserves_data_and_foreign_keys(self):
        self.assert_init_upgrades_legacy_db(4)

    def assert_init_upgrades_legacy_db(self, version):
        self.create_legacy_db(version)
        denied = self.invoke("status", 7, expected=1)
        self.assertIn("run init with --db pointing", denied.stderr)
        with sqlite3.connect(self.db) as db:
            original_rows = [line for line in db.iterdump() if line.startswith("INSERT INTO ")]
        upgraded_rows = []
        for line in original_rows:
            if line.startswith('INSERT INTO "runs"'):
                line = line[:-2] + ",0);"
            elif line.startswith('INSERT INTO "dispatches"'):
                line = line[:-2] + ",NULL,NULL,NULL,NULL,NULL);"
            upgraded_rows.append(line)

        self.assertEqual(self.invoke("init")["schema_version"], 5)
        status = self.invoke("status", 7)
        self.assertEqual(status["run"]["notes_version"], 0)
        self.assertEqual(status["notes"], [])
        self.assertEqual(status["pull_requests"], [])
        self.assertIsNone(status["dispatches"][0]["notes_version"])
        for field in ("progress_text", "progress_step", "progress_total", "progress_at"):
            self.assertIsNone(status["dispatches"][0][field])
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 5)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertIn("tasks_run", [row[1] for row in db.execute("PRAGMA index_list(tasks)")])
            self.assertEqual([line for line in db.iterdump() if line.startswith("INSERT INTO ")], upgraded_rows)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE tasks SET worker = 'unknown' WHERE id = 19")

        result = self.invoke(
            "task-create", 7, "--worker", "agy", "--goal", "Verify",
            "--scope", "src/", "--evidence", "Show the verification result",
            expected=2,
        )
        self.assertIn("invalid choice: 'agy'", result.stderr)
        self.assertEqual(self.invoke("init")["schema_version"], 5)
        with sqlite3.connect(self.db) as db:
            self.assertEqual([line for line in db.iterdump() if line.startswith("INSERT INTO ")], upgraded_rows)
        self.assertEqual(self.invoke("note", 7, "Use the existing checklist")["notes_version"], 1)

    def test_note_appends_to_its_run_and_status_lists_notes_in_order(self):
        run = self.run_create()
        other = self.run_create()
        self.invoke("note", run, "  ", expected=2)
        self.invoke("note", 999, "Unknown run", expected=1)
        first = self.invoke("note", run, "Use the system Python")
        self.invoke("note", other, "Separate run")
        second = self.invoke("note", run, "Keep notes short\nInclude commands")

        self.assertEqual((first.pop("notes_version"), second.pop("notes_version")), (1, 2))
        self.assertEqual(first["run_id"], run)
        self.assertTrue(first["created_at"])
        self.assertLess(first["id"], second["id"])
        status = self.invoke("status", run)
        self.assertEqual(status["run"]["notes_version"], 2)
        self.assertEqual(status["notes"], [first, second])
        self.assertEqual([note["text"] for note in status["notes"]],
                         ["Use the system Python", "Keep notes short\nInclude commands"])
        self.assertEqual(self.invoke("status", other)["run"]["notes_version"], 1)

    def test_begin_snapshots_notes_per_turn(self):
        worktree = self.linked_worktree()
        run = self.run_create()
        task = self.task(run, "Implement")
        dispatch = self.invoke("reserve", run, "--task", task,
                               "--worktree", worktree, "--branch", "assigned")["id"]
        self.invoke("note", run, "First decision")
        first = self.invoke("begin", dispatch)
        self.assertEqual((first["notes_version"], first["notes"]), (1, "First decision"))
        self.started(dispatch, first["turn"])
        question = self.invoke("record", dispatch, "--turn", first["turn"], "Which path?")["id"]
        self.invoke("answer", question, "Use path A")
        self.exit_worker(dispatch, first["turn"])
        self.invoke("note", run, "Newest decision")

        status = self.invoke("status", run)
        self.assertEqual(status["run"]["notes_version"], 2)
        self.assertEqual(status["dispatches"][0]["notes_version"], 1)
        second = self.invoke("begin", dispatch)
        self.assertEqual((second["notes_version"], second["notes"]),
                         (2, "Newest decision\n\nFirst decision"))
        with closing(sqlite3.connect(self.db)) as db:
            events = db.execute(
                "SELECT data FROM events WHERE dispatch_id = ? AND kind = 'turn-begun' ORDER BY id",
                (dispatch,),
            ).fetchall()
        self.assertEqual([json.loads(data) for (data,) in events],
                         [{"turn": 1, "notes_version": 1}, {"turn": 2, "notes_version": 2}])

    def test_begin_caps_note_text_in_utf8_bytes(self):
        run = self.run_create()
        task = self.task(run, "Use notes in the brief")
        dispatch = self.invoke("reserve", run, "--task", task)["id"]
        older = "Older note"
        newest = "🍋" * 1500
        self.invoke("note", run, older)
        self.invoke("note", run, newest)

        brief = self.invoke("begin", dispatch)
        marker = "\n[Run notes truncated]"
        self.assertEqual(brief["notes_version"], 2)
        self.assertEqual(brief["notes"], newest[:(4096 - len(marker)) // 4] + marker)
        self.assertLessEqual(len(brief["notes"].encode("utf-8")), 4096)
        self.assertEqual([note["text"] for note in self.invoke("status", run)["notes"]], [older, newest])

    def test_active_workers_run_while_legacy_agy_reservations_are_blocked(self):
        run = self.run_create(slots=1)
        legacy = self.task(run, "Old unassigned task")
        self.make_legacy_agy(legacy)
        active = [self.task(run, f"New {worker} task", worker=worker) for worker in ("claude", "codex")]

        self.assert_legacy_execution_rejected("reserve", run, "--task", legacy)
        for task in active:
            dispatch = self.invoke("reserve", run)
            self.assertEqual(dispatch["task_id"], task)
            turn = self.begin(dispatch["id"])
            self.started(dispatch["id"], turn)
            self.report(dispatch["id"], turn)
            self.exit_worker(dispatch["id"], turn)
        self.assertIsNone(self.invoke("reserve", run))
        self.assertEqual(self.invoke("status", run)["tasks"][0]["worker"], "agy")

    def test_legacy_agy_cannot_retry_even_with_override(self):
        run = self.run_create()
        task = self.task(run, "Old failed task")
        dispatch, turn = self.start(run, task)
        self.exit_worker(dispatch, turn, code=1)
        self.make_legacy_agy(task)

        self.assert_legacy_execution_rejected("retry", dispatch)
        self.assert_legacy_execution_rejected("retry", dispatch, "--override")

    def test_legacy_agy_cannot_begin_reserved_waiting_or_completed_turns(self):
        worktree = self.linked_worktree()
        directory = self.db.parent
        for phase in ("reserved", "waiting", "completed"):
            with self.subTest(phase=phase):
                self.db = directory / f"{phase}.db"
                self.command = [sys.executable, "-B", str(SCRIPT), "--db", str(self.db)]
                run = self.run_create(slots=1)
                task = self.task(run, f"Old {phase} task")
                spec = ("--worktree", worktree, "--branch", "assigned")
                if phase == "reserved":
                    dispatch = self.invoke(
                        "reserve", run, "--task", task,
                        "--worktree", directory / "uncreated worktree", "--branch", "missing",
                    )["id"]
                else:
                    dispatch, turn = self.start(run, task, *spec)
                    if phase == "waiting":
                        question = self.invoke("record", dispatch, "--turn", turn, "Which path?")
                        self.invoke("answer", question["id"], "Use path A")
                    else:
                        self.report(dispatch, turn)
                    self.exit_worker(dispatch, turn)
                    if phase == "completed":
                        self.invoke("delivered", dispatch)
                        self.invoke("instruct", dispatch, "Review one more file")
                self.make_legacy_agy(task)

                self.assert_legacy_execution_rejected("begin", dispatch)
                if phase == "completed":
                    self.assertEqual(self.invoke("cleanup", run), [])
                    instruction = self.invoke("status", run)["messages"][0]
                    self.assertEqual((instruction["kind"], instruction["consumed"]), ("instruction", 0))
                    replacement = self.task(run, instruction["text"])
                    self.invoke("abandon", dispatch, "--reason", f"Moved instruction to Task {replacement}")
                    self.assertEqual([item["id"] for item in self.invoke("cleanup", run)], [dispatch])

    def test_legacy_agy_cannot_register_a_begun_turn_without_runtime(self):
        worktree = self.linked_worktree()
        run = self.run_create()
        task = self.task(run, "Old task with an unregistered turn")
        dispatch = self.invoke("reserve", run, "--task", task)["id"]
        turn = self.begin(dispatch)
        self.make_legacy_agy(task)

        spec = ("--worktree", worktree, "--branch", "assigned")
        start = ("--runtime", "job", "--session", "session")
        for command, options in (("register", spec), ("started", start), ("started", start + spec)):
            with self.subTest(command=command, options=options):
                self.assert_legacy_execution_rejected(command, dispatch, "--turn", turn, *options)
        self.invoke("stop", dispatch)
        closed = self.exit_worker(dispatch, turn, "--stopped")
        self.assertEqual((closed["phase"], closed["outcome"]), ("closed", "stopped"))

    def test_legacy_agy_rejects_answers_and_instructions(self):
        run = self.run_create()
        task = self.task(run, "Old task with a pending question")
        dispatch, turn = self.start(run, task)
        question = self.invoke("record", dispatch, "--turn", turn, "Which path?")
        self.exit_worker(dispatch, turn)
        self.make_legacy_agy(task)

        error = "worker 'agy' is disabled and will not be resumed"
        for command, target, message in (
            ("answer", question["id"], "Use path A"),
            ("instruct", dispatch, "Review one more file"),
        ):
            with self.subTest(command=command):
                self.assert_legacy_execution_rejected(command, target, message, error=error)

    def test_legacy_agy_records_can_be_reported_stopped_and_cleaned_up(self):
        worktree = self.linked_worktree()
        run = self.run_create(slots=1)
        task = self.task(run, "Old running task with results")
        spec = ("--worktree", worktree, "--branch", "assigned")
        dispatch, turn = self.start(run, task, *spec)
        self.make_legacy_agy(task)
        self.assertEqual(self.invoke("status", run)["tasks"][0]["worker"], "agy")

        report = self.report(dispatch, turn)
        self.assertEqual(report["task"]["worker"], "agy")
        self.invoke("turn-ended", dispatch, "--turn", turn)
        self.exit_worker(dispatch, turn)
        self.assertEqual(self.invoke("cleanup", run), [])
        self.invoke("delivered", dispatch)
        self.assertEqual([item["id"] for item in self.invoke("cleanup", run)], [dispatch])

        for phase in ("running", "reserved", "waiting"):
            with self.subTest(phase=phase):
                run = self.run_create(slots=1)
                stopped_task = self.task(run, f"Old {phase} task to stop")
                if phase == "reserved":
                    stopped = self.invoke("reserve", run, "--task", stopped_task)["id"]
                else:
                    stopped, stopped_turn = self.start(run, stopped_task)
                    if phase == "waiting":
                        self.invoke("record", stopped, "--turn", stopped_turn, "Which path?")
                        self.assertEqual(self.exit_worker(stopped, stopped_turn)["phase"], "waiting")
                self.make_legacy_agy(stopped_task)
                next_task = self.task(run, "New task waiting for a slot")
                closed = self.invoke("stop", stopped)
                outcome = "stopped"
                if phase != "reserved":
                    self.assertEqual(closed["phase"], phase)
                    if phase == "running":
                        self.invoke("abandon", stopped, "--reason", "Worker no longer supported")
                        outcome = "abandoned"
                    self.assertIsNone(self.invoke("reserve", run, "--task", next_task))
                    closed = self.exit_worker(stopped, stopped_turn, "--stopped")
                self.assertEqual((closed["phase"], closed["outcome"]), ("closed", outcome))
                self.assertEqual(self.invoke("reserve", run)["task_id"], next_task)

    def test_non_init_on_v3_suggests_init_on_the_same_database(self):
        self.create_legacy_db(3)
        result = self.invoke("status", 7, expected=1)
        self.assertIn("schema version 3", result.stderr)
        self.assertIn("run init", result.stderr)
        self.assertIn(str(self.db), result.stderr)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)

    def test_init_rolls_back_v3_upgrade_when_foreign_key_check_fails(self):
        self.create_legacy_db(3)
        with sqlite3.connect(self.db) as db:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("UPDATE dispatches SET task_id = 99 WHERE id = 29")
        original = self.db.read_bytes()

        result = self.invoke("init", expected=1)
        self.assertIn("foreign key check failed", result.stderr)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
        self.assertEqual(self.db.read_bytes(), original)

    def test_init_refuses_v2_and_preserves_the_existing_database(self):
        self.invoke("init")
        with sqlite3.connect(self.db) as db:
            db.execute("PRAGMA user_version=2")
        result = self.invoke("init", expected=1)
        self.assertIn("schema version 2", result.stderr)
        self.assertIn("new --db path", result.stderr)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_done_accepts_utf8_evidence_file(self):
        run = self.run_create()
        dispatch, turn = self.start(run, self.task(run, "Finish the task"))
        evidence = {
            "status": "success", "result": "검증 완료", "changed_code": False,
            "verification": [
                {"command": "python3 -m unittest", "exit_code": 0, "location": "test.log"}
            ],
        }
        value = json.dumps(evidence, ensure_ascii=False)
        path = self.db.parent / "completion evidence.json"
        path.write_text(value, encoding="utf-8")

        reported = self.invoke("done", dispatch, "--turn", turn, "--evidence-file", path)
        self.assertEqual(reported["evidence"], evidence)
        with sqlite3.connect(self.db) as db:
            stored, = db.execute("SELECT evidence FROM dispatches WHERE id = ?", (dispatch,)).fetchone()
        self.assertEqual(json.loads(stored), evidence)
        inline = self.invoke("done", dispatch, "--turn", turn, "--evidence", value)
        self.assertEqual(inline["evidence"], reported["evidence"])

    def test_done_rejects_invalid_json_in_evidence_file(self):
        run = self.run_create()
        dispatch, turn = self.start(run, self.task(run, "Finish the task"))
        value = '{\r\n  "status": }'
        path = self.db.parent / "evidence.json"
        path.write_bytes(value.encode("utf-8"))

        inline = self.invoke("done", dispatch, "--turn", turn, "--evidence", value, expected=1)
        self.assertTrue(inline.stderr.startswith("team-up: invalid evidence JSON:"))
        self.invoke("done", dispatch, "--turn", turn, "--evidence-file", path,
                    expected=1, stderr=inline.stderr)

    def test_done_rejects_unreadable_evidence_file(self):
        run = self.run_create()
        dispatch, turn = self.start(run, self.task(run, "Finish the task"))
        missing = self.db.parent / "missing.json"
        invalid_utf8 = self.db.parent / "invalid-utf8.json"
        invalid_utf8.write_bytes(b"\xff")

        for path in (missing, self.db.parent, invalid_utf8):
            with self.subTest(path=path):
                result = self.invoke("done", dispatch, "--turn", turn, "--evidence-file", path, expected=1)
                self.assertTrue(result.stderr.startswith(f"team-up: could not read evidence file {str(path)!r}:"))
                self.assertNotIn("Traceback", result.stderr)

    def test_done_requires_exactly_one_evidence_option(self):
        result = self.invoke("done", 1, "--turn", 1, expected=2)
        self.assertIn("one of the arguments --evidence --evidence-file is required", result.stderr)
        result = self.invoke("done", 1, "--turn", 1, "--evidence", "{}",
                             "--evidence-file", "evidence.json", expected=2)
        self.assertIn("argument --evidence-file: not allowed with argument --evidence", result.stderr)

    def test_completion_follow_up_keeps_instructions_and_fences_reports(self):
        worktree = self.linked_worktree()
        run = self.run_create(slots=1)
        task = self.task(run, "Review")
        dispatch, turn = self.start(run, task, "--worktree", worktree, "--branch", "assigned")
        instruction = self.invoke("instruct", dispatch, "Check one more thing")
        question = self.invoke("record", dispatch, "--turn", turn, "Which file?")
        self.report(dispatch, turn)
        self.invoke("answer", question["id"], "README.md", expected=1)
        self.invoke("begin", dispatch, expected=1)
        self.exit_worker(dispatch, turn)
        follow_up = self.invoke("instruct", dispatch, "Quote the first heading")
        self.invoke("delivered", dispatch)
        self.assertEqual(self.invoke("cleanup", run), [])

        other, other_turn = self.start(run, self.task(run, "Other work"))
        self.invoke("begin", dispatch, expected=1)
        self.exit_worker(other, other_turn)
        brief = self.invoke("begin", dispatch)
        self.assertEqual((brief["id"], brief["turn"], brief["session"], brief["worktree"]),
                         (dispatch, turn + 1, f"session-{dispatch}", str(worktree.resolve())))
        self.assertEqual([m["id"] for m in brief["messages"] if m["kind"] == "instruction" and not m["consumed"]],
                         [instruction["id"], follow_up["id"]])
        self.assertIsNone(brief["evidence"])
        self.assertEqual(brief["delivered"], 0)
        self.invoke("answer", question["id"], "README.md", expected=1)
        self.report(dispatch, turn, expected=1)
        self.started(dispatch, turn + 1)
        self.report(dispatch, turn + 1)
        self.exit_worker(dispatch, turn + 1)
        self.invoke("begin", dispatch, expected=1)
        self.invoke("delivered", dispatch)
        self.assertEqual([item["id"] for item in self.invoke("cleanup", run)], [dispatch])

    def test_main_review_resumes_against_the_live_patch_and_cannot_be_cleaned_up(self):
        worktree = self.linked_worktree()
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=self.cwd, text=True, timeout=30,
        ).strip()
        checkout = self.cwd
        readme = checkout / "README.md"
        original = readme.read_bytes()
        readme.write_bytes(original + b"\nOnly in the main checkout\n")
        diff = ["git", "--no-pager", "diff", "--no-ext-diff", "--no-textconv", "HEAD", "--", "README.md"]
        patch = subprocess.check_output(diff, cwd=checkout, timeout=30)
        self.assertIn(b"+Only in the main checkout", patch)
        self.assertEqual(subprocess.check_output(diff, cwd=worktree, timeout=30), b"")

        run = self.run_create()
        task = self.task(run, "Review the live patch")
        spec = ("--worktree", checkout, "--branch", branch)
        self.invoke("reserve", run, "--task", task, *spec, expected=1)
        self.invoke("reserve", run, "--task", task, "--review-main", expected=1)
        self.invoke("reserve", run, "--task", task, "--review-main",
                    "--worktree", worktree, "--branch", "assigned", expected=1)
        dispatch, turn = self.start(run, task, "--review-main", *spec)
        self.assertEqual(self.invoke("register", dispatch, "--turn", turn, *spec)["worktree"], str(checkout.resolve()))
        question = self.invoke("record", dispatch, "--turn", turn, "Review the wording?")
        waiting = self.exit_worker(dispatch, turn)
        self.invoke("answer", question["id"], "Yes")
        brief = self.invoke("begin", dispatch)
        self.assertEqual((brief["turn"], brief["session"], brief["worktree"]),
                         (turn + 1, waiting["session"], str(checkout.resolve())))
        self.report(dispatch, turn + 1, expected=1)
        self.report(dispatch, turn + 1, changed_code=False)
        self.exit_worker(dispatch, turn + 1)
        self.invoke("delivered", dispatch)
        self.assertEqual(subprocess.check_output(diff, cwd=checkout, timeout=30), patch)
        readme.write_bytes(original)
        self.assertEqual(self.invoke("cleanup", run), [])

    def test_merge_dependency_requires_designated_base(self):
        self.linked_worktree()
        base = subprocess.check_output(
            ["git", "symbolic-ref", "HEAD"], cwd=self.cwd, text=True, timeout=30,
        ).strip()
        run = self.run_create(1, "--base", base)
        first = self.task(run, "Land prerequisite")
        second = self.task(run, "Needs merge", "--after-merge", first)
        dispatch, turn = self.start(run, first)
        self.report(dispatch, turn)
        self.exit_worker(dispatch, turn)
        self.assertIsNone(self.invoke("reserve", run, "--task", second))
        self.invoke("merged", first, "--base", "refs/heads/assigned", "--commit", "HEAD", expected=1)
        self.invoke("merged", first, "--base", base, "--commit", "HEAD")
        self.assertIsNotNone(self.invoke("reserve", run, "--task", second))

    def test_start_failure_breaker_and_retry_lineage(self):
        run = self.run_create()
        task = self.task(run, "Start fails")
        dispatch = self.invoke("reserve", run, "--task", task)["id"]
        for attempt in range(1, 4):
            turn = self.begin(dispatch)
            self.exit_worker(dispatch, turn, "--start-failed", code=1)
            if attempt < 3:
                retry = self.invoke("retry", dispatch)
                self.assertEqual(retry["retry_of"], dispatch)
                self.assertEqual(retry["attempt"], attempt + 1)
                dispatch = retry["id"]

        self.invoke("retry", dispatch, expected=1)
        self.assertIsNone(self.invoke("reserve", run, "--task", task))
        self.assertEqual(len(self.invoke("status", run)["dispatches"]), 3)

        replacement = self.invoke("retry", dispatch, "--override")
        self.assertEqual(replacement["retry_of"], dispatch)
        self.assertEqual(replacement["attempt"], 4)
        with sqlite3.connect(self.db) as db:
            overrides = db.execute("SELECT dispatch_id, data FROM events WHERE kind = 'retry-override'").fetchall()
        self.assertEqual(
            [(dispatch_id, json.loads(data)["retry_of"]) for dispatch_id, data in overrides],
            [(replacement["id"], dispatch)],
        )
        turn = self.begin(replacement["id"])
        self.exit_worker(replacement["id"], turn, "--start-failed", code=1)
        self.invoke("retry", replacement["id"], expected=1)

    def test_question_resume_fences_previous_turn_and_keeps_slot(self):
        worktree = self.linked_worktree()
        run = self.run_create(slots=1)
        first = self.task(run, "Ask a question")
        second = self.task(run, "Use another slot")
        dispatch, turn = self.start(run, first, "--worktree", worktree, "--branch", "assigned")
        question = self.invoke("record", dispatch, "--turn", turn, "Which path?")["id"]
        self.invoke("answer", question, "Use path A")
        self.exit_worker(dispatch, turn)
        self.assertIsNone(self.invoke("reserve", run, "--task", second))
        next_turn = self.begin(dispatch)
        self.assertEqual(next_turn, turn + 1)
        self.started(dispatch, next_turn)
        self.report(dispatch, turn, expected=1)
        self.report(dispatch, next_turn)
        self.report(dispatch, next_turn)
        self.exit_worker(dispatch, next_turn)
        self.assertIsNotNone(self.invoke("reserve", run, "--task", second))

    def test_missing_runtime_warns_without_discarding_turn_or_exit_reports(self):
        run = self.run_create(slots=1)
        task = self.task(run, "Finish without a recorded runtime handle")
        dispatch = self.invoke("reserve", run, "--task", task)["id"]
        turn = self.begin(dispatch)
        self.report(dispatch, turn)
        warning = f"team-up: warning: Dispatch {dispatch} turn {turn} has no runtime handle recorded with started\n"

        ended = self.invoke("turn-ended", dispatch, "--turn", turn, stderr=warning)
        self.assertEqual(ended["phase"], "turn-ended")
        closed = self.invoke("exited", dispatch, "--turn", turn, "--code", 0, stderr=warning)
        self.assertEqual(closed["phase"], "closed")
        self.assertEqual(closed["outcome"], "success")

        next_dispatch = self.invoke("reserve", run, "--task", self.task(run, "Fail to launch"))["id"]
        next_turn = self.begin(next_dispatch)
        failed = self.invoke("exited", next_dispatch, "--turn", next_turn, "--code", 1, "--start-failed", stderr="")
        self.assertEqual(failed["outcome"], "start-failed")

    def test_missing_session_can_be_recovered_after_a_question_turn_exits(self):
        worktree = self.linked_worktree()
        run = self.run_create()
        task = self.task(run, "Recover the session from the worker log")
        dispatch = self.invoke("reserve", run, "--task", task,
                               "--worktree", worktree, "--branch", "assigned")["id"]
        turn = self.begin(dispatch)
        start = ("started", dispatch, "--turn", turn, "--runtime", "job-1")
        self.invoke(*start)
        question = self.invoke("record", dispatch, "--turn", turn, "Which path?")["id"]
        self.invoke("answer", question, "Use path A")
        ended = self.exit_worker(dispatch, turn)

        recovered = self.invoke("started", dispatch, "--turn", turn, "--session", "logged-thread")
        self.assertEqual(recovered, {**ended, "session": "logged-thread"})
        self.assertEqual(self.invoke(*start, "--session", "logged-thread"), recovered)
        self.invoke(*start, "--session", "different-thread", expected=1)
        with sqlite3.connect(self.db) as db:
            events = db.execute("SELECT data FROM events WHERE kind = 'session-recovered'").fetchall()
        self.assertEqual([json.loads(data) for (data,) in events], [{"turn": turn, "session": "logged-thread"}])
        self.assertEqual(self.begin(dispatch), turn + 1)
        self.invoke(*start, "--session", "logged-thread", expected=1)

    def test_missing_session_can_be_recovered_after_turn_ended_report(self):
        run = self.run_create()
        task = self.task(run, "Recover a logged thread before recording exit")
        dispatch = self.invoke("reserve", run, "--task", task)["id"]
        turn = self.begin(dispatch)
        ended = self.invoke("turn-ended", dispatch, "--turn", turn)
        recover = ("started", dispatch, "--turn", turn, "--session", "logged-thread")
        self.invoke(*recover, "--unresumable", expected=1)
        self.assertEqual(self.invoke(*recover), {**ended, "session": "logged-thread"})
        self.exit_worker(dispatch, turn)
        self.invoke(*recover, expected=1)

    def test_worktree_checks_use_the_database_repository(self):
        worktree = self.linked_worktree()
        checkout = self.cwd
        self.cwd = worktree
        run = self.run_create()
        self.cwd = checkout
        self.invoke("init")
        first = self.task(run, "Reserve an existing worktree")
        second = self.task(run, "Register a host-created worktree")
        third = self.task(run, "Check a worktree in the start report")
        self.cwd = self.db.parent / "unrelated"
        self.cwd.mkdir()
        spec = ("--worktree", worktree, "--branch", "assigned")
        self.invoke("reserve", run, "--task", first,
                    "--worktree", worktree, "--branch", "wrong-branch", expected=1)
        dispatch = self.invoke("reserve", run, "--task", first, *spec)["id"]
        self.exit_worker(dispatch, self.begin(dispatch))

        dispatch = self.invoke("reserve", run, "--task", second)["id"]
        turn = self.begin(dispatch)
        self.assertEqual(self.invoke("register", dispatch, "--turn", turn, *spec)["worktree"], str(worktree.resolve()))
        self.exit_worker(dispatch, turn)

        dispatch = self.invoke("reserve", run, "--task", third)["id"]
        turn = self.begin(dispatch)
        self.invoke("started", dispatch, "--turn", turn, "--runtime", "job-1", *spec)
        self.report(dispatch, turn)
        self.exit_worker(dispatch, turn)
        self.invoke("delivered", dispatch)
        self.assertEqual([item["id"] for item in self.invoke("cleanup", run)], [dispatch])

        fourth = self.task(run, "Reserve a worktree before creating it")
        planned = self.db.parent / "planned worktree"
        dispatch = self.invoke("reserve", run, "--task", fourth,
                               "--worktree", planned, "--branch", "planned")["id"]
        self.invoke("begin", dispatch, expected=1)
        subprocess.run(
            ["git", "-C", str(checkout), "worktree", "add", "--quiet", "-b", "planned", str(planned)],
            check=True, capture_output=True, timeout=30,
        )
        self.assertEqual(self.begin(dispatch), 1)

    def test_same_turn_ask_returns_answer_and_timeout_leaves_question(self):
        run = self.run_create()
        dispatch, turn = self.start(run, self.task(run, "Wait for an answer"))
        cursor = self.invoke("wait", run, "--timeout", 0)["cursor"]
        self.invoke("ack", run, cursor)
        with subprocess.Popen(
            [*self.command, "ask", str(dispatch), "--turn", str(turn), "Keep going?", "--timeout", "10"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ) as asker:
            events = self.invoke("wait", run, "--timeout", 5)["events"]
            self.assertEqual([event["kind"] for event in events], ["question"])
            self.invoke("answer", events[0]["data"]["message_id"], "Yes")
            stdout, stderr = asker.communicate(timeout=10)
        self.assertEqual(asker.returncode, 0, stderr)
        self.assertEqual(json.loads(stdout)["answer"], "Yes")

        timed_out = self.invoke(
            "ask", dispatch, "--turn", turn, "Next step?", "--timeout", 0, expected=124,
        )
        question = json.loads(timed_out.stdout)
        self.assertIsNone(question["answer"])
        self.exit_worker(dispatch, turn)
        self.assertEqual(self.invoke("answer", question["id"], "Use plan B")["answer"], "Use plan B")

    def test_cleanup_preserves_dirty_undelivered_and_kept_worktrees(self):
        worktree = self.linked_worktree()
        run = self.run_create(slots=1)
        task = self.task(run, "Leave an artifact")
        dispatch, turn = self.start(run, task, "--worktree", worktree, "--branch", "assigned")
        self.report(dispatch, turn)
        self.assertEqual(self.invoke("cleanup", run), [])
        self.exit_worker(dispatch, turn)
        self.assertEqual(self.invoke("cleanup", run), [])
        self.invoke("delivered", dispatch)
        dirty_file = worktree / "untracked-result.txt"
        dirty_file.write_text("Keep my work")
        self.assertEqual(self.invoke("cleanup", run), [])
        dirty_file.unlink()
        self.assertEqual([item["id"] for item in self.invoke("cleanup", run)], [dispatch])
        self.invoke("keep-open", dispatch)
        self.assertEqual(self.invoke("cleanup", run), [])
        self.assertTrue(worktree.exists())

    def test_stop_and_abandon_hold_slot_until_confirmed_exit(self):
        run = self.run_create(slots=1)
        first = self.task(run, "Stop this worker")
        second = self.task(run, "Wait for a slot")
        dispatch, turn = self.start(run, first)
        self.invoke("record", dispatch, "--turn", turn, "Can I continue?")
        self.exit_worker(dispatch, turn)
        self.invoke("stop", dispatch)
        self.invoke("abandon", dispatch, "--reason", "User cancelled this assignment")
        self.assertIsNone(self.invoke("reserve", run, "--task", second))
        self.invoke("retry", dispatch, expected=1)
        self.exit_worker(dispatch, turn, "--stopped")
        self.invoke("retry", dispatch, expected=1)
        self.assertIsNotNone(self.invoke("reserve", run, "--task", second))

    def test_normal_exit_without_report_leaves_task_retryable(self):
        run = self.run_create()
        dispatch, turn = self.start(run, self.task(run, "No report"))
        self.invoke("turn-ended", dispatch, "--turn", turn)
        self.invoke("retry", dispatch, expected=1)
        self.exit_worker(dispatch, turn)
        self.report(dispatch, turn, expected=1)
        self.assertEqual(self.invoke("retry", dispatch)["retry_of"], dispatch)

    def test_wait_ignores_heartbeats_progress_and_coordinator_events_until_timeout(self):
        run = self.run_create()
        dispatch, turn = self.start(run, self.task(run, "Keep working"))
        self.invoke("heartbeat", dispatch, "--turn", turn)
        self.invoke("progress", dispatch, "--turn", turn, "Still working")
        self.invoke("instruct", dispatch, "Coordinator update")
        self.invoke("turn-ended", dispatch, "--turn", turn)
        self.exit_worker(dispatch, turn)
        timeout = 1
        started_at = time.monotonic()
        observed = self.invoke("wait", run, "--timeout", timeout)
        self.assertEqual([event["kind"] for event in observed["events"]], [])
        self.assertGreaterEqual(time.monotonic() - started_at, timeout)
        with sqlite3.connect(self.db) as db:
            last_event = db.execute("SELECT max(id) FROM events WHERE run_id = ?", (run,)).fetchone()[0]
        self.assertEqual(observed["cursor"], last_event)
        self.assertEqual(self.invoke("ack", run, observed["cursor"])["cursor"], last_event)

    def test_progress_reports_only_for_the_active_running_turn(self):
        worktree = self.linked_worktree()
        run = self.run_create()
        task = self.task(run, "Report progress")
        dispatch = self.invoke("reserve", run, "--task", task,
                               "--worktree", worktree, "--branch", "assigned")["id"]
        self.invoke("progress", dispatch, "--turn", 1, "Too soon", expected=1)
        turn = self.begin(dispatch)
        self.started(dispatch, turn)
        first = self.invoke("progress", dispatch, "--turn", turn, "Planning")
        self.assertEqual((first["progress_step"], first["progress_total"]), (None, None))
        self.invoke("progress", dispatch, "--turn", turn, "--step", "1/3", "Plan ready")
        report = self.invoke("progress", dispatch, "--turn", turn, "Checking sources")
        self.assertEqual((report["progress_step"], report["progress_total"]), (1, 3))
        self.assertEqual(report["progress_at"], report["heartbeat_at"])
        saved = self.invoke("status", run)["dispatches"][0]
        with sqlite3.connect(self.db) as db:
            event = json.loads(db.execute(
                "SELECT data FROM events WHERE kind = 'progress' AND dispatch_id = ? ORDER BY id DESC LIMIT 1",
                (dispatch,),
            ).fetchone()[0])
        self.assertEqual(event["turn"], turn)
        for field in ("progress_text", "progress_step", "progress_total", "progress_at", "heartbeat_at"):
            self.assertEqual(saved[field], report[field])
            self.assertEqual(event[field], report[field])
        question = self.invoke("record", dispatch, "--turn", turn, "Proceed?")
        self.invoke("turn-ended", dispatch, "--turn", turn)
        self.invoke("progress", dispatch, "--turn", turn, "Too late", expected=1)
        self.exit_worker(dispatch, turn)
        self.invoke("progress", dispatch, "--turn", turn, "Waiting", expected=1)
        self.invoke("answer", question["id"], "Yes")
        resumed = self.invoke("begin", dispatch)
        self.assertEqual(resumed["turn"], turn + 1)
        for field in ("progress_text", "progress_step", "progress_total", "progress_at"):
            self.assertIsNone(resumed[field])
        self.invoke("progress", dispatch, "--turn", turn, "Stale", expected=1)
        self.invoke("progress", dispatch, "--turn", turn + 1, "Resumed")

    def test_progress_validates_step_and_bounds_text(self):
        run = self.run_create()
        dispatch, turn = self.start(run, self.task(run, "Report a step"))
        for step in ("one/two", "1", "1/2/3", "0/2", "2/1", "1/0", "1/9223372036854775808"):
            with self.subTest(step=step):
                self.invoke("progress", dispatch, "--turn", turn, "--step=" + step, "Work", expected=2)
        text = "일" * 200
        report = self.invoke("progress", dispatch, "--turn", turn, "--step", "2/2", text)
        self.assertEqual(report["progress_text"], text)
        self.invoke("progress", dispatch, "--turn", turn, text + "일", expected=1)
        self.assertEqual(self.invoke("status", run)["dispatches"][0]["progress_text"], text)

    def test_wait_wakes_on_done_and_replays_until_acknowledged(self):
        run = self.run_create()
        dispatch, turn = self.start(run, self.task(run, "Finish the task"))
        with subprocess.Popen(
            [*self.command, "wait", str(run), "--timeout", "20"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ) as waiter:
            try:
                self.report(dispatch, turn)
                stdout, stderr = waiter.communicate(timeout=5)
            finally:
                if waiter.poll() is None:
                    waiter.kill()
        self.assertEqual(waiter.returncode, 0, stderr)
        observed = json.loads(stdout)
        self.assertEqual([event["kind"] for event in observed["events"]], ["done"])
        self.task(run, "Create a trailing event")
        replayed = self.invoke("wait", run, "--timeout", 0)
        self.assertEqual(replayed["events"], observed["events"])
        self.assertGreater(replayed["cursor"], observed["cursor"])
        self.invoke("ack", run, replayed["cursor"])
        self.assertEqual(self.invoke("wait", run, "--timeout", 0), {"events": [], "cursor": replayed["cursor"]})

    def build_board_run(self):
        run = self.run_create(20)
        ids = {}
        ids["ask"] = self.task(run, "Ask the user")
        dispatch, turn = self.start(run, ids["ask"])
        self.invoke("record", dispatch, "--turn", turn, "Permission denied: Bash git push")
        ids["gate"] = self.task(run, "Wait for design gate", "--gate", "design")
        ids["breaker"] = self.task(run, "Fails to start")
        dispatch = self.invoke("reserve", run, "--task", ids["breaker"])["id"]
        for attempt in range(3):
            self.exit_worker(dispatch, self.begin(dispatch), "--start-failed", code=1)
            if attempt < 2:
                dispatch = self.invoke("retry", dispatch)["id"]
        ids["running"] = self.task(run, "Keep working")
        self.start(run, ids["running"])
        ids["ready"] = self.task(run, "Ready to go")
        ids["review"] = self.task(run, "Needs review", worker="claude")
        dispatch, turn = self.start(run, ids["review"])
        self.report(dispatch, turn)
        self.exit_worker(dispatch, turn)
        ids["merging"] = self.task(run, "Delivered awaiting merge")
        dispatch, turn = self.start(run, ids["merging"])
        self.report(dispatch, turn)
        self.exit_worker(dispatch, turn)
        self.invoke("delivered", dispatch)
        ids["after_merge"] = self.task(run, "Needs the merge", "--after-merge", ids["merging"])
        ids["after"] = self.task(run, "Needs running task", "--after", ids["running"])
        ids["rejected"] = self.task(run, "Rejected gate", "--gate", "qa")
        self.invoke("gate", run, "qa", "--decision", "reject")
        ids["abandoned"] = self.task(run, "Given up")
        dispatch = self.invoke("reserve", run, "--task", ids["abandoned"])["id"]
        self.invoke("abandon", dispatch, "--reason", "Out of scope")
        ids["delivered"] = self.task(run, "Shipped")
        dispatch, turn = self.start(run, ids["delivered"])
        self.report(dispatch, turn)
        self.exit_worker(dispatch, turn)
        self.invoke("delivered", dispatch)
        return run, ids

    def test_board_groups_each_task_once_from_the_users_view(self):
        run, ids = self.build_board_run()
        with sqlite3.connect(self.db) as db:
            before = list(db.iterdump())
        board = self.invoke("board", run, "--json")
        with sqlite3.connect(self.db) as db:
            self.assertEqual(list(db.iterdump()), before)
        groups = {group["key"]: {task["task_id"]: task["fact"] for task in group["tasks"]}
                  for group in board["groups"]}
        self.assertEqual([group["key"] for group in board["groups"]],
                         ["needs_user", "in_progress", "review", "merging", "blocked", "done"])
        self.assertEqual(groups["needs_user"], {
            ids["ask"]: "Permission denied: Bash git push",
            ids["gate"]: "gate design",
            ids["breaker"]: "시작 실패 3회 · retry --override",
        })
        self.assertEqual(set(groups["in_progress"]), {ids["running"], ids["ready"]})
        self.assertEqual(groups["in_progress"][ids["ready"]], "대기열")
        self.assertRegex(groups["in_progress"][ids["running"]], r"^\d+(초|분)$")
        self.assertEqual(list(groups["review"]), [ids["review"]])
        self.assertEqual(groups["merging"], {ids["merging"]: f"→ #{ids['after_merge']}"})
        self.assertEqual(groups["blocked"], {
            ids["after_merge"]: f"← #{ids['merging']} 머지",
            ids["after"]: f"← #{ids['running']}",
            ids["rejected"]: "← gate qa",
        })
        self.assertEqual(groups["done"], {ids["abandoned"]: "abandoned", ids["delivered"]: "전달됨"})
        listed = [task for group in groups.values() for task in group]
        self.assertEqual(sorted(listed), sorted(ids.values()))

    def test_board_text_lists_nonempty_groups_with_counts(self):
        run = self.run_create()
        queued = self.task(run, "First line goal\nsecond line")
        result = subprocess.run([*self.command, "board", str(run)], cwd=self.cwd,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"진행 중 (1)\n  #{queued} codex First line goal  대기열\n")
        self.invoke("board", 99, expected=1)

    def test_board_shows_running_progress_and_worktree_diff_stats(self):
        worktree = self.linked_worktree()
        run = self.run_create()
        task = self.task(run, "Implement progress")
        dispatch, turn = self.start(run, task, "--worktree", worktree, "--branch", "assigned")
        report = self.invoke("progress", dispatch, "--turn", turn, "--step", "2/3", "Check\nresults")

        def card():
            return self.invoke("board", run, "--json")["groups"][1]["tasks"][0]

        self.assertEqual(card()["diff_stats"], {"files": 0, "added": 0, "deleted": 0})
        readme = worktree / "README.md"
        readme.write_bytes(readme.read_bytes().partition(b"\n")[2])
        subprocess.run(["git", "add", "README.md"], cwd=worktree, check=True, timeout=30)
        with readme.open("ab") as file:
            file.write(b"\nA new line of text.\n")
        (worktree / "new\tfile\r.txt").write_bytes(b"first\nsecond")
        (worktree / "binary.dat").write_bytes(b"one\0two\n")
        (worktree / "empty.txt").touch()
        running = card()
        self.assertEqual(running["dispatch_id"], dispatch)
        self.assertEqual((running["progress_step"], running["progress_total"]), (2, 3))
        self.assertEqual(running["progress_text"], "Check\nresults")
        self.assertEqual(running["last_update_at"], report["progress_at"])
        self.assertFalse(running["stalled"])
        self.assertEqual(running["diff_stats"], {"files": 4, "added": 4, "deleted": 1})
        result = subprocess.run([*self.command, "board", str(run)], cwd=self.cwd,
                                capture_output=True, text=True, timeout=30, check=True)
        self.assertIn(f"2/3 단계 · Check results · 4개 파일 +4 -1 · {report['progress_at']}", result.stdout)
        worktree.rename(worktree.with_name("moved worktree"))
        self.assertIsNone(card()["diff_stats"])
        worktree.mkdir()
        (worktree / ".git").write_text("gitdir: /missing/worktree\n", encoding="utf-8")
        self.assertIsNone(card()["diff_stats"])

    def test_board_marks_stalls_using_the_latest_worker_update(self):
        run = self.run_create()
        task = self.task(run, "Check a stalled worker")
        dispatch, turn = self.start(run, task)
        report = self.invoke("progress", dispatch, "--turn", turn, "Waiting for tests")
        old = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat(timespec="milliseconds")

        def set_times(heartbeat_at, progress_at):
            with closing(sqlite3.connect(self.db)) as db, db:
                db.execute("UPDATE dispatches SET heartbeat_at = ?, progress_at = ? WHERE id = ?",
                           (heartbeat_at, progress_at, dispatch))
            return self.invoke("board", run, "--json")["groups"][1]["tasks"][0]

        fresh = report["progress_at"]
        for heartbeat_at, progress_at in ((old, fresh), (fresh, old)):
            with self.subTest(heartbeat_at=heartbeat_at, progress_at=progress_at):
                running = set_times(heartbeat_at, progress_at)
                self.assertFalse(running["stalled"])
                self.assertEqual(running["last_update_at"], fresh)
        stalled = set_times(old, old)
        self.assertTrue(stalled["stalled"])
        self.assertEqual(stalled["last_update_at"], old)
        result = subprocess.run([*self.command, "board", str(run)], cwd=self.cwd,
                                capture_output=True, text=True, timeout=30, check=True)
        self.assertIn("⚠ 정체 · Waiting for tests", result.stdout)

    def test_wait_cursor_preserves_actionable_events_beyond_a_full_batch(self):
        run = self.run_create()
        with sqlite3.connect(self.db) as db:
            db.executemany(
                "INSERT INTO events(run_id, kind, at, data) VALUES (?, ?, '2026-11-21', '{}')",
                [(run, "heartbeat")] * 101 + [(run, "done")] * 101 + [(run, "heartbeat")],
            )
            last_event = db.execute("SELECT max(id) FROM events WHERE run_id = ?", (run,)).fetchone()[0]

        first = self.invoke("wait", run, "--timeout", 0)
        self.assertEqual([event["kind"] for event in first["events"]], ["done"] * 100)
        self.invoke("ack", run, first["cursor"])
        second = self.invoke("wait", run, "--timeout", 0)
        self.assertEqual([event["id"] for event in second["events"]], [last_event - 1])
        self.assertEqual(second["cursor"], last_event)


if __name__ == "__main__":
    unittest.main()
