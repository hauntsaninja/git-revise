from enum import Enum
from typing import List, Set, Optional
from .odb import Commit, Repository
from .utils import run_editor
import re

class StepKind(Enum):
    PICK = 1
    FIXUP = 2
    REWORD = 3
    INDEX = 4

    def __str__(self):
        if self == StepKind.PICK:
            return 'pick'
        elif self == StepKind.FIXUP:
            return 'fixup'
        elif self == StepKind.REWORD:
            return 'reword'
        elif self == StepKind.INDEX:
            return 'index'
        raise TypeError()

    @staticmethod
    def parse(s: str) -> 'StepKind':
        if len(s) < 1:
            raise ValueError()
        if 'pick'.startswith(s):
            return StepKind.PICK
        if 'fixup'.startswith(s):
            return StepKind.FIXUP
        if 'reword'.startswith(s):
            return StepKind.REWORD
        if 'index'.startswith(s):
            return StepKind.INDEX
        raise ValueError(f"step kind '{s}' must be one of: pick, fixup, reword, or index")


class Step:
    kind: StepKind
    commit: Commit

    def __str__(self):
        return f"{self.kind} {self.commit.oid.short()} {self.commit.summary()}"

    def __init__(self, kind: StepKind, commit: Commit):
        self.kind = kind
        self.commit = commit

    @staticmethod
    def parse(repo: Repository, s: str) -> 'Step':
        parsed = re.match('(?P<command>\S+)\s(?P<hash>\S+)', s)
        if not parsed:
            raise ValueError(f"todo entry '{s}' must follow format <keyword> <sha> <optional message>")
        kind = StepKind.parse(parsed.group('command'))
        commit = repo.getcommit(parsed.group('hash'))
        return Step(kind, commit)


def build_todos(commits: List[Commit], index: Optional[Commit]) -> List[Step]:
    steps = [Step(StepKind.PICK, commit) for commit in commits]
    if index:
        steps.append(Step(StepKind.INDEX, index))
    return steps


def edit_todos(repo: Repository, todos: List[Step]) -> List[Step]:
    # Invoke the editors to parse commit messages.
    todos_text = '\n'.join(str(step) for step in todos).encode()
    response = run_editor("git-zipfix-todo", todos_text, comments=f"""\
        Interactive Zipfix Todos ({len(todos)} commands)

        Commands:
         p, pick <commit> = use commit
         r, reword <commit> = use commit, but edit the commit message
         f, fixup <commit> = use commit, but fuse changes into previous commit
         i, index <commit> = leave commit changes unstaged

        These lines can be re-ordered; they are executed from top to bottom.

        If a line is removed, it will be treated like an 'index' line.

        However, if you remove everything, these changes will be aborted.
        """)

    # Parse the response back into a list of steps
    result = []
    seen: Set[Commit] = set()
    seen_index = False
    for line in response.splitlines():
        if line.isspace():
            continue
        step = Step.parse(repo, line.decode(errors='replace').strip())
        result.append(step)

        # Produce diagnostics for duplicated commits.
        if step.commit in seen:
            print(f"(warning) Commit {step.commit} referenced multiple times")
        seen.add(step.commit)

        if step.kind == StepKind.INDEX:
            seen_index = True
        elif seen_index:
            raise ValueError("Non-index todo found after index todo")

    # Produce diagnostics for missing and/or added commits.
    before = set(s.commit for s in todos)
    after = set(s.commit for s in result)
    for commit in (before - after):
        print(f"(warning) commit {commit} missing from todo list")
    for commit in (after - before):
        print(f"(warning) commit {commit} not in original todo list")

    return result