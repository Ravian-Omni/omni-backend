"""
evidence_first.py — executable enforcement of the Evidence-First Coding skill.

Rules are control flow, not prose. Each rule either passes on measured evidence
or raises. The loop cannot apply a change it cannot verify, cannot claim a gain
it cannot re-measure, and cannot game its own tests without tripping a guard.

    python evidence_first.py --demo        # exercise the whole system
    python evidence_first.py --json        # machine-readable demo output
"""

.evidence_first/
  README.md                  # generated; explains every file below
  LOCK                       # PID of the running loop; absent when idle
  index.json                 # ← agent's first read: last round, current R, convergence, pending-human queue
  ledger.jsonl               # append-only evidence trail (one JSON object per line)
  backlog.json               # current ranked next-round backlog
  rounds/
    round_0001.md            # human/agent-readable report
    round_0001.json          # machine-readable report (same content)
    round_0001.logs.txt      # raw logs triaged that round
    round_0002.md
    ...


## Persistent Workspace (`.evidence_first/`)

Every run of the loop writes its intermediate state to a dedicated, gitignored
folder at the repo root so a future agent (or human) can inspect it at any time
without re-running:

    .evidence_first/
      README.md            # auto-generated; explains the layout
      LOCK                 # PID of the running loop; absent when idle
      index.json           # entry point: last round, current R, convergence, pending human queue
      ledger.jsonl         # append-only evidence trail (one JSON object per line)
      backlog.json         # ranked next-round backlog
      rounds/
        round_0001.md      # human/agent-readable report
        round_0001.json    # machine-readable report
        round_0001.logs.txt  # raw logs triaged this round

The agent's first move in a fresh session is `cat .evidence_first/index.json`,
then `.evidence_first/rounds/round_NNNN.md` for detail. Add `.evidence_first/`
to `.gitignore` — it is audit state, not source. The `LOCK` file fails the loop
closed if another run holds the workspace; delete it only if the owning PID is dead.

Scratch code (exploratory snippets, throwaway tests) still goes to `/tmp` per
the rule above. The workspace holds *decisions and their evidence*, not scratch.