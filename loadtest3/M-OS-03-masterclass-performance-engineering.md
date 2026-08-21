# M-OS-03: PostgreSQL Performance Engineering Masterclass
**Track:** 2 (Production DBRE) | **Phase:** extends ProductionDB, positioned after M-OS-02 | **Duration:** 4 hours
**Prerequisites:** M-OS-01 (OS fundamentals), M-OS-02 (OS tuning for Postgres), comfort with `pgbench`, `loadtest.py` v3 (`--cpu-workers`/`--memory-workers`/`--io-workers`/`--mixed-workers`/`--idle-workers`/`--no-fsync`/`--disk-dir`/`--metrics-port` flags)

## What changes here, and what doesn't

M-OS-02 taught *which* sysctl knobs matter and *why*. This module does not
add more knobs. It adds the discipline that separates "I changed something
and it got faster" from "I proved what caused the improvement." Every
experiment in this module follows one fixed shape:

```
Hypothesis → Control runs → Change ONE thing → Repeat runs → Correlate → Prove or disprove → Rollback discipline
```

If a student can't fill in every step of that shape for a change they made
on a real production host, they haven't finished tuning it — they've just
made it faster once, which is a different and much less reliable thing.

---

## Learning Objectives
By the end of this module, students will be able to:
- Write a falsifiable hypothesis before running any tuning experiment, and
  state in advance what evidence would disprove it
- Run a change through baseline → contention → tuned → repeat and use
  variance across repeats to tell signal from noise
- Correlate OS-level timestamps (`Dirty:`, `iostat`, `vmstat`) against
  PostgreSQL-level timestamps (`pgbench` intervals, `pg_stat_*`) to build a
  causal story, not just a coincidence
- Use `perf stat` to distinguish "CPU-bound because of real computation"
  from "CPU-bound because of cache misses or context-switch overhead"
- Use `taskset` and `renice` to demonstrate CPU affinity and scheduling
  priority as tuning levers in their own right
- Distinguish storage throughput from storage latency using `ioping`
  alongside `iostat`
- Run the same experiment across two different mount points/filesystems and
  explain what changed and why
- Capture and roll back every sysctl change with a documented before/after
  diff, and produce a complete Performance Engineering Report

---

## The Production War Story (Hook — 5 min)

A senior DBA once spent a full day convinced that raising `shared_buffers`
had fixed a throughput problem — TPS went from 950 to 1,240 right after the
change, and the team celebrated in Slack. Three days later, at the same time
of day, TPS was back down to 960 with `shared_buffers` still at the new
value. Nothing had been rolled back. What had actually happened: a batch ETL
job that normally ran concurrently with the benchmark window had failed
silently earlier that day and wasn't competing for I/O during the "successful"
test. The `shared_buffers` change did approximately nothing. The missing ETL
job did everything. Without a control group — the same test repeated a few
times under the same conditions — that correlation was invisible, and the
team spent the next sprint tuning a parameter that had already been proven
irrelevant, for the wrong reason, with high confidence.

This module exists so that mistake doesn't happen on your watch.

---

## Concept: Correlation Is Not Causation, Even When You're the One Watching (15 min)

Three failure modes this module is built to prevent, all of which look
identical from inside a single successful test run:

1. **Noise mistaken for signal.** Any single pgbench run has natural
   variance. A 5-8% TPS swing between two runs of the *exact same
   configuration* is normal on most lab VMs. If your "improvement" is inside
   that noise band, you haven't proven anything.
2. **A confound mistaken for the change.** Something else moved between your
   "before" and "after" runs — cache got warm, a background process
   finished, another tenant on the host went quiet. The war story above is
   this failure mode exactly.
3. **A real OS-level change with no PostgreSQL-level effect** (or vice
   versa). If `Dirty:` genuinely dropped after you tuned `vm.dirty_ratio` but
   `pgbench` TPS didn't move, the tuning "worked" at the OS layer but wasn't
   your actual bottleneck — useful to know, easy to misreport as "the fix."

The fix for all three is the same discipline, applied consistently: **run it
more than once, capture the OS metric and the Postgres metric together with
timestamps, and require both to move in the explainable direction before you
credit a change.**

