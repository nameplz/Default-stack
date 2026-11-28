#!/usr/bin/env python3
"""Store and coordinate team-up state. The host owns worker processes and sessions."""

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import fcntl
from fnmatch import fnmatchcase
import hashlib
from html import escape
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from tempfile import NamedTemporaryFile
import time


SCHEMA_VERSION = 5
RUN_NOTES_LIMIT = 4096
RUN_NOTES_TRUNCATED = b"\n[Run notes truncated]"
PROGRESS_TEXT_LIMIT = 200
STALL_SECONDS = 1800
ACTIVE_WORKERS = ("claude", "codex")
PR_POLICIES = ("auto", "hold", "manual")
PR_FIX_LIMIT = 3
PR_VIEW_FIELDS = ("headRefOid,statusCheckRollup,mergeable,mergeStateStatus,autoMergeRequest,"
                  "state,mergeCommit,files,url,baseRefName,changedFiles")
WAKE_EVENTS = ("question", "done", "pr-checks-failed", "pr-conflict")
PR_INFO_EVENTS = ("pr-checks-passed", "pr-behind", "pr-merged", "pr-closed", "pr-policy-downgraded")
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
V5_SCHEMA = """
ALTER TABLE runs ADD COLUMN notes_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE dispatches ADD COLUMN notes_version INTEGER;
ALTER TABLE dispatches ADD COLUMN progress_text TEXT;
ALTER TABLE dispatches ADD COLUMN progress_step INTEGER;
ALTER TABLE dispatches ADD COLUMN progress_total INTEGER;
ALTER TABLE dispatches ADD COLUMN progress_at TEXT;
CREATE TABLE run_notes (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX run_notes_run ON run_notes(run_id, id);
CREATE TABLE pull_requests (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    dispatch_id INTEGER NOT NULL REFERENCES dispatches(id),
    number INTEGER NOT NULL CHECK (number > 0),
    url TEXT,
    policy TEXT NOT NULL CHECK (policy IN ('auto', 'hold', 'manual')),
    approval_gate TEXT,
    state TEXT NOT NULL DEFAULT 'OPEN' CHECK (state IN ('OPEN', 'CLOSED', 'MERGED')),
    head_sha TEXT,
    checks TEXT CHECK (checks IN ('pending', 'passing', 'failing')),
    mergeable TEXT,
    merge_state TEXT,
    auto_merge INTEGER NOT NULL DEFAULT 0 CHECK (auto_merge IN (0, 1)),
    fix_rounds INTEGER NOT NULL DEFAULT 0 CHECK (fix_rounds BETWEEN 0 AND 3),
    merged_commit TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (run_id, approval_gate) REFERENCES gates(run_id, name)
);
CREATE UNIQUE INDEX one_open_pr_per_task ON pull_requests(task_id) WHERE state = 'OPEN';
CREATE UNIQUE INDEX one_open_pr_per_number ON pull_requests(number) WHERE state = 'OPEN';
CREATE UNIQUE INDEX one_pr_per_approval_gate ON pull_requests(run_id, approval_gate) WHERE approval_gate IS NOT NULL;
"""


class StateError(Exception):
    pass


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def git(*args, directory=None, nul=False):
    result = subprocess.run(
        ["git", *args], cwd=directory, text=not nul, capture_output=True, check=False
    )
    if result.returncode:
        raise StateError(os.fsdecode(result.stderr).strip() or f"git {args[0]} failed ({result.returncode})")
    return os.fsdecode(result.stdout) if nul else result.stdout.rstrip("\n")


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
            if version not in (3, 4, SCHEMA_VERSION):
                raise StateError(f"database schema version {version} does not match {SCHEMA_VERSION}; "
                                 "keep the existing DB and run init with a new --db path")
            if repository_common_dir(db) != str(repo_common_dir):
                raise StateError("database belongs to a different repository")
            if version != 3:
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
            elif version in (3, 4) and not create:
                raise StateError(f"database schema version {version} at {path}; run init with --db pointing "
                                 "to this file to upgrade")
            elif version not in (3, 4, SCHEMA_VERSION):
                raise StateError(f"database schema version {version} does not match {SCHEMA_VERSION}; "
                                 "keep the existing DB and run init with a new --db path")
            elif create and repository_common_dir(db) != str(repo_common_dir):
                raise StateError("database belongs to a different repository")
        if version == 3:
            migrate_v3(db, repo_common_dir)
        if create:
            if db.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                if db.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                    raise StateError("could not enable SQLite WAL mode")
            with transaction(db):
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version in (4, SCHEMA_VERSION) and repository_common_dir(db) != str(repo_common_dir):
                    raise StateError("database belongs to a different repository")
                if version == 0:
                    for statement in SCHEMA.split(";"):
                        if statement.strip():
                            db.execute(statement)
                    db.execute("INSERT INTO repository(id, common_dir) VALUES (1, ?)", (str(repo_common_dir),))
                    version = 4
                if version == 4:
                    for statement in V5_SCHEMA.split(";"):
                        if statement.strip():
                            db.execute(statement)
                    db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                    version = SCHEMA_VERSION
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


def add_note(db, args):
    version = run_row(db, args.run)["notes_version"] + 1
    created_at = timestamp()
    note_id = db.execute(
        "INSERT INTO run_notes(run_id, text, created_at) VALUES (?, ?, ?)",
        (args.run, args.text, created_at),
    ).lastrowid
    db.execute("UPDATE runs SET notes_version = ? WHERE id = ?", (version, args.run))
    return {"id": note_id, "run_id": args.run, "text": args.text, "created_at": created_at,
            "notes_version": version}


def brief_notes(db, run_id):
    content = bytearray()
    notes = db.execute("SELECT text FROM run_notes WHERE run_id = ? ORDER BY id DESC", (run_id,))
    for (note_text,) in notes:
        if content:
            content.extend(b"\n\n")
        content.extend(note_text[:RUN_NOTES_LIMIT + 1].encode("utf-8"))
        if len(content) > RUN_NOTES_LIMIT:
            del content[RUN_NOTES_LIMIT - len(RUN_NOTES_TRUNCATED):]
            return content.decode("utf-8", errors="ignore").rstrip() + RUN_NOTES_TRUNCATED.decode("ascii")
    return content.decode("utf-8")


