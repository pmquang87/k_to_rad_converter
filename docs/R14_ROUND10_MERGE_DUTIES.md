# R14 campaign parity round 10 - MERGE DUTIES (report section 0.37) - chip prompt

Written by the round-10 coordinator (session r14-round10-05682a, 2026-11-07); corrected in place by the
verification round (findings 6.29 (3), 6.30 (3)(b), 6.31 (2)(g)): every fact below is current, nothing is
overridden further down. The session that runs the duties measures everything itself.

PR: #148 (branch `claude/r14-round10-05682a`, base master `b17c298` = `ed52c93` + PR #146 (docs) + PR #147
(CODE), merged into the branch as `e512676` with the user's permission; `ed52c93` is the round's start and the
campaign's `_meta` baseline, not the PR's base). The PR head is NOT named here: read it with `gh pr view 148
--repo pmquang87/k_to_rad_converter --json headRefOid`. The last code commit of the PR is
`218b06aeeb35f5ecb2a4e331dbc960b3b8713188` (measured: `git diff 218b06a..<head> -- k2rad tools k2rad.py
k2rad_gui.py` empty). The round-10 campaign passes on the branch: report section 0.36 (branch `ab53752`:
238 keys / 205 models moved, 169 / 147 by bytes, 158 runnable byte movers re-run, the ledger normal 300 -> 302
/ error_engine 23 -> 21 / match 34 -> 35 / deviation 144 -> 145 / not_comparable 188 -> 186, implicit residue
24 / 24), section 0.36.1 (branch `4579f60`, the fix round: 0 byte movers, 25 warning-only movers re-converted,
the ledger unchanged) and section 0.36.2 (the verification round: 0 byte movers, 37 warning-only movers on 32 models re-converted at `0d3a4e1` (RECONVERTED, not re-run), the ledger unchanged, the rows naming the branch 243).

## Role and the standing rules