---

## Hands-On Lab

### Part 1 — Hypothesis-driven experiments

Before running *any* experiment in this module, fill in this block. Not
optionally — this is the deliverable, and it's graded on precision, not on
being right.

```
HYPOTHESIS
----------
What do I think will happen?
Why?
What OS metric should change if I'm correct?
What PostgreSQL metric should change if I'm correct?
What result would PROVE ME WRONG?
```

**Worked example**, using the dirty-page-buildup scenario from M-OS-02:

```bash
python3 loadtest.py --duration 120 --cpu-workers 0 --memory-workers 0 \
  --io-workers 2 --mixed-workers 0 --idle-workers 0 --no-fsync
```

```
HYPOTHESIS
----------
What do I think will happen?
  Dirty pages will accumulate because writes aren't fsynced immediately.

Why?
  Buffered writes sit in kernel page cache until vm.dirty_background_ratio
  triggers writeback, or vm.dirty_ratio forces a synchronous flush.

What OS metric should change if I'm correct?
  Dirty: in /proc/meminfo should climb well above its idle baseline.

What PostgreSQL metric should change if I'm correct?
  pgbench per-interval latency (-P 5) should show occasional spikes that
  line up with points where Dirty: was high or just got flushed.

What result would PROVE ME WRONG?
  If Dirty: stays flat despite --no-fsync (would mean something else is
  forcing synchronous writes — worth investigating, not dismissing), OR
  if Dirty: climbs but pgbench latency shows no correlated change (would
  mean dirty pages aren't actually this workload's bottleneck).
```

**Run it, then fill in the result block — not just "it worked":**

```
RESULT
------
Dirty: behavior:              ______________________
pgbench latency behavior:     ______________________
Hypothesis confirmed / refuted / partially confirmed: ______________________
If refuted or partial — what's the next hypothesis?   ______________________
```

Require this exact block — hypothesis, then result — for every experiment
in this module. It's the single highest-leverage habit in the whole course.

---

### Part 2 — Control groups and repeated runs

One run proves nothing. Use this run sequence for every important
experiment, not just the final "prove it" one:

```
Run 1 — CONTROL:    pgbench alone, no contention, no tuning
Run 2 — BASELINE:   pgbench + contention, default sysctl
Run 3 — EXPERIMENT: pgbench + contention + ONE tuning change
Run 4 — REPEAT:     identical to Run 3, run again
Run 5 — REPEAT:     identical to Run 3, run again
```

```bash
# Run 1 — control
pgbench -c 10 -j 2 -T 60 -P 5 bankforge

# Run 2 — baseline (contention, no tuning)
python3 loadtest.py --duration 90 --no-fsync &
sleep 5
pgbench -c 10 -j 2 -T 60 -P 5 bankforge
wait

# Change ONE sysctl
sudo sysctl -w vm.dirty_background_ratio=5
sudo sysctl -w vm.dirty_ratio=10

# Runs 3, 4, 5 — experiment, repeated three times, identical command
for i in 1 2 3; do
  python3 loadtest.py --duration 90 --no-fsync &
  sleep 5
  echo "=== Repeat $i ==="
  pgbench -c 10 -j 2 -T 60 -P 5 bankforge
  wait
done
```

From the three repeat runs, compute:

```
                  Run 3      Run 4      Run 5     |  Avg      Min      Max     StdDev
TPS               ______     ______     ______    |  ______   ______   ______  ______
Latency avg (ms)  ______     ______     ______    |  ______   ______   ______  ______
```

**The teaching point:** if your standard deviation across the three tuned
repeats is comparable to the *difference* between the baseline average and
the tuned average, you have not demonstrated an effect — you've demonstrated
noise. A change is only worth keeping if the tuned average clears the
baseline by more than the tuned runs' own spread.

---

### Part 3 — OS ↔ PostgreSQL timestamp correlation

This is the connective tissue between everything M-OS-01/02 taught
separately. Run contention and pgbench together, log both sides with
timestamps, and line them up by clock time — not by "roughly when."