def check_active_worker(worker):
    if worker not in ACTIVE_WORKERS:
        raise StateError(f"worker {worker!r} is not supported for new work; use claude or codex. "
                         "Existing records can still be inspected and closed.")


def create_task(db, args):
    check_active_worker(args.worker)
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
        if db.execute("SELECT 1 FROM pull_requests WHERE run_id = ? AND approval_gate = ?",
                      (args.run, name)).fetchone():
            raise StateError(f"gate {name!r} is dedicated to PR approval")
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
        return record_merge(db, task, base, sha)


def record_merge(db, task, base, sha):
    if task["merged_commit"] is not None:
        if task["merged_commit"] != sha or task["merged_base"] != base:
            raise StateError("the task already has a recorded merge")
        return dict(task)
    db.execute("UPDATE tasks SET merged_base = ?, merged_commit = ? WHERE id = ?", (base, sha, task["id"]))
    event(db, task["run_id"], "task-merged", {"base": base, "commit": sha}, task_id=task["id"])
    return dict(task_row(db, task["id"]))


def gh(directory, *args):
    try:
        result = subprocess.run(
            [os.environ.get("TEAM_UP_GH", "gh"), *map(str, args)],
            cwd=directory, text=True, capture_output=True, timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise StateError(f"gh {' '.join(map(str, args[:3]))} timed out") from exc
    if result.returncode:
        raise StateError(result.stderr.strip() or f"gh {args[0]} {args[1]} failed ({result.returncode})")
    return result.stdout


def pr_directory(db):
    if common_dir() != Path(repository_common_dir(db)):
        raise StateError("database belongs to a different repository")
    return Path(git("rev-parse", "--show-toplevel"))


def pr_view(directory, number):
    output = gh(directory, "pr", "view", number, "--json", PR_VIEW_FIELDS)
    try:
        remote = json.loads(output)
        if (remote["state"] not in ("OPEN", "MERGED", "CLOSED") or not remote["headRefOid"]
                or not isinstance(remote["statusCheckRollup"], (list, type(None)))
                or "autoMergeRequest" not in remote):
            raise ValueError
    except (ValueError, TypeError, KeyError) as exc:
        raise StateError(f"invalid GitHub state for PR #{number}") from exc
    return remote


def pr_requires_hold(directory, remote):
    try:
        lines = (directory / ".github" / "merge-policy").read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return False
    except UnicodeError as exc:
        raise StateError("could not read .github/merge-policy as UTF-8") from exc
    globs = [line for line in map(str.strip, lines) if line and not line.startswith("#")]
    if not globs:
        return False
    files = remote.get("files")
    if not isinstance(files, list) or remote.get("changedFiles", len(files)) != len(files):
        return True
    return any(
        not isinstance(file, dict) or not isinstance(file.get("path"), str) or not file["path"]
        or file.get("changeType") == "RENAMED"
        or any(path_matches(file["path"], pattern) for pattern in globs)
        for file in files
    )


def path_matches(path, pattern):
    parts = path.split("/")
    positions = {0}
    for glob in pattern.split("/"):
        if glob == "**" and positions:
            positions = set(range(min(positions), len(parts) + 1))
        else:
            positions = {i + 1 for i in positions if i < len(parts) and fnmatchcase(parts[i], glob)}
    return len(parts) in positions


def open_pr(db, task_id):
    return db.execute("SELECT * FROM pull_requests WHERE task_id = ? AND state = 'OPEN'", (task_id,)).fetchone()


@contextmanager
def pr_command_lock(db):
    database = db.execute("PRAGMA database_list").fetchone()[2]
    with open(f"{database}.pr.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise StateError("another PR command is in progress; retry after it finishes") from exc
        yield


def pr_registration(db, args):
    dispatch = dispatch_row(db, args.dispatch)
    task = task_row(db, dispatch["task_id"])
    if not dispatch["delivered"] or task["merged_commit"] is not None:
        raise StateError("pr-open requires a delivered dispatch for an unmerged task")
    old = open_pr(db, task["id"])
    if old:
        if (old["dispatch_id"], old["number"]) == (args.dispatch, args.number):
            return dispatch, old
        raise StateError(f"task {task['id']} already has open PR #{old['number']}")
    if db.execute("SELECT 1 FROM pull_requests WHERE number = ? AND state = 'OPEN'", (args.number,)).fetchone():
        raise StateError(f"PR #{args.number} already belongs to another task")
    return dispatch, None


def pr_open(db, args):
    dispatch, old = pr_registration(db, args)
    if old:
        if old["policy"] != "auto" and old["auto_merge"]:
            directory = pr_directory(db)
            remote = pr_view(directory, old["number"])
            return dict(reconcile_pr(db, run_row(db, old["run_id"]), old, directory, remote))
        return dict(old)
    directory = pr_directory(db)
    remote = pr_view(directory, args.number)
    if remote["state"] != "OPEN":
        raise StateError(f"PR #{args.number} is not open on GitHub")
    policy = "hold" if pr_requires_hold(directory, remote) else args.policy
    if policy == "auto":
        raise StateError("record the PR first, then use pr-policy auto with an approved gate")
    with transaction(db):
        dispatch, old = pr_registration(db, args)
        if old:
            return dict(old)
        now = timestamp()
        armed = remote["autoMergeRequest"] is not None
        db.execute(
            """INSERT INTO pull_requests
            (run_id, task_id, dispatch_id, number, url, policy, auto_merge, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (dispatch["run_id"], dispatch["task_id"], args.dispatch, args.number,
             args.url or remote.get("url"), policy, int(armed), now, now),
        )
        pr = open_pr(db, dispatch["task_id"])
    if armed:
        gh(directory, "pr", "merge", args.number, "--disable-auto")
        set_pr_auto_merge(db, pr, False)
    return dict(pr_by_id(db, pr["id"]))


def require_open_pr(db, task_id):
    task_row(db, task_id)
    pr = open_pr(db, task_id)
    if pr is None:
        raise StateError(f"task {task_id} has no open PR")
    return pr


def pr_by_id(db, pr_id):
    return db.execute("SELECT * FROM pull_requests WHERE id = ?", (pr_id,)).fetchone()


def require_unchanged_pr(db, pr):
    current = pr_by_id(db, pr["id"])
    if current is None or current["updated_at"] != pr["updated_at"] or dict(current) != dict(pr):
        raise StateError(f"PR #{pr['number']} changed while the command was running; retry")


def require_pr_gate(db, pr, name):
    gate = db.execute("SELECT decision FROM gates WHERE run_id = ? AND name = ?",
                      (pr["run_id"], name)).fetchone()
    if gate is None or gate["decision"] != "approve":
        raise StateError("auto policy requires --gate naming an approved gate in this run")
    if db.execute("SELECT 1 FROM task_gates WHERE run_id = ? AND name = ?",
                  (pr["run_id"], name)).fetchone():
        raise StateError(f"gate {name!r} is attached to a task; use a dedicated PR gate")
    if db.execute("SELECT 1 FROM pull_requests WHERE run_id = ? AND approval_gate = ? AND id != ?",
                  (pr["run_id"], name, pr["id"])).fetchone():
        raise StateError(f"gate {name!r} already approved another PR")
    if pr["approval_gate"] not in (None, name):
        raise StateError(f"PR #{pr['number']} already has approval gate {pr['approval_gate']!r}")


def pr_policy(db, args):
    pr = require_open_pr(db, args.task)
    gate = pr["approval_gate"]
    if args.policy == "auto":
        gate = args.gate
        require_pr_gate(db, pr, gate)
    error = None
    try:
        directory = pr_directory(db)
        remote = pr_view(directory, pr["number"])
    except (StateError, OSError) as exc:
        if args.policy == "auto":
            raise
        error = exc
    if args.policy == "auto":
        if remote["state"] != "OPEN" or pr_requires_hold(directory, remote):
            raise StateError(f"PR #{pr['number']} cannot use auto policy in its current GitHub state or merge policy")
    with transaction(db):
        require_unchanged_pr(db, pr)
        if args.policy == "auto":
            require_pr_gate(db, pr, gate)
        if (args.policy, gate) != (pr["policy"], pr["approval_gate"]):
            db.execute("UPDATE pull_requests SET policy = ?, approval_gate = ?, updated_at = ? WHERE id = ?",
                       (args.policy, gate, timestamp(), pr["id"]))
        current = pr_by_id(db, pr["id"])
    if error:
        raise error
    if args.policy != "auto":
        reconcile_pr(db, run_row(db, pr["run_id"]), current, directory, remote)
    return dict(pr_by_id(db, pr["id"]))


def pr_checks(checks):
    if not checks:
        return None
    states = {check.get("conclusion") or check.get("state") or check.get("status") for check in checks}
    if states & {"ACTION_REQUIRED", "CANCELLED", "ERROR", "FAILURE", "STALE", "STARTUP_FAILURE", "TIMED_OUT"}:
        return "failing"
    return "passing" if states <= {"SUCCESS", "NEUTRAL", "SKIPPED"} else "pending"


def pr_conflict(pr):
    return pr["mergeable"] == "CONFLICTING" or pr["merge_state"] == "DIRTY"


def pr_base(run, remote, number):
    target = remote.get("baseRefName")
    base = run["base"] or target
    if target and base not in (target, f"refs/heads/{target}", f"origin/{target}", f"refs/remotes/origin/{target}"):
        raise StateError(f"PR #{number} targets {target!r}, expected {base!r}")
    return base


def observe_pr(db, run, pr, remote, requires_hold):
    state = remote["state"]
    policy = pr["policy"]
    if requires_hold:
        policy = "hold"
    sha = (remote.get("mergeCommit") or {}).get("oid") if state == "MERGED" else None
    current = {
        "state": state, "policy": policy, "head_sha": remote["headRefOid"],
        "checks": pr_checks(remote["statusCheckRollup"]), "mergeable": remote.get("mergeable"),
        "merge_state": remote.get("mergeStateStatus"), "merged_commit": sha,
        "auto_merge": int(state == "OPEN" and remote["autoMergeRequest"] is not None),
    }
    kinds = []
    if state == "MERGED":
        base = pr_base(run, remote, pr["number"])
        if not sha or not base:
            raise StateError(f"merged PR #{pr['number']} is missing its commit or base ref")
        record_merge(db, task_row(db, pr["task_id"]), base, sha)
        kinds.append("pr-merged")
    elif state == "CLOSED":
        kinds.append("pr-closed")
    else:
        new_head = current["head_sha"] != pr["head_sha"]
        checks = current["checks"]
        if new_head or checks != pr["checks"]:
            kind = {"passing": "pr-checks-passed", "failing": "pr-checks-failed"}.get(checks)
            if kind:
                kinds.append(kind)
        if pr_conflict(current) and (new_head or not pr_conflict(pr)):
            kinds.append("pr-conflict")
        if current["merge_state"] == "BEHIND" and (new_head or pr["merge_state"] != "BEHIND"):
            kinds.append("pr-behind")
        if policy != pr["policy"]:
            kinds.append("pr-policy-downgraded")
    if any(pr[key] != value for key, value in current.items()):
        fields = ", ".join(f"{key} = ?" for key in current)
        db.execute(f"UPDATE pull_requests SET {fields}, updated_at = ? WHERE id = ?",
                   (*current.values(), timestamp(), pr["id"]))
    for kind in kinds:
        event(db, run["id"], kind, {"number": pr["number"], **current}, pr["task_id"], pr["dispatch_id"])


def set_pr_auto_merge(db, pr, enabled):
    with transaction(db):
        require_unchanged_pr(db, pr)
        db.execute("UPDATE pull_requests SET auto_merge = ?, updated_at = ? WHERE id = ?",
                   (int(enabled), timestamp(), pr["id"]))


def reconcile_pr(db, run, pr, directory, remote, *, sync=False):
    requires_hold = (remote["state"] == "OPEN" and pr["policy"] == "auto"
                     and pr_requires_hold(directory, remote))
    with transaction(db):
        require_unchanged_pr(db, pr)
        observe_pr(db, run, pr, remote, requires_hold)
        current = pr_by_id(db, pr["id"])
    if current["state"] == "OPEN":
        if current["policy"] != "auto" and current["auto_merge"]:
            gh(directory, "pr", "merge", current["number"], "--disable-auto")
            set_pr_auto_merge(db, current, False)
        elif sync and current["policy"] == "auto" and current["merge_state"] == "BEHIND" and not current["auto_merge"]:
            pr_base(run, remote, current["number"])
            gh(directory, "pr", "update-branch", current["number"])
    return pr_by_id(db, pr["id"])


def pr_sync(db, args):
    run = run_row(db, args.run)
    rows = db.execute(
        "SELECT id FROM pull_requests WHERE run_id = ? AND state = 'OPEN' ORDER BY id", (args.run,),
    ).fetchall()
    synced, errors = [], []
    if rows:
        directory = pr_directory(db)
    for row in rows:
        with pr_command_lock(db):
            pr = pr_by_id(db, row["id"])
            if pr["state"] == "OPEN":
                try:
                    remote = pr_view(directory, pr["number"])
                    current = reconcile_pr(db, run, pr, directory, remote, sync=True)
                except (StateError, OSError) as exc:
                    errors.append(f"PR #{pr['number']}: {exc}")
                else:
                    synced.append(dict(current))
    if errors:
        raise StateError("\n".join(errors))
    return {"run_id": args.run, "pull_requests": synced}


def pr_arm(db, args):
    pr = require_open_pr(db, args.task)
    if pr["policy"] != "auto":
        raise StateError(f"PR #{pr['number']} policy is {pr['policy']}; pr-arm requires auto")
    directory = pr_directory(db)
    run = run_row(db, pr["run_id"])
    remote = pr_view(directory, pr["number"])
    current = reconcile_pr(db, run, pr, directory, remote)
    with transaction(db):
        require_unchanged_pr(db, current)
        if current["state"] != "OPEN":
            refusal = "is no longer open"
        elif current["policy"] != "auto":
            refusal = "is held by .github/merge-policy"
        elif current["checks"] == "failing":
            refusal = "has failing checks"
        elif pr_conflict(current):
            refusal = "has merge conflicts"
        else:
            refusal = None
            pr_base(run, remote, pr["number"])
    if refusal:
        raise StateError(f"PR #{pr['number']} {refusal}; auto-merge was not armed")
    if not current["auto_merge"]:
        gh(directory, "pr", "merge", current["number"], "--auto", "--squash",
           "--match-head-commit", current["head_sha"])
        set_pr_auto_merge(db, current, True)
    return dict(pr_by_id(db, pr["id"]))


READY = f"""
    SELECT t.* FROM tasks t
    WHERE t.run_id = ? AND (? IS NULL OR t.id = ?)
      AND t.worker IN ({', '.join('?' for _ in ACTIVE_WORKERS)})
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


def occupied_slots(db, run_id):
    return db.execute(
        """SELECT count(*) FROM dispatches d JOIN tasks t ON t.id = d.task_id
        WHERE t.run_id = ? AND d.phase != 'closed'""", (run_id,)
    ).fetchone()[0]


def slot_available(db, run):
    return occupied_slots(db, run["id"]) < run["slots"]


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
    check_active_worker(task["worker"])
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
    if args.task is not None:
        task = task_row(db, args.task)
        if task["run_id"] != args.run:
            raise StateError("the task belongs to another run")
        check_active_worker(task["worker"])
    worktree, branch = worktree_spec(args)
    if not slot_available(db, run):
        return None
    task = db.execute(READY, (args.run, args.task, args.task, *ACTIVE_WORKERS)).fetchone()
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
    check_active_worker(task_row(db, snapshot["task_id"])["worker"])
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
            pr = open_pr(db, dispatch["task_id"])
            fixing_pr = (pr is not None and pr["dispatch_id"] == dispatch["id"]
                         and (pr["checks"] == "failing" or pr_conflict(pr)))
            if fixing_pr and pr["fix_rounds"] >= PR_FIX_LIMIT:
                raise StateError(f"PR #{pr['number']} reached {PR_FIX_LIMIT} fix rounds; user review is required")
            if not slot_available(db, run_row(db, dispatch["run_id"])):
                raise StateError("no run slot is available for the follow-up")
            if fixing_pr and pr["auto_merge"]:
                raise StateError(f"disable auto-merge on PR #{pr['number']} and run pr-sync before starting a fix")
            check_worktree_claim(db, dispatch["worktree"], args.dispatch)
            if fixing_pr:
                db.execute("UPDATE pull_requests SET fix_rounds = fix_rounds + 1, updated_at = ? WHERE id = ?",
                           (timestamp(), pr["id"]))
            dispatch_event(db, dispatch, "completion-followed-up", evidence=json.loads(dispatch["evidence"]),
                           delivered=bool(dispatch["delivered"]))
            db.execute("UPDATE tasks SET completed_at = NULL WHERE id = ? AND merged_commit IS NULL",
                       (dispatch["task_id"],))
        elif phase != "reserved":
            raise StateError("begin requires a reservation or a confirmed exit before resuming")
        notes_version = run_row(db, dispatch["run_id"])["notes_version"]
        db.execute(
            """UPDATE dispatches SET phase = 'running', turn = turn + 1, runtime = NULL,
            heartbeat_at = ?, turn_ended_at = NULL, exited_at = NULL, exit_code = NULL,
            progress_text = NULL, progress_step = NULL, progress_total = NULL, progress_at = NULL,
            outcome = NULL, evidence = NULL, delivered = 0, notes_version = ? WHERE id = ?""",
            (timestamp(), notes_version, args.dispatch),
        )
        dispatch_event(db, dispatch_row(db, args.dispatch), "turn-begun", notes_version=notes_version)
        result = brief(db, args.dispatch)
        result["notes"] = brief_notes(db, dispatch["run_id"])
        return result


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


def check_start_registration(db, dispatch):
    if dispatch["runtime"] is None and dispatch["phase"] in ("running", "turn-ended"):
        check_active_worker(task_row(db, dispatch["task_id"])["worker"])


def register(db, args):
    worktree, branch = worktree_spec(args)
    check_worktree(db, worktree, branch, dispatch_row(db, args.dispatch)["review_main"])
    with transaction(db):
        dispatch = current_turn(db, args)
        check_start_registration(db, dispatch)
        save_worktree(db, dispatch, worktree, branch)
        return brief(db, args.dispatch)


def started(db, args):
    worktree, branch = worktree_spec(args)
    if worktree:
        check_worktree(db, worktree, branch, dispatch_row(db, args.dispatch)["review_main"])
    with transaction(db):
        dispatch = current_turn(db, args)
        check_start_registration(db, dispatch)
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


def progress(db, args):
    dispatch = current_turn(db, args)
    if dispatch["phase"] != "running":
        raise StateError("progress requires a running turn")
    if len(args.text) > PROGRESS_TEXT_LIMIT:
        raise StateError(f"progress text must be at most {PROGRESS_TEXT_LIMIT} characters")
    step, total = args.step or (dispatch["progress_step"], dispatch["progress_total"])
    now = timestamp()
    db.execute(
        """UPDATE dispatches SET progress_text = ?, progress_step = ?, progress_total = ?,
        progress_at = ?, heartbeat_at = ? WHERE id = ?""",
        (args.text, step, total, now, now, args.dispatch),
    )
    report = {"progress_text": args.text, "progress_step": step, "progress_total": total,
              "progress_at": now, "heartbeat_at": now}
    dispatch_event(db, dispatch, "progress", **report)
    return {"dispatch_id": args.dispatch, "turn": args.turn, **report}


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


def check_resumable_worker(db, dispatch):
    worker = task_row(db, dispatch["task_id"])["worker"]
    if worker not in ACTIVE_WORKERS:
        raise StateError(f"worker {worker!r} is disabled and will not be resumed")


def answer_question(db, args):
    message = db.execute("SELECT * FROM messages WHERE id = ? AND kind = 'question'", (args.question_id,)).fetchone()
    if message is None:
        raise StateError(f"unknown question {args.question_id}")
    dispatch = dispatch_row(db, message["dispatch_id"])
    check_resumable_worker(db, dispatch)
    if message["answer"] is not None:
        if message["answer"] != args.answer:
            raise StateError("the question already has a different answer")
        return dict(message)
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
    check_resumable_worker(db, dispatch)
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
    value = args.evidence
    if args.evidence_file is not None:
        try:
            value = args.evidence_file.read_bytes().decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise StateError(f"could not read evidence file {str(args.evidence_file)!r}: {exc}") from exc
    evidence = completion_evidence(value)
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
    next_sync = time.monotonic()
    kinds = WAKE_EVENTS + PR_INFO_EVENTS
    while True:
        if args.sync_prs is not None and time.monotonic() >= next_sync:
            try:
                pr_sync(db, args)
            except (StateError, OSError) as exc:
                print(f"team-up: pr-sync: {exc}", file=sys.stderr)
            next_sync = time.monotonic() + args.sync_prs
        with transaction(db, write=False):
            cursor = run_row(db, args.run)["cursor"]
            wake = db.execute(
                f"""SELECT 1 FROM events WHERE run_id = ? AND id > ?
                AND kind IN ({', '.join('?' for _ in WAKE_EVENTS)}) LIMIT 1""",
                (args.run, cursor, *WAKE_EVENTS),
            ).fetchone()
            if wake or time.monotonic() >= deadline:
                events = [decode(row, "data") for row in db.execute(
                    f"""SELECT * FROM events WHERE run_id = ? AND id > ?
                    AND kind IN ({', '.join('?' for _ in kinds)}) ORDER BY id LIMIT 101""",
                    (args.run, cursor, *kinds),
                )]
                if len(events) > 100:
                    return {"events": events[:100], "cursor": events[99]["id"]}
                cursor = db.execute(
                    "SELECT coalesce(max(id), ?) FROM events WHERE run_id = ? AND id > ?",
                    (cursor, args.run, cursor),
                ).fetchone()[0]
                return {"events": events, "cursor": cursor}
        remaining = deadline - time.monotonic()
        if args.sync_prs is not None:
            remaining = min(remaining, next_sync - time.monotonic())
        time.sleep(max(0, min(0.1, remaining)))


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
            "pull_requests": "r.id",
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
        result["notes"] = [dict(row) for row in db.execute(
            "SELECT * FROM run_notes WHERE run_id = ? ORDER BY id", (args.run,)
        )]
        return result


BOARD_GROUPS = (
    ("needs_user", "내 차례"),
    ("in_progress", "진행 중"),
    ("review", "검토 대기"),
    ("merging", "머지 중"),
    ("blocked", "막힘"),
    ("done", "완료"),
)


def elapsed(since, now):
    seconds = max(0, int((now - datetime.fromisoformat(since)).total_seconds()))
    if seconds < 60:
        return f"{seconds}초"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}분"
    return f"{minutes // 60}시간 {minutes % 60}분"


def short_goal(goal, limit=48):
    line = goal.strip().splitlines()[0] if goal.strip() else ""
    return line if len(line) <= limit else line[:limit - 1] + "…"


def untracked_lines(path):
    if path.is_symlink():
        target = os.readlink(path)
        return target.count("\n") + (not target.endswith("\n"))
    if not path.is_file():
        return 0
    with path.open("rb") as file:
        chunk = file.read(8000)
        if not chunk or b"\0" in chunk:
            return 0
        lines = 0
        while chunk:
            lines += chunk.count(b"\n")
            last_byte = chunk[-1:]
            chunk = file.read(65536)
        return lines + (last_byte != b"\n")


def worktree_diff_stats(worktree):
    if not worktree:
        return None
    try:
        root = Path(worktree)
        if not (root / ".git").exists():
            return None
        options = {"directory": root, "nul": True}
        diff = git("--no-optional-locks", "diff", "--numstat", "-z", "--no-ext-diff",
                   "--no-textconv", "HEAD", "--", **options)
        untracked = git("--no-optional-locks", "ls-files", "--others", "--exclude-standard", "-z", **options)
        files = added = deleted = 0
        records = iter(diff.split("\0"))
        for record in records:
            if not record:
                break
            additions, deletions, path = record.split("\t", 2)
            renamed_with_old_and_new_paths_next = not path
            if renamed_with_old_and_new_paths_next:
                next(records)
                next(records)
            files += 1
            if additions != "-":
                added += int(additions)
                deleted += int(deletions)
        for path in untracked.split("\0"):
            if path:
                files += 1
                added += untracked_lines(root / path)
    except (OSError, StateError):
        return None
    return {"files": files, "added": added, "deleted": deleted}


def board_pr(pr):
    number = f"PR #{pr['number']}"
    trouble = "충돌" if pr_conflict(pr) else "실패" if pr["checks"] == "failing" else None
    if trouble and pr["fix_rounds"] >= PR_FIX_LIMIT:
        return "needs_user", f"수정 {pr['fix_rounds']}회 · 확인 필요"
    if pr["policy"] in ("hold", "manual") and pr["checks"] == "passing" and not trouble:
        action = "승인 필요" if pr["policy"] == "hold" else "수동 머지"
        return "needs_user", f"{number} {action}"
    if trouble:
        return "merging", f"{number} {trouble}"
    detail = {"hold": "보류(hold)", "manual": "수동 머지"}.get(pr["policy"])
    if detail is None:
        detail = "자동머지" if pr["auto_merge"] else "검사 통과" if pr["checks"] == "passing" else "검사 중"
    return "merging", f"{number} {detail}"


def board_entry(task, dispatches, dependencies, dependents, gates, messages, pr, now):
    """Return (group, fact, details) for one task; the first matching group wins."""
    latest = dispatches[-1] if dispatches else None
    if latest and latest["phase"] != "closed":
        pending = [m for m in messages.get(latest["id"], ())
                   if m["kind"] == "question" and m["turn"] == latest["turn"]
                   and m["answer"] is None and not m["consumed"]]
        if pending and not latest["stop_requested"]:
            return "needs_user", pending[0]["text"], {"questions": [{"id": m["id"], "text": m["text"]} for m in pending]}
        return "in_progress", elapsed(latest["reserved_at"], now), {"phase": latest["phase"]}
    if latest is None:
        undecided = [g["name"] for g in gates if g["decision"] is None]
        if undecided:
            return "needs_user", f"gate {', '.join(undecided)}", {"gates": undecided}
        waits = []
        for dep in dependencies:
            if not dep["finished"]:
                waits.append(f"#{dep['prerequisite_id']}")
            elif dep["condition"] == "merge" and not dep["merged"]:
                waits.append(f"#{dep['prerequisite_id']} 머지")
        waits += [f"gate {g['name']}" for g in gates if g["decision"] == "reject"]
        if task["worker"] not in ACTIVE_WORKERS:
            waits.append(f"{task['worker']} 비활성")
        if waits:
            return "blocked", "← " + ", ".join(waits), {"waits_on": waits}
        return "in_progress", "대기열", {"queued": True}
    if pr is not None:
        group, fact = board_pr(pr)
        return group, fact, {"pull_request": dict(pr)}
    start_failures = sum(1 for d in dispatches if d["outcome"] == "start-failed")
    if (latest["outcome"] == "start-failed" and start_failures >= 3
            and not latest["abandon_reason"] and not latest["taken_over"]):
        return "needs_user", f"시작 실패 {start_failures}회 · retry --override", {"start_failures": start_failures}
    succeeded = latest["outcome"] == "success"
    if succeeded and not latest["delivered"]:
        return "review", latest["branch"] or f"D{latest['id']}", {}
    if succeeded and task["merged_commit"] is None:
        waiting = [f"#{d['task_id']}" for d in dependents if d["condition"] == "merge" and not d["dispatched"]]
        if waiting:
            return "merging", "→ " + ", ".join(waiting), {"dependents": waiting}
    if succeeded:
        return "done", "머지됨" if task["merged_commit"] else "전달됨", {}
    return "done", latest["outcome"] or "closed", {"abandon_reason": latest["abandon_reason"]}


def board(db, args, *, include_slots=False):
    now = datetime.now(timezone.utc)
    with transaction(db, write=False):
        run = run_row(db, args.run)
        if include_slots:
            occupied = occupied_slots(db, args.run)
        tasks = db.execute("SELECT * FROM tasks WHERE run_id = ? ORDER BY id", (args.run,)).fetchall()
        dispatches, messages, dependencies, dependents, gates = {}, {}, {}, {}, {}
        for row in db.execute(
            """SELECT d.* FROM dispatches d JOIN tasks t ON t.id = d.task_id
            WHERE t.run_id = ? ORDER BY d.task_id, d.attempt""", (args.run,)
        ):
            dispatches.setdefault(row["task_id"], []).append(row)
        for row in db.execute(
            """SELECT m.* FROM messages m JOIN dispatches d ON d.id = m.dispatch_id
            JOIN tasks t ON t.id = d.task_id WHERE t.run_id = ? ORDER BY m.id""", (args.run,)
        ):
            messages.setdefault(row["dispatch_id"], []).append(row)
        for row in db.execute(
            """SELECT dep.*, p.merged_commit IS NOT NULL AS merged,
                EXISTS (SELECT 1 FROM dispatches d WHERE d.task_id = p.id AND d.outcome = 'success') AS finished,
                EXISTS (SELECT 1 FROM dispatches d WHERE d.task_id = dep.task_id) AS dispatched
            FROM dependencies dep JOIN tasks p ON p.id = dep.prerequisite_id
            WHERE p.run_id = ? ORDER BY dep.task_id, dep.prerequisite_id""", (args.run,)
        ):
            dependencies.setdefault(row["task_id"], []).append(row)
            dependents.setdefault(row["prerequisite_id"], []).append(row)
        for row in db.execute(
            """SELECT tg.task_id, g.name, g.decision FROM task_gates tg
            JOIN gates g ON g.run_id = tg.run_id AND g.name = tg.name
            WHERE tg.run_id = ? ORDER BY tg.task_id, g.name""", (args.run,)
        ):
            gates.setdefault(row["task_id"], []).append(row)
        prs = {row["task_id"]: row for row in db.execute(
            """SELECT p.* FROM pull_requests p JOIN tasks t ON t.id = p.task_id
            WHERE t.run_id = ? AND p.state = 'OPEN'""", (args.run,)
        )}
    groups = {key: [] for key, _ in BOARD_GROUPS}
    for task in tasks:
        history = dispatches.get(task["id"], [])
        latest = history[-1] if history else None
        group, fact, details = board_entry(
            task, history, dependencies.get(task["id"], []), dependents.get(task["id"], []),
            gates.get(task["id"], []), messages, prs.get(task["id"]), now,
        )
        if latest and latest["phase"] == "running":
            last_update = max(filter(None, (latest["heartbeat_at"], latest["progress_at"])), default=None)
            details.update({key: latest[key] for key in
                            ("phase", "progress_text", "progress_step", "progress_total", "progress_at")})
            details["last_update_at"] = last_update
            details["stalled"] = (last_update is not None
                                  and (now - datetime.fromisoformat(last_update)).total_seconds() > STALL_SECONDS)
            details["diff_stats"] = worktree_diff_stats(latest["worktree"])
        groups[group].append({
            "task_id": task["id"], "worker": task["worker"], "goal": short_goal(task["goal"]),
            "dispatch_id": latest["id"] if latest else None, "fact": fact, **details,
        })
    result = {"run_id": args.run, "groups": [
        {"key": key, "title": title, "count": len(groups[key]), "tasks": groups[key]}
        for key, title in BOARD_GROUPS
    ]}
    if include_slots:
        result.update(occupied=occupied, slots=run["slots"])
    return result


def render_board(result):
    lines = []
    for group in result["groups"]:
        if not group["tasks"]:
            continue
        if lines:
            lines.append("")
        lines.append(f"{group['title']} ({group['count']})")
        for task in group["tasks"]:
            facts = [task["fact"]]
            if task.get("stalled"):
                facts.append("⚠ 정체")
            if task.get("progress_step") is not None:
                facts.append(f"{task['progress_step']}/{task['progress_total']} 단계")
            if task.get("progress_text"):
                facts.append("".join(char if char.isprintable() else " " for char in task["progress_text"]))
            if task.get("diff_stats") is not None:
                diff = task["diff_stats"]
                facts.append(f"{diff['files']}개 파일 +{diff['added']} -{diff['deleted']}")
            if task.get("last_update_at"):
                facts.append(task["last_update_at"])
            lines.append(f"  #{task['task_id']} {task['worker']} {task['goal']}  " + " · ".join(facts))
    return "\n".join(lines)


BOARD_CSS = """
:root {
  color-scheme: light dark;
  --bg: #f4f5f7; --card: #fff; --text: #17202d; --muted: #4b5868;
  --line: #d5dbe3; --accent: #235bbd; --focus: #edf4ff; --stall: #a03917;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #141922; --card: #1d2531; --text: #e9eef6; --muted: #b3bfce;
    --line: #3c4859; --accent: #8db7ff; --focus: #202f48; --stall: #ffad8a;
  }
}
* { box-sizing: border-box; }
body {
  max-width: 76rem; margin: 0 auto; padding: clamp(1rem, 4vw, 2.5rem);
  background: var(--bg); color: var(--text);
  font: 1rem/1.45 system-ui, sans-serif; overflow-wrap: anywhere;
}
header, h2, .task-meta, .stats {
  display: flex; align-items: baseline; flex-wrap: wrap; gap: .35rem .65rem;
}
header { justify-content: space-between; border-bottom: 1px solid var(--line); padding-bottom: 1rem; }
h1, h2, p { margin: 0; }
h1 { font-size: 1.5rem; }
main { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 19rem), 1fr)); gap: 1rem; }
section { min-width: 0; }
h2 { font-size: 1rem; padding: 1rem 0 .5rem; }
article {
  margin-bottom: .5rem; padding: .75rem; border: 1px solid var(--line);
  border-radius: .5rem; background: var(--card);
}
article p { margin-top: .3rem; }
.needs_user article { border-inline-start: .25rem solid var(--accent); background: var(--focus); }
article.stalled { border-color: var(--stall); }
.stall { color: var(--stall); font-weight: 600; }
.count, .task-meta, .stats, .fact { color: var(--muted); font-variant-numeric: tabular-nums; }
.task-meta, .stats, .fact { font-size: .875rem; }
.goal { font-weight: 600; }
.track { height: .3rem; margin-top: .55rem; border-radius: 1rem; background: var(--line); overflow: hidden; }
.track span { display: block; height: 100%; background: var(--accent); }
.stalled .track span { background: var(--stall); }
"""


def render_board_card(task, running):
    stalled = running and task["stalled"]
    markup = [
        '<article class="stalled">' if stalled else '<article>',
        f'<div class="task-meta"><strong>#{task["task_id"]}</strong> {escape(task["worker"])}</div>',
        f'<p class="goal">{escape(task["goal"])}</p>',
        f'<p class="fact">{escape(task["fact"])}</p>',
    ]
    if running:
        stats = []
        step, total = task["progress_step"], task["progress_total"]
        if step is not None:
            markup.append(f'<div class="track" aria-hidden="true"><span style="width: {100 * step / total:g}%"></span></div>')
            stats.append(f"<span>{step}/{total}</span>")
        if task["progress_text"]:
            markup.append(f'<p>{escape(task["progress_text"])}</p>')
        diff = task["diff_stats"]
        if diff is not None:
            stats.append(f'<span>{diff["files"]}개 파일</span><span>+{diff["added"]} −{diff["deleted"]}</span>')
        if task["last_update_at"]:
            updated = datetime.fromisoformat(task["last_update_at"]).astimezone()
            stats.append(f'<time>{updated:%H:%M:%S}</time>')
        if stalled:
            stats.append('<span class="stall">정체</span>')
        if stats:
            markup.append('<p class="stats">' + "".join(stats) + "</p>")
    markup.append("</article>")
    return "\n".join(markup)


def render_board_html(result, refresh):
    markup = [
        '<!doctype html>', '<html lang="ko">', '<head>', '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
    ]
    if refresh is not None:
        markup.append(f'<meta http-equiv="refresh" content="{refresh}">')
    markup.extend([
        f'<title>Run #{result["run_id"]}</title>',
        f'<style>{BOARD_CSS}</style>', '</head>', '<body>',
        f'<header><h1>Run #{result["run_id"]}</h1>'
        f'<span class="count">{result["occupied"]}/{result["slots"]}</span></header>',
        '<main>',
    ])
    for group in result["groups"]:
        markup.append(f'<section class="{escape(group["key"])}">')
        markup.append(f'<h2>{escape(group["title"])} <span class="count">{group["count"]}</span></h2>')
        for task in group["tasks"]:
            running = group["key"] == "in_progress" and task.get("phase") == "running"
            markup.append(render_board_card(task, running))
        markup.append("</section>")
    return "\n".join([*markup, "</main>", "</body>", "</html>", ""])


def write_board_html(path, markup):
    temp = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temp = Path(file.name)
            file.write(markup)
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def board_finished(result):
    populated = {group["key"] for group in result["groups"] if group["tasks"]}
    return populated == {"done"}


def board_html(db, args, db_path):
    if args.html is True:
        path = db_path.parent / "boards" / f"run-{args.run}.html"
        path.parent.mkdir(exist_ok=True)
    else:
        path = args.html.expanduser().absolute()
    try:
        while True:
            result = board(db, args, include_slots=True)
            finished = board_finished(result)
            refresh = None if finished else args.watch or 5
            write_board_html(path, render_board_html(result, refresh))
            if finished or args.watch is None:
                return {"path": str(path), "finished": finished}
            time.sleep(args.watch)
    except KeyboardInterrupt:
        if args.watch is None:
            raise
        result = board(db, args, include_slots=True)
        write_board_html(path, render_board_html(result, None))
        return {"path": str(path), "finished": False}


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
        AND NOT EXISTS (SELECT 1 FROM pull_requests p WHERE p.dispatch_id = d.id AND p.state = 'OPEN')
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


def progress_step(value):
    match = re.fullmatch(r"([0-9]{1,19})/([0-9]{1,19})", value)
    if match:
        step, total = map(int, match.groups())
        if 1 <= step <= total <= 2**63 - 1:
            return step, total
    raise argparse.ArgumentTypeError("expected k/n with 1 <= k <= n and both numbers fitting a 64-bit integer")


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
    command("note", add_note, "run").add_argument("text", type=nonempty)

    task = command("task-create", create_task, "run")
    task.add_argument("--worker", choices=ACTIVE_WORKERS, required=True)
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
    pull_request = command("pr-open", pr_open, "dispatch", writes=False)
    pull_request.add_argument("--number", type=positive_int, required=True)
    pull_request.add_argument("--url", type=nonempty)
    pull_request.add_argument("--policy", choices=PR_POLICIES, default="hold")
    policy = command("pr-policy", pr_policy, "task", writes=False)
    policy.add_argument("policy", choices=PR_POLICIES)
    policy.add_argument("--gate", type=nonempty)
    command("pr-sync", pr_sync, "run", writes=False)
    command("pr-arm", pr_arm, "task", writes=False)

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
    progress_command = command("progress", progress, "dispatch", turn=True)
    progress_command.add_argument("--step", type=progress_step, metavar="k/n")
    progress_command.add_argument("text", type=nonempty)

    command("record", record_question, "dispatch", turn=True).add_argument("question", type=nonempty)
    ask_command = command("ask", ask, "dispatch", writes=False, turn=True)
    ask_command.add_argument("question", type=nonempty)
    ask_command.add_argument("--timeout", type=duration, required=True)
    command("answer", answer_question, "question_id").add_argument("answer", type=nonempty)
    command("instruct", instruct, "dispatch").add_argument("text", type=nonempty)
    done_command = command("done", done, "dispatch", turn=True)
    evidence_group = done_command.add_mutually_exclusive_group(required=True)
    evidence_group.add_argument("--evidence", metavar="JSON")
    evidence_group.add_argument("--evidence-file", type=Path, metavar="PATH")

    wait_command = command("wait", wait, "run", writes=False)
    wait_command.add_argument("--timeout", type=duration, default=30)
    wait_command.add_argument("--sync-prs", type=positive_int, metavar="SECONDS")
    command("ack", ack, "run").add_argument("event", type=nonnegative_int)
    command("status", status, "run", writes=False)
    board_command = command("board", board, "run", writes=False)
    board_format = board_command.add_mutually_exclusive_group()
    board_format.add_argument("--json", action="store_true")
    board_format.add_argument("--html", nargs="?", const=True, type=Path, metavar="PATH")
    board_command.add_argument("--watch", type=positive_int, metavar="SECONDS")
    for name in ("keep-open", "takeover", "delivered"):
        command(name, flag_dispatch, "dispatch")
    command("cleanup", cleanup, "run", writes=False)
    return cli


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    html_board = args.command == "board" and args.html is not None
    watching_board = args.command == "board" and args.watch is not None
    if watching_board and not html_board:
        cli.error("--watch requires --html")
    try:
        repo_common_dir = common_dir() if args.command == "init" else None
        path = database_path(args, repo_common_dir)
        with closing(connect(path, repo_common_dir)) as db:
            if args.command == "init":
                result = {"db": str(path), "schema_version": SCHEMA_VERSION,
                          "sqlite_version": sqlite3.sqlite_version,
                          "journal_mode": db.execute("PRAGMA journal_mode").fetchone()[0]}
            elif args.command in ("pr-open", "pr-policy", "pr-arm"):
                with pr_command_lock(db):
                    result = args.handler(db, args)
            elif html_board:
                result = board_html(db, args, path)
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
    if args.command == "board" and not args.json and not html_board:
        print(render_board(result))
        return 0
    print(json.dumps(result, ensure_ascii=False))
    if args.command == "ask" and result["answer"] is None:
        return 124
    return 0


if __name__ == "__main__":
    sys.exit(main())
