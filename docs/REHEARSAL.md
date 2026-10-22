# Demo rehearsal

The script for the rehearsal of the demo in chapter 21, with the changes of chapters 25.7 and 26.6, and (section 8) the second rehearsal: the walk-through of the pilot features of chapter 27. The demo half of the hour (minutes 0 to 30) must run in 25 minutes, with 5 minutes to spare (chapter 25.7). The engineer runs the rehearsal and fills the blank "measured" columns. The stage 16 build report entry records the measured totals.

## 1. Before the rehearsal

Run the pre-flight script. It automates the machine-checkable items of the chapter 21.1 checklist and prints a pass, warn, and fail table.

```bash
scripts/demo_preflight.sh               # the full run, with make test
scripts/demo_preflight.sh --skip-tests  # the quick run, 30 minutes before the session
```

| Item of chapter 21.1 | How it is checked | Measured (night before) | Measured (30 minutes before) |
| --- | --- | --- | --- |
| `make test` passes | the script (skipped with `--skip-tests`) | | |
| `keel doctor`: Python, models, index, key, clock, disk | the script | | |
| Free disk above 2 GB | the script | | |
| `keel serve` runs, `/api/health` answers | the script (it starts the service when nothing answers) | | |
| `/api/ready` is ready with the index version of `index/current` | the script | | |
| `keel warm-cache` holds 28 entries | the script (reports "pending stage 15" until the command exists) | | |
| `demo/recording.mp4` and `demo/static/` exist | the script (warnings when absent); play and open them by hand | | |
| The 3 example questions run live, every citation read once | by hand | | |
| The offline drill works with the provider host blocked | by hand (drill D-1 below) | | |
| The 3 answers are printed | by hand | | |
| `caffeinate -dims` runs, power connected | by hand | | |
| Other applications closed, notifications muted, browser zoom 125% | by hand | | |
| Hotspot on standby and tested once | by hand | | |
| Request ID of the last live answer on a sticky note | by hand | | |

## 2. Timing of the demo half

The spec minutes come from the narrative in chapter 21.2 with the change of chapter 25.7: the trace drawer opens at minute 10 to 12 on the answer to example question 1, and the architecture walk gives up 2 minutes for it. The target column fits the same order into 25 minutes. Run the rehearsal with a visible timer and write the elapsed minutes per segment.

| # | Segment | Spec minutes (21.2, 25.7) | Spec length | Target length | Target end | Measured run 1 | Measured run 2 | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | The problem: 4 analyst hours for a 3-company risk comparison | 0 to 3 | 3 | 2 | 2 | | | |
| 2 | The architecture: every step before the 1 call, none an LLM call | 3 to 5 | 2 | 2 | 4 | | | |
| 3 | The live question: example question 1, entities line, retrieval panel, streamed answer, 2 citations and the SEC link; the steps light up as the events arrive (25.8, 1 sentence) | 5 to 10 | 5 | 5 | 9 | | | |
| 4 | The trace drawer on the same answer: quota fills, prompt hash, `model requests: 1` (25.1, 25.7) | 10 to 12 | 2 | 2 | 11 | | | |
| 5 | How the context grounds the answer: coverage statement, JPM gap, fiscal label of a chunk, audit record by request ID | 12 to 17 | 5 | 3 | 14 | | | |
| 6 | The second question: example question 2, the NVIDIA fiscal year that ends in January; a live panel question fits here | 17 to 20 | 3 | 3 | 17 | | | |
| 7 | Value: table 2.4.2, cost per question under $0.10, the low case | 20 to 24 | 4 | 3 | 20 | | | |
| 8 | Future state: the roadmap of chapter 22 and which phases keep the single call | 24 to 27 | 3 | 2 | 22 | | | |
| 9 | Questions: invite them, answers in 21.5 | 27 to 30 | 3 | 3 | 25 | | | |
| | Total | 0 to 30 | 30 | 25 | | | | |
| | Spare | | | 5 | | | | |

Pass rule: the total of a run is 25 minutes or less. A segment more than 1 minute over its target gets a cut line written next to it before the next run.