You run the merge duties of the round-10 PR after the USER has merged it on GitHub. You convert the campaign's
round-10 rows to the merge commit's bytes, re-baseline `_meta.k2rad_sha`, publish section 0.37, update the memories
and file the lessons. Rules (the user's, unchanged since round 9): never merge or rebase anything yourself; never
`--allow-giants`; `F:\dynaexamples_r14_ton-mm-s` is READ-ONLY; `db.json` only through db_io / convert_all / run_queue
/ reset_deck; every figure measured, nothing typed in (a figure carried across a context compaction is typed in until
re-measured); stop at the FIRST deviation from this checklist and report; sub-agents (Opus, max effort) and the
Workflow tool for fan-out, no session chips; do not touch the user's main checkout
`C:\Users\pmqua\PycharmProjects\k_to_rad_converter` (read-only: its state is MEASURED, never assumed) nor any other
worktree; commit nothing (the duties write only the campaign mirror, the memories and the lessons files).

## READ FIRST, in order

1. `C:\Users\pmqua\.claude\MISTAKES.md` (agents & workflow, running OpenRadioss, evidence sections) and
   `C:\Users\pmqua\PycharmProjects\k_to_rad_converter\PROJECT_MISTAKES.md` (gitignored; the campaign section's
   2026-11-01 entries tagged `k2rad #144 merge` = the 0.35 lessons, and the `k2rad round 10` entries).
2. The memory `k2rad-parity-roadmap-2026-07.md` (line 48 = the round-10 record; its END is the newest state) and
   `dynaexamples-r14-computed-collection.md` (the LAST paragraphs = 0.35, then 0.36 with 0.36.1, then 0.36.2).
3. `C:\dynaexamples_r14_ton-mm-s_openradioss\OPENRADIOSS_REPORT.md` sections 0.34 (the round-9 merge re-baseline),
   0.35 (the CardStack re-baseline: the FIRST merge whose batch moved roster bytes - its order is this checklist's
   when D0 = 0) and 0.36, 0.36.1 and 0.36.2 (the round-10 pass, its fix round and its verification round);
   `README.md` sections 7-10 (section 7's C6 paragraph "Rows that name
   another branch" is re-measured in place at every merge re-baseline).
4. The durable archive of the round-10 session: `C:\Users\pmqua\rcv_r14_round10_session_2026-11-01\scratchpad\`
   with the 15 templates of the 0.35 duties (the scratchpad they came from is NOT durable):
   `merge_params_11.py`, `run_gates_r10.py`, `launch_sweep_r10.ps1`, `census_movers_r10.py`,
   `second_scanner_11.py`, `pass_prepare_r10.py`, `pass_convert_r10.py`, `pass_after_r10.py`,
   `probe_plates_tied_r10.py`, `rebaseline_meta_11.py`, `publish_groups_11.py`, `publish_035.py`,
   `update_memory_11.py`, `file_lessons_11.py`, `cleanup_11.ps1`; the 0.34 templates under `prev11\`
   (`refresh_logs_10.py`, `repoint_notes_10.py` = the branch-row re-stamp and the note re-point of a round merge);
   the decision doc `r14_round10_coordinator_findings.md` (its 6.10 / 6.11 are the merge rules); the campaign spec
   `r10\campaign_spec_r10.md` section C5 (the EXACT line-by-line re-pointing of each template, written by the
   round-10 research agent).
5. The PR body (`gh pr view 148 --repo pmquang87/k_to_rad_converter --json body`) and the 0.36 section:
   the mover census per item, the measured ledger, the A10 gate outcome, the named costs.

## The checklist (0.37), in order - each step measured, each result read back

0. MEASURE THE STATE. `gh pr view 148 --json state,mergeCommit,mergedAt,headRefOid` -> M10 = the merge
   commit, the merge time; `git ls-remote origin master` must equal M10 (if a later commit sits above M10, the
   baseline target is master's head and the k2rad package identity across M10 and that head is asserted exactly as
   0.35 asserted it across e0e0ef9 and ed52c93). Assert the k2rad package identity: `git diff --stat <PR head> M10
   -- k2rad tools k2rad.py k2rad_gui.py` EMPTY. Against `fba6afd` or `ed52c93` the same diff is NOT empty (PR
   #147's code and round 10's): do not run it against them. If a commit above M10 exists, the identity is
   asserted across M10 and that head as well. D0 = the number of db.json rows whose `conversion.k2rad_branch`
   is `claude/r14-round10-05682a` (read a COPY of db.json; measured after the PR's last campaign pass: 243, the
   stamps `ab53752` x192 + `4579f60` x14 + `0d3a4e1` x37 - section 0.36.2; D0 > 0 -> PATTERN P34 below; D0 = 0 -> PATTERN P35 = the whole 0.35
   order). The main checkout's state from
   `git -C <main> reflog show master --date=iso -5` and `rev-parse HEAD` (pulled to M10 or not; its MEASURED
   untracked set from `git status --porcelain` - never a remembered count). The runner IDLE (`_infra/current.txt`,
   runner.pid's PID not alive by Get-CimInstance). db.json md5 recorded. Nothing else runs on the machine.
1. PARAMETERS: copy `merge_params_11.py` -> `merge_params_12.py` in your scratchpad: OLD = ed52c93 (the 0.35
   baseline), NEW = M10 (or master's head), the PR number, the merge time, the batch sha = the PR head, section
   "0.37", tag p13, arm `sw_p13_<M10 7>`, the backup folder `campaign_backup_r13`, note history 7 -> 8, the main
   checkout's measured state. Run it; every fact in its JSON is measured by it.
2. THE BASELINE TREE: a NEW pristine clone `C:\Users\pmqua\PycharmProjects\k2rad-clone-pristine13` =
   `git clone --branch master` of origin at NEW (assert `HEAD == origin/master == NEW`; `git status --porcelain
   --ignored` empty; PYTHONDONTWRITEBYTECODE=1 in every process that imports it). The 0.35 clone `pristine12`
   (ed52c93) stays until cleanup. If the main checkout IS pulled to NEW, it is the re-stamp tree of step 7 (the
   `_meta` gate ON); it is never the sweep's tree.
3. GATES on the clone (`run_gates_r10.py` re-pointed): pytest tests/ (count >= the PR's final count; the baseline
   at ed52c93 was 6795 / 2 / 23238), mypy 0 in the dev venv AND --no-site-packages, ruff clean, `--help` renders;
   porcelain --ignored empty after.
4. THE SWEEP (`launch_sweep_r10.ps1` re-pointed; `-Keep`): all 356 roster keys converted from F: at NEW through
   `verify_warnings.py sweep --tree <clone13> --arm sw_p13_<NEW7> --baseline NEW --keep <dir>`, then
   `verify_warnings.py check --records <sweep> --baseline NEW`. PATTERN P34 (D0 > 0): the round-10 rows were
   converted at several branch commits (`ab53752` x192 + `4579f60` x14 + `0d3a4e1` x37); the stamps are valid because a fresh sweep of the
   PR head reproduces every row's bytes and warning record (check FAIL 0 / WARN 5 / OK 351: the coordinator and
   the evidence verifier at bc2910c, the verification round at its last code commit), so BYTES_DIFFER must be 0
   on them. NOT_ANCESTOR must be 0 ONLY IF the user merged with a MERGE COMMIT (as PR #143 and #144 were): after
   a squash or a rebase merge the branch shas are not ancestors of master, the check then reports NOT_ANCESTOR on
   all D0 rows until step 7 re-stamps them - expected, not a deviation; the package identity of step 0 decides.
   The only FAIL rows allowed besides are rows no pass re-converted although their bytes or warning records
   move (there should be none - if the census finds any, they are movers a pass missed: a finding for the
   record, then the P35 steps 5-6 for exactly those rows); NOTE_SHA_STALE / NOTE_STALE on the branch rows are expected until step 7. Census the FAIL rows with
   `census_movers_r10.py` (the block classifier; print every unlabelled hunk).
5. (only if step 4 found uncovered byte movers) `pass_prepare_r10.py` / `pass_convert_r10.py` / `pass_after_r10.py`
   re-pointed: reset the runnable ones, convert ALL uncovered movers from the clone (`--tree`), run the runnable
   ones through `run_queue.py --pass 1 --only-file --redo` (giants never), the status-mover probes with the OLD
   bytes beside the new, the driven-body check, check FAIL 0.
6. CHECK BEFORE THE WRITE: `verify_warnings.py check` FAIL 0 (WARN = the 5 STALE_RUN giants only), `verify_runs.py`
   PROBLEMS 0, `xcheck_counts.py` exit 0, `rescore_benchmark.py --dry-run` 0 / 0 / 0 / 0 / 0.
7. `_meta` LAST, THEN THE RE-STAMP (`rebaseline_meta_11.py` re-pointed, then the 0.34 pattern's
   `refresh_logs_10.py` + `repoint_notes_10.py`): (a) the backup of db.json + status.csv to `campaign_backup_r13`
   AND to `_infra/backup/db_before_rebaseline_<NEW7>_<stamp>.json` (+ the status csv); (b) through
   `db_io.save_db_and_ledger(db, {db_io.META: ()})` with the runner idle: `_meta.k2rad_sha` = NEW, `k2rad_branch`
   master, the note (the measurement above; the main-checkout clause from the BRANCH reflog at write time; the
   ledger before -> after; the provenance rule; "section 0.37"), the previous note displaced into the EIGHTH
   `k2rad_sha_note_history` entry; deck rows byte-equal on read-back; status.csv byte-identical; (c) the D0 branch
   rows re-stamped to NEW / master: from the pulled main checkout (gate ON) if the user pulled, else
   `convert_all.py --tree <clone13> --only-file <the D0 keys> --redo` (TRANSITIONS: RECONVERTED x D0 minus the
   refused rows' REFUSAL UNCHANGED); every re-stamped mirror `.rad` SHA256-equal to the sweep's fresh digest (bytes
   must not move: the package is identical - a moved byte here is a STOP); the note re-point of rows whose notes
   embed the branch sha; (d) `verify_warnings.py check` after: FAIL 0 / WARN 5, NOTE_STALE 0, NOTE_SHA_STALE 0,
   NOT_ANCESTOR 0; `convert_all.py --dry-run --limit 1` from the clone (exit 0) and from the main checkout (exit 0 if
   pulled to NEW, a FATAL if not - record which).
8. THE GROUPING: `publish_groups_11.py` re-pointed: `model_groups.py mirror` -> scratch, `compare` against the
   published pair (SHRANK / GREW recorded - a default that moves one sibling of a collision group splits the group:
   a finding, not a stop), then `mirror --publish`; the second scanner (`second_scanner_11.py`) over the sweep's
   `_0000.rad` digests must agree (356 keys -> the same model count; the movers on the same models).
9. SECTION 0.37 (`publish_035.py` re-pointed to 0.37): inserted before '## 1. Errors first'; the 0.36 section gets
   its "done at the merge" marker; README section 10 gets the changelog line; README section 7's C6 paragraph
   re-measured in place (0 rows on an unmerged branch - the round-10 branch is merged; N on older merged branches;
   master; no branch field; the sum = 373); the model-count sentence re-dated to NEW; the 0.35 label lesson: the
   RECONVERTED / REFUSAL UNCHANGED counts in the README line come from the conversion log, never from the mover
   count. The section records: the merge facts from `gh`, the package identity across the PR head and M10 (never fba6afd: PR #147's code
   sits between),
   D0 and the pattern used, the sweep (two halves), the census of FAIL rows (expected 0 bytes), the re-stamp with its
   SHA proof, the `_meta` table (before / after), the checks, the provenance table, the branch census, the ledger
   (unchanged by a re-baseline unless step 5 ran), the k2rad gates on the clone, the cleanup, the drift (the skill
   launcher vs `_infra/run_or.ps1` md5s - re-synced by round 10's C1: assert equal now), "not done here".
10. MEMORIES AND LESSONS (`update_memory_11.py`, `file_lessons_11.py` re-pointed): the roadmap memory's line 48
    END gets "PR #148 MERGED <time> as M10; re-baselined 0.37 <date>" (the newest record is the END of the
    line); `dynaexamples-r14-computed-collection.md` appended (0.37); `project_k2rad.md` STATUS; MEMORY.md hooks;
    lessons by scope (project: `PROJECT_MISTAKES.md` by absolute path, tag `k2rad #148 merge`; global:
    cross-project traps only).
11. CLEANUP (`cleanup_11.ps1` re-pointed, `-Write -RemoveClone`): the sweep keep dir (about 1 GB) and the empty
    sweep root removed; `pristine12` AND `pristine13` removed (porcelain empty and HEAD read back first); the
    round-10 worktree `.claude/worktrees/r14-round10-05682a` is the user's to remove (merged branch); the session's
    scratchpad archived to a durable folder `C:\Users\pmqua\rcv_r14_round10_merge_<date>\` with every script and
    result (the archive is the next round's template source).
12. REPORT to the user: the merge facts, D0 and the pattern, the sweep's FAIL / WARN / OK before and after, the
    `_meta` md5s, the grouping, the section number, the memories and lessons written, what was NOT done and why.

## What round 10 leaves for the merge duties specifically (from the decision doc and the 0.36 section)

- D0 = the rows that name the branch: MEASURED 243 after the verification round's pass (`ab53752` x192 + `4579f60` x14 + `0d3a4e1` x37;
  section 0.36.2). Read it from a db.json copy - never type in 234, 238 or 240.
- STALE_RUN 5 (2Dlag, ale_wavehitcol, intermediate-fsi-2-flaps, the Yaris roof crush, the Yaris door sag) stays;
  the 8 giant byte movers were converted + starter-only in 0.36 (their runs stay stale or pending; never launched).
- The implicit residue 24 / 24 and the ledger measured in 0.36 (normal 302 / error_engine 21 / match 35 /
  deviation 145 / not_comparable 186), unchanged by 0.36.1 and 0.36.2 - read the current one.
- The skill launcher and `_infra/run_or.ps1` + `_infra/audit_or_run.py` were re-synced by C1 (md5 d22c3eee /
  9f99fb99 at the time); assert they still match the skill's files at the merge (the skill may have moved again).
- origin/master `b17c298` is merged into the branch (`e512676`). If master moved beyond `b17c298` before the user's
  merge, M10 carries those commits too: assert the package identity across the PR head and M10 and name every
  extra commit in 0.37.
- The campaign README's `_infra/audit_or_run.py` row in section 8's runner table (line 772 on 2026-11-12)
  still gives the strict-gate census of the round's start ('42 of the 300 normal rows', on the 0.35 listings, report
  section 0.36), while section 8's 'Solver launch rules' paragraph gives the census after the round-10 re-runs
  (report section 0.36.2): restate the row, or point it at that paragraph, in the 0.37 pass (measure the census
  again; never copy it).

## Facts measured by the fix-and-PR agent and the verification round (2026-11-12) - the record

- **Master and the merge.** origin/master is `b17c298` (PR #146 docs + PR #147 CODE: `k2rad/handlers.py`,
  `k2rad/writer/contacts.py`), merged into the branch as `e512676` with the user's permission (findings 6.19a);
  step 0 says what the identity check compares.
- **D0 and its stamps**: 243 rows (`ab53752` x192 + `4579f60` x14 + `0d3a4e1` x37) after section 0.36.2; 238 after 0.36, 240 after 0.36.1.
- **The fix round moved warning text only** (report section 0.36.1): 0 byte movers on the 356 roster keys
  between `ab53752` and `7a63e1d`; 25 keys / 23 models warning-record movers re-converted (RECONVERTED, not
  re-run); the ledger did not move. **The verification round** (section 0.36.2) moved warning text only too: 0 byte movers, 37 warning-only movers on 32 models re-converted at `0d3a4e1` (RECONVERTED, not re-run), the ledger unchanged, the rows naming the branch 243.
- **PR #147's own column** (`ed52c93` -> `b17c298`): 0 byte movers on the roster, 0 roster warning records (15
  warning-record movers outside the roster: the CardStack archive 10, Ryan_Lee 5) - report it in its own column,
  never inside a round-10 item.
- **Bands (findings 6.28 (4)) - a MERGE DUTY:** run THREE more eps twins per carrier with
  `_infra/perturbation_band.py` (Ashear `1` -> `1.000001`, nt 4, ALONE, recorded with `--write`) on the four band
  carriers (ring_01, ring_1, ring_100, airbag-ii's airbag.deploy) AND on constrained.spotweld.plates as the
  zero-band control; state the union band in 0.37. No repo text depends on the outcome (the shipped sentence says
  what one twin covers and what it does not).
- **4.2's `42_union` annotation:** its 7 runs span KE END +191.6 .. +2337.8 %; the campaign validator's 6 runs of the
  `ed52c93` bytes reach +1542.96 .. +2732.45 % - restate the union with the wider spread at 0.37.
- **The Yaris suspension starters** print ERROR 179 (PART 2000970 'hexa spotwelds', the expected stop) and then
  grow past 16 000 MB private within 20 - 25 s, at nt 4 AND at nt 1: never start them without an in-run memory
  cap polled every 1 s; nt 1 is no fallback. The 6 other moved giants' starters ended with 0 ERROR(S). The giants
  rule stands: never the engine, never `--allow-giants`.
- **The launcher pair** `_infra/run_or.ps1` / `_infra/audit_or_run.py` equalled the skill's (md5 d22c3eee /
  9f99fb99) after C1; assert it again at the merge. Under the strict default the round-10 bytes of
  pan.drawbead.31 end exit 5 (FLAG energy-error-clamped, the one newly flagged roster row; findings 6.27).
- **stagnation_A / _B cycle counts**: the campaign rows record the engine's TOTAL (9365); the implementers' and
  the physics validator's runs quote the last printed cycle (9364). Name the run beside every figure.
- **Follow-ups that are not merge duties** (named so the session does not mistake them for one): the
  campaign scorer's guard against an A5 sliver last row (flag or skip an END row whose increment is below about
  half of the one before - a campaign candidate; the 0.36.2 scan found no scored row below 0.5 today, the
  lowest 0.622); the K-04 cap RE-OPENED for round 11 (ROADMAP); the tests.yml ubuntu skip comment (13 where CI
  shows 14) and the GUI's two-widget cells (rows 10 / 13), both older than round 10.
