#!/usr/bin/env python3
"""Store and coordinate team-up state. The host owns worker processes and sessions."""

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time


SCHEMA_VERSION = 4
TASKS_SCHEMA = """CREATE TABLE {} (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    worker TEXT NOT NULL CHECK (worker IN ('claude', 'codex', 'agy')),
    goal TEXT NOT NULL,
    scope TEXT NOT NULL,
    evidence_requirement TEXT NOT NULL,
    completed_at TEXT,
    merged_base TEXT,
    merged_commit TEXT
)"""
SCHEMA = f"""
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
{TASKS_SCHEMA.format("tasks")};
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


class StateError(Exception):
    pass


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def git(*args, directory=None):
    result = subprocess.run(
        ["git", *args], cwd=directory, text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise StateError(result.stderr.strip() or f"git {args[0]} failed ({result.returncode})")
    return result.stdout.rstrip("\n")


def common_dir(directory=None):
    return Path(git("rev-parse", "--path-format=absolute", "--git-common-dir", directory=directory)).resolve()


def database_path(args, repo_common_dir=None):
    override = args.db or os.environ.get("TEAM_UP_DB")
    if override:
        return Path(override).expanduser().resolve()
    repo_id = hashlib.sha256(os.fsencode(repo_common_dir or common_dir())).hexdigest()[:16]
    return Path.home() / ".local/state/default-stack/team-up" / f"{repo_id}.db"


def wal_reset_warning():
    version = tuple(map(int, sqlite3.sqlite_version.split(".")))
    # https://www.sqlite.org/wal.html#the_wal_reset_bug
    fixed_backport = ((version[:2] == (3, 44) and version >= (3, 44, 6))
                      or (version[:2] == (3, 50) and version >= (3, 50, 7)))
    if (3, 7, 0) <= version <= (3, 51, 2) and not fixed_backport:
        return f"SQLite {sqlite3.sqlite_version} is affected by the WAL-reset bug. Use a Python build with the fix."
    return None


def repository_common_dir(db):
    row = db.execute("SELECT common_dir FROM repository WHERE id = 1").fetchone()
    if row is None:
        raise StateError("database is missing its repository identity")
    return row[0]


def migrate_v3(db, repo_common_dir):
    # https://www.sqlite.org/lang_altertable.html#making_other_kinds_of_table_schema_changes
    db.execute("PRAGMA foreign_keys=OFF")
    try:
        with transaction(db):
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (3, SCHEMA_VERSION):
                raise StateError(f"database schema version {version} does not match {SCHEMA_VERSION}; "
                                 "keep the existing DB and run init with a new --db path")
            if repository_common_dir(db) != str(repo_common_dir):
                raise StateError("database belongs to a different repository")
            if version == SCHEMA_VERSION:
                return
            schema_objects = db.execute(
                "SELECT sql FROM sqlite_master WHERE tbl_name='tasks' "
                "AND type IN ('index', 'trigger') AND sql IS NOT NULL"
            ).fetchall()
            db.execute(TASKS_SCHEMA.format("new_tasks"))
            db.execute("""
                INSERT INTO new_tasks
                SELECT id, run_id, worker, goal, scope, evidence_requirement,
                       completed_at, merged_base, merged_commit
                FROM tasks
            """)
            db.execute("DROP TABLE tasks")
            db.execute("ALTER TABLE new_tasks RENAME TO tasks")
            for row in schema_objects:
                db.execute(row["sql"])
            violation = db.execute("PRAGMA foreign_key_check").fetchone()
            if violation is not None:
                raise StateError(f"cannot upgrade schema version 3: foreign key check failed "
                                 f"for {violation['table']} row {violation['rowid']}")
            db.execute("PRAGMA user_version=4")
    finally:
        db.execute("PRAGMA foreign_keys=ON")


def connect(path, repo_common_dir=None):
    create = repo_common_dir is not None
    if create:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, mode=0o600)
        os.close(descriptor)
    elif not path.is_file():
        raise StateError(f"database does not exist: {path}; run init first")
    db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, isolation_level=None)
    try:
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA foreign_keys=ON")
        db.row_factory = sqlite3.Row
        with transaction(db, write=False):
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 0 and create:
                if db.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchone():
                    raise StateError("refusing to initialize an existing database with unknown objects")
            elif version == 3 and not create:
                raise StateError(f"database schema version 3 at {path}; run init with --db pointing "
                                 "to this file to upgrade")
            elif version not in (3, SCHEMA_VERSION):
                raise StateError(f"database schema version {version} does not match {SCHEMA_VERSION}; "
                                 "keep the existing DB and run init with a new --db path")
            elif create and repository_common_dir(db) != str(repo_common_dir):
                raise StateError("database belongs to a different repository")
        if version == 3:
            migrate_v3(db, repo_common_dir)
            return db
        if create:
            if db.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                if db.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                    raise StateError("could not enable SQLite WAL mode")
            with transaction(db):
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version == 0:
                    for statement in SCHEMA.split(";"):
                        if statement.strip():
                            db.execute(statement)
                    db.execute("INSERT INTO repository(id, common_dir) VALUES (1, ?)", (str(repo_common_dir),))
                    db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                    version = SCHEMA_VERSION
                elif version == SCHEMA_VERSION and repository_common_dir(db) != str(repo_common_dir):
                    raise StateError("database belongs to a different repository")
        if version != SCHEMA_VERSION:
            raise StateError(f"database schema version {version} does not match {SCHEMA_VERSION}")
    except BaseException:
        db.close()
        raise
    return db


@contextmanager
def transaction(db, write=True):
    db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def run_row(db, run_id):
    row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise StateError(f"unknown run {run_id}")
    return row


def task_row(db, task_id):
    row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise StateError(f"unknown task {task_id}")
    return row


def dispatch_row(db, dispatch_id):
    row = db.execute(
        """SELECT d.*, t.run_id FROM dispatches d JOIN tasks t ON t.id = d.task_id
        WHERE d.id = ?""", (dispatch_id,)
    ).fetchone()
    if row is None:
        raise StateError(f"unknown dispatch {dispatch_id}")
    return row


def decode(row, field):
    result = dict(row)
    if result[field] is not None:
        result[field] = json.loads(result[field])
    return result


def event(db, run_id, kind, data, task_id=None, dispatch_id=None):
    db.execute(
        "INSERT INTO events(run_id, task_id, dispatch_id, kind, at, data) VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, task_id, dispatch_id, kind, timestamp(), json.dumps(data, ensure_ascii=False)),
    )


def dispatch_event(db, dispatch, kind, **data):
    event(db, dispatch["run_id"], kind, {"turn": dispatch["turn"], **data},
          task_id=dispatch["task_id"], dispatch_id=dispatch["id"])


def brief(db, dispatch_id):
    dispatch = dispatch_row(db, dispatch_id)
    result = decode(dispatch, "evidence")
    result["task"] = dict(task_row(db, dispatch["task_id"]))
    result["messages"] = [dict(row) for row in db.execute(
        "SELECT * FROM messages WHERE dispatch_id = ? ORDER BY id", (dispatch_id,)
    )]
    return result


def create_run(db, args):
    run_id = db.execute("INSERT INTO runs(goal, slots, base) VALUES (?, ?, ?)",
                        (args.goal, args.slots, args.base)).lastrowid
    event(db, run_id, "run-created", {"goal": args.goal, "slots": args.slots, "base": args.base})
    return dict(run_row(db, run_id))


def create_task(db, args):
    run_row(db, args.run)
    dependencies = dict.fromkeys(args.after, "finish")
    dependencies.update(dict.fromkeys(args.after_merge, "merge"))
    for prerequisite in dependencies:
        if task_row(db, prerequisite)["run_id"] != args.run:
            raise StateError(f"prerequisite {prerequisite} belongs to another run")
    task_id = db.execute(
        "INSERT INTO tasks(run_id, worker, goal, scope, evidence_requirement) VALUES (?, ?, ?, ?, ?)",
        (args.run, args.worker, args.goal, args.scope, args.evidence),
    ).lastrowid
    db.executemany("INSERT INTO dependencies VALUES (?, ?, ?)",
                   ((task_id, prerequisite, condition) for prerequisite, condition in dependencies.items()))
    for name in dict.fromkeys(args.gate):
        db.execute("INSERT OR IGNORE INTO gates(run_id, name) VALUES (?, ?)", (args.run, name))
        db.execute("INSERT INTO task_gates VALUES (?, ?, ?)", (args.run, task_id, name))
    event(db, args.run, "task-created", {}, task_id=task_id)
    return dict(task_row(db, task_id))


def decide_gate(db, args):
    run_row(db, args.run)
    gate = db.execute("SELECT decision, note FROM gates WHERE run_id = ? AND name = ?",
                      (args.run, args.name)).fetchone()
    result = {"run_id": args.run, "name": args.name, "decision": args.decision, "note": args.note}
    if gate and gate["decision"] == "approve" and args.decision == "reject":
        raise StateError(f"gate {args.name!r} already approved dependent work")
    if gate and (gate["decision"], gate["note"]) == (args.decision, args.note):
        return result
    db.execute(
        """INSERT INTO gates(run_id, name, decision, note) VALUES (?, ?, ?, ?)
        ON CONFLICT(run_id, name) DO UPDATE SET decision = excluded.decision, note = excluded.note""",
        (args.run, args.name, args.decision, args.note),
    )
    event(db, args.run, "gate-decided", result)
    return result


def mark_merged(db, args):
    task = task_row(db, args.task)
    run = run_row(db, task["run_id"])
    base = run["base"] or args.base
    if base != args.base:
        raise StateError(f"expected the run's base ref {base!r}")
    sha = git("rev-parse", "--verify", "--end-of-options", f"{args.commit}^{{commit}}")
    base_sha = git("rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}")
    git("merge-base", "--is-ancestor", sha, base_sha)
    with transaction(db):
        task = task_row(db, args.task)
        if task["completed_at"] is None:
            raise StateError("the task needs a successful completion report before recording a merge")
        if task["merged_commit"] is not None:
            if task["merged_commit"] != sha or task["merged_base"] != base:
                raise StateError("the task already has a recorded merge")
            return dict(task)
        db.execute("UPDATE tasks SET merged_base = ?, merged_commit = ? WHERE id = ?", (base, sha, args.task))
        event(db, task["run_id"], "task-merged", {"base": base, "commit": sha}, task_id=args.task)
        return dict(task_row(db, args.task))


READY = """
    SELECT t.* FROM tasks t
    WHERE t.run_id = ? AND (? IS NULL OR t.id = ?)
      AND NOT EXISTS (SELECT 1 FROM dispatches d WHERE d.task_id = t.id)
      AND NOT EXISTS (
          SELECT 1 FROM dependencies dep JOIN tasks p ON p.id = dep.prerequisite_id
          WHERE dep.task_id = t.id AND (
              NOT EXISTS (SELECT 1 FROM dispatches d WHERE d.task_id = p.id AND d.outcome = 'success')
              OR (dep.condition = 'merge' AND p.merged_commit IS NULL)
          )
      )
      AND NOT EXISTS (
          SELECT 1 FROM task_gates tg JOIN gates g ON g.run_id = tg.run_id AND g.name = tg.name
          WHERE tg.task_id = t.id AND g.decision IS NOT 'approve'
      )
    ORDER BY t.id LIMIT 1