## 3. The discussion half

These items sit after minute 30 on purpose, as the material the panel asks for (chapters 25.7 and 26.6). Rehearse each one on its own; they do not count toward the 25 minutes.

| Minute | Item | Source | Target length | Measured | Notes |
| --- | --- | --- | --- | --- | --- |
| 32 to 38 | The `/api/eval` page: recall per question, ablations, latency and cost, end on the prompt log versions | 25.2, 25.7 | 6 | | |
| 38 to 46 | Live EDGAR: the `keel add` log from the night before, the 2 new companies in the coverage chips, 1 question about one of them, the NVIDIA numeric question with the drawer on the facts lines | 26.6 | 8 | | |
| 44 to 46 | The deliberate failure: the G-27 preset, say what must happen before it streams, then the drift count in the drawer | 25.4, 25.7 | 2 | | |
| any | Pushback drills, 1 run through every row of `docs/PUSHBACK.md` (stage 15) | 25.5 | | | |

The minute 44 to 46 failure sits inside the minute 38 to 46 EDGAR block in the chapters. In the rehearsal, run the EDGAR block first and the failure at its end, so the failure opens the open discussion as chapter 25.7 says.

## 4. Failure drills

Run every drill once in the rehearsal. The "how to stage it" column triggers the failure without touching the index or the corpus. The scripts are those of chapter 21.4.

| ID | Failure | How to stage it in the rehearsal | Detection on stage | Script (chapter 21.4) | Recovery target | Measured recovery | Pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D-1 | The provider returns an error or times out | Block the provider host for 1 question (an `/etc/hosts` entry for the API host, removed afterwards), `KEEL_OFFLINE` unset | The red banner and the degraded mode with chunks | Name the degraded mode of chapter 16. Click Retry once. Then run the question with `KEEL_OFFLINE=1`: the cached answer came from the same pipeline on the same index. | 1 minute | | |
| D-2 | The venue network has no internet | Turn Wi-Fi off | The browser offline banner, or the connect error | Switch to the hotspot. If it fails, `KEEL_OFFLINE=1`, restart with `make demo`, run the example questions from the cache. The cache key holds the index, the prompt, and the model versions. | 2 minutes | | |
| D-3 | The service does not start | Hold port 8000 with another process (`python3 -m http.server 8000`), then `make demo` | The terminal error, or the port message | Read the port message; `make demo` picks the next free port. If the index check fails, show the printed answers and open `demo/static/`. | 1 minute | | |
| D-4 | The index is absent or corrupt | `KEEL_INDEX__DIR` pointed at an empty directory for 1 run of `keel serve` (never delete the real index) | The full-page card | The build takes 27 minutes, so continue with the static export and the recording. Start `keel index` in the background anyway. | 1 minute | | |
| D-5 | The laptop sleeps or restarts | `pmset sleepnow`, then wake | A black screen | Wake, run `make demo`, continue from the request ID on the sticky note with the stored result. | 2 minutes | | |
| D-6 | A live panel question is out of scope | Ask about a well-known company outside the corpus | The gray out-of-scope card | This is the design: the system refuses without a model call and shows the covered companies. Ask for a covered company. | 30 seconds | | |
| D-7 | A live panel question hits a thin company | Ask a trend question about a company with 1 10-K | The yellow partial-coverage banner | Point at the gaps list and the coverage statement. The limit is in the corpus; the roadmap adds live EDGAR. | 30 seconds | | |
| D-8 | The model gives a weak answer | The G-27 preset (the deliberate failure of 25.4) | A finding marked unverified, a drift count above 0 | The server removed a citation that did not match the context. Show the drift count in the audit record. The eval gate measures this rate. | 1 minute | | |

The recovery target is the time from the failure on screen to the demo back on its script. It is a rehearsal aim, not a figure from the chapters. After the drills, run `scripts/demo_preflight.sh --skip-tests` again to confirm the setup is back to normal (hosts file, Wi-Fi, port, index pointer).

## 5. Cold-read rehearsal