```bash
# Terminal A — log Dirty: every second with a timestamp
while true; do echo "$(date '+%H:%M:%S') Dirty=$(grep Dirty /proc/meminfo | awk '{print $2}')kB"; sleep 1; done | tee dirty_log.txt

# Terminal B — loadtest
python3 loadtest.py --duration 90 --no-fsync

# Terminal C — pgbench with per-interval reporting (already timestamped by -P)
pgbench -c 10 -j 2 -T 80 -P 5 bankforge | tee pgbench_log.txt
```

Build a table like this from the two logs (this is the deliverable):

```
TIME       DIRTY (MB)    PGBENCH LATENCY (ms)     NOTE
10:31:05   450           12                        normal
10:31:10   620           47                        <- what happened here?
10:31:15   80            13                        dirty pages just flushed
```

**Assessment-style question to pose:** "What happened at 10:31:10?" The
correct reasoning chain: dirty pages crossed a writeback threshold, the
kernel forced a synchronous flush, backends touching those blocks stalled
behind it, and `pgbench` latency spiked in the same window. **This is the
actual skill this whole module exists to build** — reading two independent
timelines and constructing the causal link between them, which is exactly
what a real incident review requires.

---

### Part 4 — perf: is it real computation, or overhead?

`top` tells you *who* is consuming CPU. `perf stat` tells you *what the CPU
is doing while it's busy* — the difference between "genuinely computing" and
"burning cycles on cache misses and context switches."

```bash
# Install if needed
sudo dnf install -y perf

# Find a CPU-bound loadtest PID
python3 loadtest.py --duration 60 --cpu-workers 4 --memory-workers 0 --io-workers 0 --mixed-workers 0 --idle-workers 0 &
sleep 2
ps -ef | grep CPU_FLOAT

# Profile one specific process for 20 seconds
perf stat -p <PID> -- sleep 20
```

**Expected output — key lines to read:**
```
     20,412,558,112      cycles
     38,201,447,903      instructions              #    1.87  insn per cycle
        142,993,201      branches
          1,203,481      branch-misses             #    0.84% of all branches
             48,201      cache-misses
         12,847,220      context-switches
                341      cpu-migrations
                 89      page-faults
```

Two numbers matter most for this exercise:
- **Instructions-per-cycle (IPC)** — near or above 1.0 means the CPU is
  doing real, efficient work most cycles. A low IPC (well under 1.0) with
  high `cache-misses` suggests the process is CPU-bound *on paper* but
  actually stalling waiting for memory, not computing.
- **`context-switches`** — high values relative to runtime indicate the
  scheduler is bouncing this process on and off the CPU frequently
  (consistent with the oversubscription this whole course has been
  demonstrating). Compare this number for the same worker at `--oversub 1.0`
  vs `--oversub 4.0` — it should climb sharply.

```bash
# System-wide view, same idea, whole machine
perf stat -a -- sleep 20
```

**Assessment-style question to pose:** "This workload shows 90% CPU
utilization in `top`. Is it CPU-bound because of actual computation, or
because of cache misses and context switching?" A student who can only
answer with `top` cannot answer this question — `perf stat` is what makes it
answerable.

**Optional, advanced-only:** for teams that want to go one level deeper,
`perf record` + `perf script` + a flame graph generator (e.g.
`FlameGraph` from Brendan Gregg) turns a CPU-bound Postgres backend's stack
samples into a visual flame graph — showing not just that a backend is
CPU-bound, but *which function* inside Postgres is consuming the cycles.
Mention this exists; don't require it in the base module. The one-sentence
version for students: `top` tells you who; `perf` tells you what; a flame
graph tells you exactly where in the code.

---

### Part 5 — CPU affinity with `taskset`

`loadtest.py`'s CPU workers are ideal for this because you can compare the
identical workload confined to different cores.

```bash
# Experiment A — loadtest free to use all cores
python3 loadtest.py --duration 60 --cpu-workers 6 --memory-workers 0 --io-workers 0 --mixed-workers 0 --idle-workers 0 &
pgbench -c 10 -j 2 -T 50 -P 5 bankforge
wait

# Experiment B — same load, confined to cores 0-1 only
taskset -c 0-1 python3 loadtest.py --duration 60 --cpu-workers 6 --memory-workers 0 --io-workers 0 --mixed-workers 0 --idle-workers 0 &
pgbench -c 10 -j 2 -T 50 -P 5 bankforge
wait
```