"""


def slot_available(db, run):
    occupied = db.execute(
        """SELECT count(*) FROM dispatches d JOIN tasks t ON t.id = d.task_id
        WHERE t.run_id = ? AND d.phase != 'closed'""", (run["id"],)
    ).fetchone()[0]
    return occupied < run["slots"]


def worktree_spec(args):
    if (args.worktree is None) != (args.branch is None):
        raise StateError("provide --worktree and --branch together")
    if args.worktree is None:
        return None, None
    return str(Path(args.worktree).expanduser().resolve()), args.branch


def worktrees(db, *, primary=False):
    records = git("--git-dir", repository_common_dir(db), "worktree", "list", "--porcelain", "-z").split("\0\0")
    worktrees = {}
    # Git lists the repository's primary worktree first.
    for record in records[:1] if primary else records[1:]:
        values = dict(line.split(" ", 1) for line in record.split("\0") if " " in line)
        if "worktree" in values:
            ref = values.get("branch", "")
            if ref.startswith("refs/heads/"):
                worktrees[str(Path(values["worktree"]).resolve())] = ref[len("refs/heads/"):]
    return worktrees


def check_worktree(db, path, branch, review_main=False):
    if not Path(path).is_dir() or worktrees(db, primary=review_main).get(path) != branch:
        placement = "the primary checkout" if review_main else "a linked worktree"
        raise StateError(f"expected {placement} at {path!r} on branch {branch!r}")


def check_worktree_claim(db, path, dispatch_id=None):
    conflict = db.execute(
        """SELECT d.id FROM dispatches d WHERE d.worktree = ? AND d.id IS NOT ?
        AND (d.phase != 'closed' OR d.keep_open OR d.taken_over OR (d.evidence IS NOT NULL AND NOT d.delivered)
             OR (d.evidence IS NOT NULL AND d.abandon_reason IS NULL AND EXISTS (
                 SELECT 1 FROM messages m WHERE m.dispatch_id = d.id AND m.kind = 'instruction' AND NOT m.consumed
             )))""",
        (path, dispatch_id),
    ).fetchone()
    if conflict:
        raise StateError(f"worktree is still held by dispatch {conflict['id']}")


def insert_dispatch(db, task, worktree, branch, attempt=1, retry_of=None, review_main=False):
    if review_main and worktree is None:
        raise StateError("--review-main requires --worktree and --branch")
    if worktree:
        if review_main or Path(worktree).exists():
            check_worktree(db, worktree, branch, review_main)
        check_worktree_claim(db, worktree)
    dispatch_id = db.execute(
        """INSERT INTO dispatches(task_id, attempt, retry_of, phase, worktree, branch, review_main, reserved_at)
        VALUES (?, ?, ?, 'reserved', ?, ?, ?, ?)""",
        (task["id"], attempt, retry_of, worktree, branch, review_main, timestamp()),
    ).lastrowid
    dispatch = dispatch_row(db, dispatch_id)
    dispatch_event(db, dispatch, "reserved", attempt=attempt, retry_of=retry_of,
                   worktree=worktree, branch=branch, review_main=review_main)
    return brief(db, dispatch_id)


def reserve(db, args):
    run = run_row(db, args.run)
    if args.task is not None and task_row(db, args.task)["run_id"] != args.run:
        raise StateError("the task belongs to another run")
    worktree, branch = worktree_spec(args)
    if not slot_available(db, run):
        return None
    task = db.execute(READY, (args.run, args.task, args.task)).fetchone()
    if task is None:
        return None
    return insert_dispatch(db, task, worktree, branch, review_main=args.review_main)


def retry(db, args):
    previous = dispatch_row(db, args.dispatch)
    if previous["phase"] != "closed" or previous["outcome"] not in ("start-failed", "failure", "incomplete", "stopped"):
        raise StateError("retry requires a confirmed failed or stopped dispatch")
    if previous["abandon_reason"] or previous["taken_over"]:
        raise StateError("an abandoned or taken-over dispatch cannot be retried")
    task = task_row(db, previous["task_id"])
    if db.execute("SELECT max(attempt) FROM dispatches WHERE task_id = ?", (task["id"],)).fetchone()[0] != previous["attempt"]:
        raise StateError("retry requires the most recent dispatch for the task")
    count = db.execute("SELECT count(*) FROM dispatches WHERE task_id = ? AND outcome = 'start-failed'",
                       (task["id"],)).fetchone()[0]
    if count >= 3 and not args.override:
        raise StateError("this task reached three failed starts. Use retry --override only on user instruction.")
    if not slot_available(db, run_row(db, task["run_id"])):
        raise StateError("no run slot is available")
    worktree, branch = worktree_spec(args)
    if previous["review_main"] and worktree is None:
        worktree, branch = previous["worktree"], previous["branch"]
    replacement = insert_dispatch(db, task, worktree, branch, attempt=previous["attempt"] + 1,
                                  retry_of=previous["id"], review_main=bool(previous["review_main"]))
    if args.override:
        dispatch_event(db, replacement, "retry-override", retry_of=previous["id"], start_failures=count)
    return replacement


def current_turn(db, args):
    dispatch = dispatch_row(db, args.dispatch)
    if dispatch["turn"] != args.turn:
        raise StateError(f"stale turn {args.turn}; current turn is {dispatch['turn']}")
    return dispatch


def check_mutable_worker(dispatch):
    if dispatch["phase"] != "running":
        raise StateError("worker reports require a running turn")
    if dispatch["abandon_reason"]:
        raise StateError("the dispatch has been abandoned")


def questions(db, dispatch):
    return db.execute(
        """SELECT * FROM messages WHERE dispatch_id = ? AND turn = ? AND kind = 'question'
        AND NOT consumed ORDER BY id""", (dispatch["id"], dispatch["turn"])
    ).fetchall()


def begin(db, args):
    snapshot = dispatch_row(db, args.dispatch)
    if snapshot["worktree"]:
        check_worktree(db, snapshot["worktree"], snapshot["branch"], snapshot["review_main"])
    with transaction(db):
        dispatch = dispatch_row(db, args.dispatch)
        if (dispatch["worktree"], dispatch["branch"]) != (snapshot["worktree"], snapshot["branch"]):
            raise StateError("the worktree changed before the turn could begin; check status")
        if dispatch["stop_requested"] or dispatch["taken_over"] or dispatch["abandon_reason"]:
            raise StateError("the dispatch is stopped, taken over, or abandoned")
        phase = dispatch["phase"]
        follow_up = phase == "closed" and dispatch["evidence"] is not None
        if phase == "waiting" or follow_up:
            if dispatch["unresumable"] or not dispatch["session"] or not dispatch["worktree"]:
                raise StateError("the saved host session and worktree cannot be resumed")
        if phase == "waiting":
            if any(question["answer"] is None for question in questions(db, dispatch)):
                raise StateError("answer all questions from the previous turn before resuming")
        elif follow_up:
            if not db.execute(
                "SELECT 1 FROM messages WHERE dispatch_id = ? AND kind = 'instruction' AND NOT consumed",
                (args.dispatch,),
            ).fetchone():
                raise StateError("record an instruction before beginning a completion follow-up")
            if db.execute("SELECT 1 FROM dispatches WHERE task_id = ? AND attempt > ?",
                          (dispatch["task_id"], dispatch["attempt"])).fetchone():
                raise StateError("a newer dispatch already exists for this task")
            if not slot_available(db, run_row(db, dispatch["run_id"])):
                raise StateError("no run slot is available for the follow-up")
            check_worktree_claim(db, dispatch["worktree"], args.dispatch)
            dispatch_event(db, dispatch, "completion-followed-up", evidence=json.loads(dispatch["evidence"]),
                           delivered=bool(dispatch["delivered"]))
            db.execute("UPDATE tasks SET completed_at = NULL WHERE id = ? AND merged_commit IS NULL",
                       (dispatch["task_id"],))
        elif phase != "reserved":
            raise StateError("begin requires a reservation or a confirmed exit before resuming")
        db.execute(
            """UPDATE dispatches SET phase = 'running', turn = turn + 1, runtime = NULL,
            heartbeat_at = ?, turn_ended_at = NULL, exited_at = NULL, exit_code = NULL,
            outcome = NULL, evidence = NULL, delivered = 0 WHERE id = ?""",
            (timestamp(), args.dispatch),
        )
        dispatch_event(db, dispatch_row(db, args.dispatch), "turn-begun")
        return brief(db, args.dispatch)


def save_worktree(db, dispatch, worktree, branch):
    if dispatch["phase"] not in ("running", "turn-ended"):
        raise StateError("worktree registration requires an active turn")
    if dispatch["worktree"] is not None:
        if (dispatch["worktree"], dispatch["branch"]) != (worktree, branch):
            raise StateError("the dispatch already has a different worktree or branch")
        return
    check_worktree_claim(db, worktree, dispatch["id"])
    db.execute("UPDATE dispatches SET worktree = ?, branch = ? WHERE id = ?", (worktree, branch, dispatch["id"]))
    dispatch_event(db, dispatch, "worktree-registered", worktree=worktree, branch=branch)


def register(db, args):
    worktree, branch = worktree_spec(args)
    check_worktree(db, worktree, branch, dispatch_row(db, args.dispatch)["review_main"])
    with transaction(db):
        save_worktree(db, current_turn(db, args), worktree, branch)
        return brief(db, args.dispatch)


def started(db, args):
    worktree, branch = worktree_spec(args)
    if worktree:
        check_worktree(db, worktree, branch, dispatch_row(db, args.dispatch)["review_main"])
    with transaction(db):
        dispatch = current_turn(db, args)
        phase = dispatch["phase"]
        recovering = phase == "waiting" or (phase == "closed" and dispatch["evidence"])
        if phase not in ("running", "turn-ended") and not recovering:
            raise StateError("start confirmation requires an active, waiting, or completed turn")
        if phase == "running" and args.runtime is None:
            raise StateError("start confirmation for a running turn requires --runtime")
        if args.runtime is not None and (recovering or dispatch["runtime"]):
            if dispatch["runtime"] != args.runtime:
                raise StateError("the supplied runtime must match the recorded runtime identity")
        if dispatch["session"] and args.session and dispatch["session"] != args.session:
            raise StateError("the dispatch already has a different session identity")
        if recovering or args.runtime is None:
            if args.session is None or worktree or args.unresumable:
                raise StateError("session recovery requires --session without worktree or unresumable options")
            if dispatch["session"] is None:
                db.execute("UPDATE dispatches SET session = ? WHERE id = ?", (args.session, args.dispatch))
                dispatch_event(db, dispatch, "session-recovered", session=args.session)
            return brief(db, args.dispatch)
        if worktree:
            save_worktree(db, dispatch, worktree, branch)
        session = args.session or dispatch["session"]
        unresumable = int(args.unresumable or dispatch["unresumable"])
        if (dispatch["runtime"], dispatch["session"], dispatch["unresumable"]) != (args.runtime, session, unresumable):
            db.execute("UPDATE dispatches SET runtime = ?, session = ?, unresumable = ? WHERE id = ?",
                       (args.runtime, session, unresumable, args.dispatch))
            dispatch_event(db, dispatch, "started", runtime=args.runtime, session=session, unresumable=bool(unresumable))
        return brief(db, args.dispatch)


def turn_ended(db, args):
    dispatch = current_turn(db, args)
    if dispatch["turn_ended_at"]:
        return brief(db, args.dispatch)
    if dispatch["phase"] != "running":
        raise StateError("turn-ended requires a running turn")
    db.execute("UPDATE dispatches SET phase = 'turn-ended', turn_ended_at = ? WHERE id = ?",
               (timestamp(), args.dispatch))
    dispatch_event(db, dispatch, "turn-ended")
    return brief(db, args.dispatch)


def outcome_after_exit(dispatch):
    if dispatch["abandon_reason"]:
        return "abandoned"
    if dispatch["evidence"]:
        return json.loads(dispatch["evidence"])["status"]
    if dispatch["taken_over"]:
        return "taken-over"
    if dispatch["stop_requested"]:
        return "stopped"
    return "incomplete"


def exited(db, args):
    dispatch = current_turn(db, args)
    if dispatch["phase"] == "closed":
        if dispatch["exit_code"] == args.code:
            return brief(db, args.dispatch)
        raise StateError("the dispatch already has a recorded exit")
    if args.stopped and not (dispatch["stop_requested"] or dispatch["taken_over"]):
        raise StateError("--stopped requires a recorded stop request, abandonment, or takeover")
    if dispatch["phase"] == "waiting":
        if not args.stopped:
            if dispatch["exit_code"] == args.code:
                return brief(db, args.dispatch)
            raise StateError("the turn already has a recorded exit; use --stopped after confirming shutdown")
    elif dispatch["phase"] not in ("running", "turn-ended"):
        raise StateError("exited requires a begun turn")
    if args.start_failed:
        if (dispatch["turn"] != 1 or dispatch["session"] or dispatch["evidence"]
                or dispatch["stop_requested"] or dispatch["taken_over"] or questions(db, dispatch)):
            raise StateError("--start-failed requires a first turn that did not start a usable session")
        outcome = "start-failed"
    else:
        outcome = outcome_after_exit(dispatch)
    phase = "closed"
    if outcome == "incomplete" and args.code == 0 and questions(db, dispatch):
        phase, outcome = "waiting", None
    db.execute("UPDATE dispatches SET phase = ?, outcome = ?, exited_at = ?, exit_code = ? WHERE id = ?",
               (phase, outcome, timestamp(), args.code, args.dispatch))
    dispatch_event(db, dispatch, "exited", code=args.code, stopped=args.stopped, phase=phase, outcome=outcome)
    return brief(db, args.dispatch)


def request_stop(db, args):
    dispatch = dispatch_row(db, args.dispatch)
    reason = getattr(args, "reason", None)
    if reason is None and dispatch["taken_over"]:
        raise StateError("the user has taken over this worker")
    if dispatch["abandon_reason"] and reason != dispatch["abandon_reason"] and reason is not None:
        raise StateError("this dispatch already has a different abandonment reason")
    if dispatch["phase"] == "closed":
        if reason is not None and dispatch["abandon_reason"] is None:
            db.execute("UPDATE dispatches SET abandon_reason = ? WHERE id = ?", (reason, args.dispatch))
            dispatch_event(db, dispatch, "abandoned", reason=reason, closed=True)
        return brief(db, args.dispatch)
    if dispatch["stop_requested"] and (reason is None or dispatch["abandon_reason"]):
        return brief(db, args.dispatch)
    never_begun = dispatch["phase"] == "reserved"
    db.execute(
        """UPDATE dispatches SET stop_requested = 1, abandon_reason = ?, phase = ?, outcome = ? WHERE id = ?""",
        (reason, "closed" if never_begun else dispatch["phase"],
         ("abandoned" if reason else "stopped") if never_begun else None, args.dispatch),
    )
    dispatch_event(db, dispatch, "abandoned" if reason else "stop-requested", reason=reason, closed=never_begun)
    return brief(db, args.dispatch)


def heartbeat(db, args):
    dispatch = current_turn(db, args)
    if dispatch["phase"] not in ("running", "turn-ended"):
        raise StateError("heartbeat requires an active turn")
    now = timestamp()
    db.execute("UPDATE dispatches SET heartbeat_at = ? WHERE id = ?", (now, args.dispatch))
    dispatch_event(db, dispatch, "heartbeat", heartbeat_at=now)
    return {"dispatch_id": args.dispatch, "turn": args.turn, "heartbeat_at": now}


def record_question(db, args):
    dispatch = current_turn(db, args)
    check_mutable_worker(dispatch)
    if dispatch["evidence"] or dispatch["stop_requested"]:
        raise StateError("the dispatch is completing or stopping")
    message_id = db.execute(
        "INSERT INTO messages(dispatch_id, turn, kind, text) VALUES (?, ?, 'question', ?)",
        (args.dispatch, args.turn, args.question),
    ).lastrowid
    dispatch_event(db, dispatch, "question", message_id=message_id, text=args.question)
    return {"id": message_id, "dispatch_id": args.dispatch, "turn": args.turn, "text": args.question}


def answer_question(db, args):
    message = db.execute("SELECT * FROM messages WHERE id = ? AND kind = 'question'", (args.question_id,)).fetchone()
    if message is None:
        raise StateError(f"unknown question {args.question_id}")
    if message["answer"] is not None:
        if message["answer"] != args.answer:
            raise StateError("the question already has a different answer")
        return dict(message)
    dispatch = dispatch_row(db, message["dispatch_id"])
    if (dispatch["phase"] == "closed" or dispatch["stop_requested"] or dispatch["evidence"]
            or message["turn"] != dispatch["turn"]):
        raise StateError("the dispatch no longer accepts answers")
    db.execute("UPDATE messages SET answer = ? WHERE id = ?", (args.answer, args.question_id))
    dispatch_event(db, dispatch, "answer", message_id=args.question_id, answer=args.answer)
    return {**dict(message), "answer": args.answer}


def ask(db, args):
    with transaction(db):
        question = record_question(db, args)
    deadline = time.monotonic() + args.timeout
    while True:
        answer = db.execute("SELECT answer FROM messages WHERE id = ?", (question["id"],)).fetchone()[0]
        if answer is not None:
            with transaction(db):
                dispatch = current_turn(db, args)
                check_mutable_worker(dispatch)
                db.execute("UPDATE messages SET consumed = 1 WHERE id = ?", (question["id"],))
                dispatch_event(db, dispatch, "answer-consumed", message_id=question["id"])
                return {**question, "answer": answer}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {**question, "answer": None}
        time.sleep(min(0.1, remaining))


def instruct(db, args):
    dispatch = dispatch_row(db, args.dispatch)
    if (dispatch["stop_requested"] or dispatch["taken_over"] or dispatch["abandon_reason"]
            or (dispatch["phase"] == "closed" and not dispatch["evidence"])):
        raise StateError("the dispatch no longer accepts instructions")
    message_id = db.execute(
        "INSERT INTO messages(dispatch_id, turn, kind, text) VALUES (?, ?, 'instruction', ?)",
        (args.dispatch, dispatch["turn"], args.text),
    ).lastrowid
    dispatch_event(db, dispatch, "instruction", message_id=message_id, text=args.text)
    return {"id": message_id, "dispatch_id": args.dispatch, "turn": dispatch["turn"], "text": args.text}


def has_text(value):
    return isinstance(value, str) and bool(value.strip())


def completion_evidence(value):
    try:
        evidence = json.loads(value, parse_constant=lambda constant: None)
    except ValueError as exc:
        raise StateError(f"invalid evidence JSON: {exc}") from exc
    if not isinstance(evidence, dict) or evidence.get("status") not in ("success", "failure"):
        raise StateError("evidence needs status 'success' or 'failure'")
    if not has_text(evidence.get("result")) or type(evidence.get("changed_code")) is not bool:
        raise StateError("evidence needs nonempty result text and a changed_code boolean")
    verification = evidence.get("verification")
    if not isinstance(verification, list) or not verification:
        raise StateError("evidence needs at least one verification entry")
    for check in verification:
        if (not isinstance(check, dict) or not has_text(check.get("command"))
                or type(check.get("exit_code")) is not int or not has_text(check.get("location"))):
            raise StateError("each verification entry needs command, integer exit_code, and location")
    if evidence["changed_code"] and not any(has_text(evidence.get(field)) for field in ("commit", "diff")):
        raise StateError("evidence for changed code needs a commit or diff")
    return evidence


def done(db, args):
    dispatch = current_turn(db, args)
    evidence = completion_evidence(args.evidence)
    if dispatch["review_main"] and evidence["changed_code"]:
        raise StateError("a main checkout review requires changed_code: false")
    if dispatch["evidence"] is not None:
        if json.loads(dispatch["evidence"]) == evidence:
            return brief(db, args.dispatch)
        raise StateError("the dispatch already has a different completion report")
    check_mutable_worker(dispatch)
    db.execute("UPDATE dispatches SET evidence = ? WHERE id = ?", (json.dumps(evidence, ensure_ascii=False), args.dispatch))
    db.execute("UPDATE messages SET consumed = 1 WHERE dispatch_id = ? AND kind = 'instruction' AND turn < ?",
               (args.dispatch, args.turn))
    if evidence["status"] == "success":
        db.execute("UPDATE tasks SET completed_at = ? WHERE id = ?", (timestamp(), dispatch["task_id"]))
    dispatch_event(db, dispatch, "done", status=evidence["status"])
    return brief(db, args.dispatch)


def wait(db, args):
    deadline = time.monotonic() + args.timeout
    cursor = 0
    while True:
        with transaction(db, write=False):
            cursor = max(cursor, run_row(db, args.run)["cursor"])
            events = [decode(row, "data") for row in db.execute(
                """SELECT * FROM events WHERE run_id = ? AND id > ?
                AND kind IN ('question', 'done') ORDER BY id LIMIT 101""",
                (args.run, cursor),
            )]
            if len(events) > 100:
                return {"events": events[:100], "cursor": events[99]["id"]}
            cursor = db.execute(
                "SELECT coalesce(max(id), ?) FROM events WHERE run_id = ? AND id > ?",
                (cursor, args.run, cursor),
            ).fetchone()[0]
        remaining = deadline - time.monotonic()
        if events or remaining <= 0:
            return {"events": events, "cursor": cursor}
        time.sleep(min(0.1, remaining))


def ack(db, args):
    cursor = run_row(db, args.run)["cursor"]
    if args.event and not db.execute("SELECT 1 FROM events WHERE run_id = ? AND id = ?", (args.run, args.event)).fetchone():
        raise StateError(f"event {args.event} does not belong to run {args.run}")
    if args.event > cursor:
        db.execute("UPDATE runs SET cursor = ? WHERE id = ?", (args.event, args.run))
    return {"run_id": args.run, "cursor": max(cursor, args.event)}


def status(db, args):
    with transaction(db, write=False):
        run = dict(run_row(db, args.run))
        tasks = [dict(row) for row in db.execute("SELECT * FROM tasks WHERE run_id = ? ORDER BY id", (args.run,))]
        gates = [dict(row) for row in db.execute("SELECT * FROM gates WHERE run_id = ? ORDER BY name", (args.run,))]
        result = {"run": run, "tasks": tasks, "gates": gates}
        order_by = {
            "dispatches": "r.id",
            "dependencies": "r.task_id, r.prerequisite_id",
            "task_gates": "r.task_id, r.name",
        }
        for table, order in order_by.items():
            rows = db.execute(
                f"SELECT r.* FROM {table} r JOIN tasks t ON t.id = r.task_id WHERE t.run_id = ? ORDER BY {order}",
                (args.run,),
            )
            result[table] = [decode(row, "evidence") if table == "dispatches" else dict(row) for row in rows]
        result["messages"] = [dict(row) for row in db.execute(
            """SELECT m.* FROM messages m JOIN dispatches d ON d.id = m.dispatch_id
            JOIN tasks t ON t.id = d.task_id WHERE t.run_id = ? ORDER BY m.id""", (args.run,)
        )]
        return result


def flag_dispatch(db, args):
    dispatch = dispatch_row(db, args.dispatch)
    field = {"keep-open": "keep_open", "takeover": "taken_over", "delivered": "delivered"}[args.command]
    if field == "delivered" and not dispatch["evidence"]:
        raise StateError("delivery requires a recorded completion report")
    if dispatch[field]:
        return brief(db, args.dispatch)
    db.execute(f"UPDATE dispatches SET {field} = 1 WHERE id = ?", (args.dispatch,))
    if field == "taken_over" and dispatch["phase"] == "reserved":
        db.execute("UPDATE dispatches SET phase = 'closed', outcome = 'taken-over' WHERE id = ?", (args.dispatch,))
    dispatch_event(db, dispatch, args.command)
    return brief(db, args.dispatch)


def cleanup(db, args):
    # A clean worktree without a report can still contain undelivered commits.
    run_row(db, args.run)
    rows = db.execute(
        """SELECT d.id, d.worktree, d.branch FROM dispatches d JOIN tasks t ON t.id = d.task_id
        WHERE t.run_id = ? AND d.worktree IS NOT NULL AND d.phase = 'closed'
        AND NOT d.review_main AND NOT d.keep_open AND NOT d.taken_over AND d.delivered
        AND (d.abandon_reason IS NOT NULL OR NOT EXISTS (
            SELECT 1 FROM messages m WHERE m.dispatch_id = d.id AND m.kind = 'instruction' AND NOT m.consumed
        ))
        AND NOT EXISTS (
            SELECT 1 FROM dispatches other WHERE other.worktree = d.worktree
            AND (other.id > d.id OR other.phase != 'closed' OR other.keep_open OR other.taken_over
                OR (other.evidence IS NOT NULL AND NOT other.delivered))
        ) ORDER BY d.id""", (args.run,)
    ).fetchall()
    if not rows:
        return []
    linked = worktrees(db)
    candidates = []
    for row in rows:
        path = row["worktree"]
        if linked.get(path) != row["branch"] or not Path(path).is_dir():
            continue
        if not git("--no-optional-locks", "status", "--porcelain", "--untracked-files=all", directory=path):
            candidates.append(dict(row))
    return candidates


def nonempty(value):
    if not value.strip():
        raise argparse.ArgumentTypeError("expected nonempty text")
    return value


def nonnegative_int(value):
    number = int(value)
    if not 0 <= number <= 2**63 - 1:
        raise argparse.ArgumentTypeError("expected a nonnegative SQLite integer")
    return number


def positive_int(value):
    number = nonnegative_int(value)
    if not number:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return number


def duration(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 0:
        raise argparse.ArgumentTypeError("expected a finite, nonnegative number of seconds")
    return seconds


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--db", help="state database path (defaults to TEAM_UP_DB or the current repository's state DB)")
    commands = cli.add_subparsers(dest="command", required=True)

    def command(name, handler=None, identifier=None, *, writes=True, turn=False):
        sub = commands.add_parser(name)
        sub.set_defaults(handler=handler, writes=writes)
        if identifier:
            sub.add_argument(identifier, type=positive_int)
        if turn:
            sub.add_argument("--turn", type=positive_int, required=True)
        return sub

    def worktree_options(sub, required=False):
        sub.add_argument("--worktree", type=nonempty, required=required)
        sub.add_argument("--branch", type=nonempty, required=required)

    command("init")
    run = command("run-create", create_run)
    run.add_argument("--goal", type=nonempty, required=True)
    run.add_argument("--slots", type=positive_int, required=True)
    run.add_argument("--base", type=nonempty)

    task = command("task-create", create_task, "run")
    task.add_argument("--worker", choices=("claude", "codex", "agy"), required=True)
    for option in ("goal", "scope", "evidence"):
        task.add_argument(f"--{option}", type=nonempty, required=True)
    for option in ("after", "after-merge"):
        task.add_argument(f"--{option}", type=positive_int, action="append", default=[])
    task.add_argument("--gate", type=nonempty, action="append", default=[])

    gate = command("gate", decide_gate, "run")
    gate.add_argument("name", type=nonempty)
    gate.add_argument("--decision", choices=("approve", "reject"), required=True)
    gate.add_argument("--note", type=nonempty)
    merged = command("merged", mark_merged, "task", writes=False)
    merged.add_argument("--base", type=nonempty, required=True)
    merged.add_argument("--commit", type=nonempty, required=True)

    reservation = command("reserve", reserve, "run")
    reservation.add_argument("--task", type=positive_int)
    reservation.add_argument("--review-main", action="store_true", help="place a read-only review in the primary checkout")
    worktree_options(reservation)
    retry_command = command("retry", retry, "dispatch")
    worktree_options(retry_command)
    retry_command.add_argument("--override", action="store_true",
                               help="allow one retry after three failed starts on user instruction")
    command("begin", begin, "dispatch", writes=False)
    worktree_options(command("register", register, "dispatch", writes=False, turn=True), required=True)
    start = command("started", started, "dispatch", writes=False, turn=True)
    start.add_argument("--runtime", type=nonempty, help="required for a running turn")
    start.add_argument("--session", type=nonempty, help="may be recovered by itself after the turn ends")
    start.add_argument("--unresumable", action="store_true")
    worktree_options(start)
    command("turn-ended", turn_ended, "dispatch", turn=True)
    exit_command = command("exited", exited, "dispatch", turn=True)
    exit_command.add_argument("--code", type=int, required=True)
    exit_flags = exit_command.add_mutually_exclusive_group()
    exit_flags.add_argument("--start-failed", action="store_true")
    exit_flags.add_argument("--stopped", action="store_true")
    command("stop", request_stop, "dispatch")
    command("abandon", request_stop, "dispatch").add_argument("--reason", type=nonempty, required=True)
    command("heartbeat", heartbeat, "dispatch", turn=True)

    command("record", record_question, "dispatch", turn=True).add_argument("question", type=nonempty)
    ask_command = command("ask", ask, "dispatch", writes=False, turn=True)
    ask_command.add_argument("question", type=nonempty)
    ask_command.add_argument("--timeout", type=duration, required=True)
    command("answer", answer_question, "question_id").add_argument("answer", type=nonempty)
    command("instruct", instruct, "dispatch").add_argument("text", type=nonempty)
    command("done", done, "dispatch", turn=True).add_argument("--evidence", required=True)

    command("wait", wait, "run", writes=False).add_argument("--timeout", type=duration, default=30)
    command("ack", ack, "run").add_argument("event", type=nonnegative_int)
    command("status", status, "run", writes=False)
    for name in ("keep-open", "takeover", "delivered"):
        command(name, flag_dispatch, "dispatch")
    command("cleanup", cleanup, "run", writes=False)
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        repo_common_dir = common_dir() if args.command == "init" else None
        path = database_path(args, repo_common_dir)
        with closing(connect(path, repo_common_dir)) as db:
            if args.command == "init":
                result = {"db": str(path), "schema_version": SCHEMA_VERSION,
                          "sqlite_version": sqlite3.sqlite_version,
                          "journal_mode": db.execute("PRAGMA journal_mode").fetchone()[0]}
            elif args.writes:
                with transaction(db):
                    result = args.handler(db, args)
            else:
                result = args.handler(db, args)
            if args.command in ("init", "status"):
                warning = wal_reset_warning()
                if warning:
                    result["warning"] = warning
    except KeyboardInterrupt:
        return 130
    except (StateError, sqlite3.Error, OSError, OverflowError) as exc:
        print(f"team-up: {exc}", file=sys.stderr)
        return 1
    if (args.command in ("turn-ended", "exited") and result["runtime"] is None
            and not getattr(args, "start_failed", False)):
        print(f"team-up: warning: Dispatch {args.dispatch} turn {args.turn} "
              "has no runtime handle recorded with started", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False))
    if args.command == "ask" and result["answer"] is None:
        return 124
    return 0


if __name__ == "__main__":
    sys.exit(main())