Chapter 25.6: clone the repository into a new directory, open nothing in advance, and walk the modules in pipeline order against a 20-minute timer with `docs/CODE_WALK.md` (stage 15). Do it once the day before and once on the day, before the demo. A module that takes more than 3 minutes to explain gets split before the demo.

| Module | Day before (minutes) | Day of (minutes) | Over 3 minutes? |
| --- | --- | --- | --- |
| `keel/extractor.py`, `keel/inventory.py` | | | |
| `keel/parsers/` | | | |
| `keel/sections.py` | | | |
| `keel/chunker.py`, `keel/tables.py` | | | |
| `keel/indexer.py`, `keel/stores/` | | | |
| `keel/understanding.py` | | | |
| `keel/retriever.py` | | | |
| `keel/context.py`, `keel/prompt.py` | | | |
| `keel/providers/`, `keel/answer.py` | | | |
| `keel/citations.py` | | | |
| `keel/cache.py`, `keel/audit.py`, `keel/reliability.py` | | | |
| `keel/api/` | | | |
| `web/src/` | | | |
| Total (20 minutes or less) | | | |

## 6. Recording checklist

The recording and the static export are the fallbacks of drills D-3 and D-4 (chapter 16.12, step 4). `demo/recording.mp4` is in `.gitignore`, so it travels with the laptop and the hand-off package, not the repository.

- [ ] Record after `keel warm-cache` and a pre-flight with no failure, so the recording shows the index, prompt, and model versions of the demo.
- [ ] Record a full run of the 3 example questions in the browser at 125% zoom, with the pipeline steps, the streamed answer, 2 opened citations, and the trace drawer.
- [ ] Nothing secret on screen: no terminal with the environment, no developer tools with the bearer token, no settings page.
- [ ] Notifications muted and other applications closed before the recording starts.
- [ ] Save as `demo/recording.mp4`, play it end to end once, and check that the sound is off or clean.
- [ ] Export the 3 answers as static HTML in `demo/static/`, open each file with the network off, and check that the citations and the coverage statement render.
- [ ] Print the 3 answers for a total failure of the laptop.
- [ ] Run `scripts/demo_preflight.sh --skip-tests` and confirm the recording and static export rows pass.
- [ ] Record again after any change to the index version, the prompt version, or the model snapshot.

## 7. Rehearsal log

| Date | Run | Total minutes | Over target | Drills run | Changes made after the run |
| --- | --- | --- | --- | --- | --- |
| | 1 | | | | |
| | 2 | | | | |

## 8. Second rehearsal: the pilot walk-through

The second rehearsal walks the pilot features of chapter 27 in the order a pilot user meets them in `docs/START_GUIDE.md`, then the week 0 steps of chapter 27.6. Run it on the pilot host after the deploy, or on the laptop against a scratch logs folder so the rehearsal leaves no record in the real audit log:

```bash
export KEEL_LOGS__DIR="$(mktemp -d)/logs"    # audit, pilot store, refresh log, watch list
export KEEL_AUTH__USERS_FILE="$KEEL_LOGS__DIR/users.yaml"
uv run keel serve                           # live provider; KEEL_LLM__PROVIDER=mock for a free run
```

On the laptop, run P-12 and P-13 with `--corpus` and `--out` on a scratch copy of `corpus/edgar` and of the index, as stage 14 did, and pass that copy's manifest to `pilot_metrics.py --manifest`: `keel add` writes corpus files, a new index build, and an entry in `config/companies.yaml` (revert that entry afterwards). Each step names the command or the page and the result that passes. A step that fails gets a fix and a note in the log of section 7 before the pilot starts.

