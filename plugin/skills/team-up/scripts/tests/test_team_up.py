import json
import os
from concurrent.futures import ThreadPoolExecutor
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


class TeamUpTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / "state with spaces.db"
        self.command = [sys.executable, "-B", str(SCRIPT), "--db", str(self.db)]
        self.cwd = REPO

    def invoke(self, *args, expected=0, stderr=None):
        result = subprocess.run(
            [*self.command, *map(str, args)],
            cwd=self.cwd, capture_output=True, text=True, timeout=30,
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

    def task(self, run, goal, *constraints):
        return self.invoke(
            "task-create", run, "--worker", "codex", "--goal", goal,
            "--scope", "src/", "--evidence", "Show the verification result", *constraints,
        )["id"]

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

    def test_only_init_creates_or_changes_journal(self):
        self.invoke("run-create", "--goal", "Run", "--slots", 1, expected=1)
        self.assertFalse(self.db.exists())
        self.invoke("init")
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

    def test_init_refuses_v2_and_preserves_the_existing_database(self):
        self.invoke("init")
        with sqlite3.connect(self.db) as db:
            db.execute("PRAGMA user_version=2")
        result = self.invoke("init", expected=1)
        self.assertIn("schema version 2", result.stderr)
        self.assertIn("new --db path", result.stderr)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)

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

    def test_wait_ignores_heartbeats_and_coordinator_events_until_timeout(self):
        run = self.run_create()
        dispatch, turn = self.start(run, self.task(run, "Keep working"))
        self.invoke("heartbeat", dispatch, "--turn", turn)
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