**Assessment-style question to pose:** "What happens to PostgreSQL's TPS
when the noisy CPU workload is confined to 2 of the box's cores instead of
free to use all of them?" Expect TPS to recover somewhat in Experiment B if
Postgres's own backends can then find free cores — this is the practical
argument for `cpuset`-based isolation of noisy batch/ETL jobs away from a
database's cores in a real shared-host environment, and a first taste of
NUMA-awareness without requiring a NUMA machine to demonstrate the concept.

---

### Part 6 — Scheduling priority with `nice`/`renice`

```bash
# Start the load
python3 loadtest.py --duration 90 --cpu-workers 6 --memory-workers 0 --io-workers 0 --mixed-workers 0 --idle-workers 0 &

# Find PIDs
ps -ef | grep CPU_FLOAT

# Deprioritize them (higher niceness = lower scheduling priority)
for pid in <PID1> <PID2> <PID3>; do
  sudo renice +10 -p $pid
done

# Observe
top          # note the NI column
pidstat -u 1
pgbench -c 10 -j 2 -T 60 -P 5 bankforge
```

**The lesson to state explicitly:** OS scheduling policy is itself a tuning
lever, independent of anything in `postgresql.conf`. A batch job that
`renice`s itself to +15 gets out of Postgres's way under contention without
needing to be paused, rate-limited, or moved to different hardware — and
this is a real, common production pattern for background maintenance jobs
sharing a host with a database.

---

### Part 7 — Throughput vs. latency with `ioping`

`iostat` (from M-OS-01/02) is throughput-and-queue focused. `ioping` answers
a narrower, equally important question: **how long does a single I/O
operation take, right now, independent of how much total throughput the
device is pushing.**

```bash
sudo dnf install -y ioping   # or build from source if not packaged

# Idle baseline
ioping -c 10 .

# Under pgbench alone
pgbench -c 10 -j 2 -T 30 bankforge &
ioping -c 10 .
wait

# Under loadtest contention
python3 loadtest.py --duration 30 --io-workers 2 --cpu-workers 0 --memory-workers 0 --mixed-workers 0 --idle-workers 0 &
ioping -c 10 .
wait
```

**Expected output shape:**
```
4 KiB from . (xfs /dev/mapper/cs-root): request=1 time=1.2 ms
...
--- . (xfs /dev/mapper/cs-root) ioping statistics ---
10 requests completed in 9.87 ms, 40 KiB read, 1.01 k iops, 4.05 MiB/s
min/avg/max/mdev = 0.8 ms / 1.0 ms / 1.4 ms / 0.2 ms
```

**The teaching point, stated directly:** a device can report very high IOPS
in `iostat` while individual operation latency (what `ioping` measures)
degrades badly under load — high throughput and good latency are not the
same claim, and a storage system can satisfy one while failing the other.
This is precisely the nuance from M-OS-01's `%util`-vs-`w_await` discussion,
now demonstrated with a tool built specifically to isolate latency.

---

### Part 8 — Filesystem and mount-point experiments

`loadtest.py` now supports `--disk-dir`, so I/O contention can be pointed at
any writable path — use this to compare behavior across mounts.

```bash
# Inspect what's mounted where first
df -Th
findmnt
lsblk

# Experiment A — default location (root filesystem, wherever /tmp lives)
python3 loadtest.py --duration 60 --io-workers 2 --cpu-workers 0 --memory-workers 0 --mixed-workers 0 --idle-workers 0 --disk-dir /tmp &
iostat -xz 1 10
wait

# Experiment B — a separate mount, if your lab VM has one (e.g. PGDATA's mount)
python3 loadtest.py --duration 60 --io-workers 2 --cpu-workers 0 --memory-workers 0 --mixed-workers 0 --idle-workers 0 --disk-dir /var/lib/pgsql &
iostat -xz 1 10
wait
```

Compare `w_await` and `%util` for the two underlying block devices side by
side (`iostat -xz` reports per-device, so both should show up if the mounts
are on different devices). This is the practical version of the
Postgres-specific chain worth writing on the board:

```
PostgreSQL -> PGDATA -> filesystem -> mount options -> block device -> physical storage
```

Every layer in that chain can independently be the bottleneck, and this
experiment is how you find out which one, on a specific host, rather than
assuming.

---

### Part 9 — Rollback discipline (production-safety habit)

Every sysctl change in this course, from M-OS-02 onward, should follow this
exact pattern from now on — not just at the end of the module:

```bash
# 1. Capture full state BEFORE any change
sysctl -a > sysctl.before.txt 2>/dev/null

# 2. Note the specific values you're about to touch
sysctl vm.dirty_ratio vm.dirty_background_ratio vm.swappiness

# 3. Make ONE change
sudo sysctl -w vm.dirty_ratio=10

# 4. Test

# 5. Roll back to the captured original value
sudo sysctl -w vm.dirty_ratio=<original_value_from_step_2>

# 6. Capture state AFTER rollback and diff against the original
sysctl -a > sysctl.after.txt 2>/dev/null
diff sysctl.before.txt sysctl.after.txt
```

An empty `diff` after rollback is the proof the system is back to its
original state — this is the habit that prevents "temporary" tuning changes
from silently becoming permanent, undocumented production configuration
that nobody remembers making.

---

## Production Gotcha ⚠️

The most dangerous outcome of this entire module is a student who runs one
successful experiment, sees a good number, and stops — skipping the repeat
runs and the "what would prove me wrong" step because the first result
already told them what they wanted to hear. **Confirmation bias is a bigger
threat to correct tuning than any individual sysctl default.** The
discipline in Part 1 and Part 2 exists specifically to catch this, and it
only works if it's applied even when — especially when — the first result
looks great.

## Key Takeaways
- Write the hypothesis, including what would disprove it, before running the experiment — not after.
- One successful run is an anecdote. Three repeated runs with a computed spread is evidence.
- Correlate OS-side and PostgreSQL-side timestamps directly — don't eyeball "around the same time."
- `perf stat` distinguishes real computation from cache-miss/context-switch overhead that `top` can't see.
- `taskset` and `renice` are tuning levers independent of `postgresql.conf`.
- `ioping` measures latency; `iostat` measures throughput+queueing — a device can be good at one and bad at the other.
- Filesystem/mount choice sits between PGDATA and the physical device — test it directly, don't assume.
- Capture, diff, and roll back every sysctl change. An empty diff at the end is your proof of a clean state.

## Assessment Questions
1. Two runs of the same experiment produce TPS of 950 and 1,020. A colleague
   says the change worked. What additional information do you need before
   agreeing, and how would you get it?
2. `perf stat` on a backend shows 85% CPU utilization but IPC of 0.4 and a
   high cache-miss rate. What does this suggest about the nature of the
   bottleneck, and how would this change your tuning approach compared to a
   backend showing 85% CPU with IPC near 2.0?
3. A device shows 12,000 IOPS in `iostat` but `ioping` reports average
   latency has climbed from 1ms to 40ms under the same load. Explain why
   these two facts don't contradict each other.
4. Write a full hypothesis block (all five fields) for an experiment testing
   whether confining `loadtest.py`'s CPU workers to 2 cores via `taskset`
   improves `pgbench` TPS on a 4-core host. Include what result would prove
   you wrong.
5. You changed `vm.swappiness` from 60 to 1 and TPS improved. Your `vmstat`
   log shows `si`/`so` were already at 0 before *and* after the change. Did
   swappiness cause the improvement? If not, what are three other
   explanations, and how would you test each one?

## What's Next
The Masterclass observability layer — wiring `node_exporter`,
`postgres_exporter`, Prometheus, and Grafana into this same lab so every
experiment in this module produces a visual, timestamped, annotated record
instead of scrollback and hand-copied numbers — is covered in the companion
guide **07-grafana-observability-stack.md**. That guide also shows how to
export `loadtest.py`'s own worker configuration (`--metrics-port`) as
Prometheus metrics, so a Grafana dashboard can show what the experiment
*was* directly alongside what it *did*.