| # | Feature (27.2) | Step | Passes when | Measured | Pass |
| --- | --- | --- | --- | --- | --- |
| P-1 | Users and tokens | `keel users add ana --role analyst`, `keel users add pat --role partner`, `keel users add eng --role admin`; `keel users list` | Each add prints a token once; the users file holds 3 `sha256:` hashes and no token | | |
| P-2 | Users and tokens | Sign in as ana in 1 browser and as pat in a private window; then a wrong token | Both see the question page; the wrong token shows **Token rejected** | | |
| P-3 | Ask, audit | ana asks example question 1; pat asks example question 2 | Each answer streams with `model requests: 1` in the trace drawer; the audit lines carry `user_name` ana and pat | | |
| P-4 | History | **History** as ana, then as pat; `scope=all` as eng (`GET /api/history?scope=all`) | Each user sees only their own question; the admin sees both | | |
| P-5 | Share links | ana clicks **Copy link**; pat opens it | pat sees the answer read-only, without the asker's name; a made-up request ID shows "no longer stored" | | |
| P-6 | Re-run | pat clicks **Re-run** on the history page | The question box is prefilled and nothing is sent until **Ask** | | |
| P-7 | Comp sets | **Comp sets**: save `software` with MSFT ORCL CRM ADBE ZTS; ask "How do the risk factors of my software comps compare?" | The entities line names the comp set; ZTS shows in the gaps as "(comp set, not in the corpus)" until P-12 adds it | | |
| P-8 | Comp sets | pat edits ana's set | 403: only the owner and the admins change a set | | |
| P-9 | Templates | Pick **Risk benchmark**, fill AAPL MSFT and fiscal 2025, click **Fill** | The box holds the filled question; no request until **Ask** | | |
| P-10 | Feedback | ana votes thumbs up on P-3; pat votes thumbs down with a note; `keel feedback --flagged` | 2 rows in the `feedback` table; the flagged list holds pat's vote with the question | | |
| P-11 | Memo export | `keel export <request ID of P-3> --format docx` and `--format markdown`; `GET /api/export/<request ID>?format=docx` with ana's token | Both files open with numbered sources and `www.sec.gov` links; the route returns the DOCX | | |
| P-12 | keel add | `keel add ZTS` (or the firm's ticker outside the corpus); ask a question about it; ask P-7 again | A new index version; the answer cites the added 10-K; the comp set question answers on ZTS too | | |
| P-13 | Watch list and refresh | `keel watch add AAPL`, `keel refresh --dry-run`, then `keel refresh` | The dry run lists each watched and added ticker; `refresh.log` holds the run; a new filing, if any, is added | | |
| P-14 | Pilot metrics | `uv run python scripts/pilot_metrics.py --exclude-user eng --exclude-user legacy --manifest <scratch corpus>/manifest.json` | The weekly row shows 2 active users (ana, pat), their questions and cost, a thumbs-up rate of 50%, the companies of P-12, and 3 memos exported (the 2 `cli` exports and ana's route export of P-11) | | |
| P-15 | Revoke | `keel users remove pat`; pat asks again | 401 on the next request, with no restart | | |
| P-16 | Data use | Read section 7 of `docs/START_GUIDE.md` against the provider's current commercial terms | The terms still say API data is not used for training; the check date is written in the log of section 7 | | |

Week 0 of chapter 27.6 on the pilot host, after the walk-through passes:

- [ ] Deploy (stage 21) and run `keel doctor` and `scripts/demo_preflight.sh --skip-tests` on the host.
- [ ] `keel users add` for the 5 users (2 associates, 2 analysts as `analyst`, 1 `partner`) and 1 `admin` for the engineer; hand each token over in person or through the password manager.
- [ ] Load the firm's comp sets (`keel compsets add NAME TICKER...`) and the watch list (`keel watch add TICKER` for the portfolio and the 2 live deals).
- [ ] `keel add TICKER` for every ticker of the comp sets and the watch list outside the corpus.
- [ ] Run the golden set (`keel eval --answers`) and write the performance memo with the measured numbers (stage 15).
- [ ] Send `docs/START_GUIDE.md` with the pilot address; write the pilot start date for `pilot_metrics.py --since`.
- [ ] Each week: `keel feedback --flagged`, the golden questions from the flagged answers, `scripts/pilot_metrics.py --since <start> --exclude-user eng --exclude-user legacy` (the terminal runs and the shared token write `legacy`) (the memos come from the export log).
