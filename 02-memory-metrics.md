# Memory Analysis: free, vmstat, sar -r, ps --sort=-%mem

## 1. `free -m` — the headline numbers

```
              total   used   free  shared  buff/cache  available
Mem:           3627   1993    180       8        1709       1633
Swap:          7999     13   7986
```

**Read `available`, not `free`.** `free` (180MB) looks alarming in isolation,
but `available` (1633MB) is the number that actually matters — it accounts for
page cache (`buff/cache`, 1709MB here) that the kernel will happily evict under
memory pressure. Linux is *supposed* to use spare RAM for cache; a low `free`
value with a healthy `available` value is normal, not a problem.

**Swap: 13MB used out of 7999MB** — negligible, essentially just what got
paged out at some point and never reclaimed. Consistent with the script review
note that the 600MB of explicit `MEMORY_*` allocations plus ~2GB of GNOME
desktop overhead never got close to exhausting `available` memory.

**PostgreSQL angle:** This is the exact confusion new DBAs have with
`shared_buffers`. Postgres's shared buffer pool shows up as `shared` memory,
and OS-level page cache (which Postgres relies on heavily for reads that miss
shared_buffers) shows up as `buff/cache`. A host with low `free` and high
`buff/cache` is healthy — don't oversize `shared_buffers` just because `free`
looks low.

---

## 2. `vmstat 1` — memory + I/O + CPU in one view, over time

```
r  b  swpd  free   buff  cache    si so    bi     bo    in   cs  us sy id wa
5  1 13396 105652   588 1828900    0  5   755  75577   807  918 17 23 59  1
5  0 13396 143704   588 1791040    0  0     0 472555  3209 3572 43 54  1  3
```

**Columns that matter most for a DB host:**
- `r` — processes runnable (ready for CPU). **Consistently 5-6** here on a
  2-vCPU box — direct numeric confirmation of the CPU contention seen in
  `uptime`/`pidstat`.
- `b` — processes blocked (uninterruptible sleep, i.e. `D` state). Mostly 0,
  briefly 1-2 — matches the `D`-state IO worker caught earlier in `ps`.
- `si`/`so` — swap in/out. **Both effectively zero** — confirms no real
  memory pressure despite the workload running.
- `bo` — blocks written out per second. Jumps from 75,577 to **472,555+**
  once the IO workers hit their steady-state overwrite phase — this is the
  clearest single number showing when disk writes kicked into high gear.
- `wa` — system-wide I/O wait. Stayed **low (1–3%)** even while `bo` was
  huge — worth noting (see the disk I/O doc) because it means the storage
  kept up with demand rather than backing up.

**PostgreSQL angle:** `vmstat 1` run for 30-60 seconds during a slow period is
one of the fastest ways to distinguish "CPU-bound" (`r` high, `wa` low) from
"I/O-bound" (`b` > 0, `wa` high) from "memory-bound" (`si`/`so` > 0) without
touching `pg_stat_activity` at all. Teach students to run this *before*
opening a psql session on a struggling server.

---

## 3. `sar -r 1` — commit ratio and dirty pages

```
kbmemfree  kbavail  kbmemused %memused  kbcached  kbcommit %commit  kbdirty
132060     1673212  1676524    45.13    1704504   4228260   35.51        24
173416     1673060  1676676    45.14    1662996   4228260   35.51         0
```

**`kbcommit`/`%commit`** is the *total memory promised* to all processes
(including overcommitted virtual memory) versus `CommitLimit`
(swap + a fraction of RAM). 35.51% here is comfortable — plenty of headroom
before the kernel would need to start refusing allocations or invoking the
OOM killer.

**`kbdirty`** — pages modified in cache but not yet flushed to disk. Sitting
at **0-24KB, essentially nothing**, even during heavy sustained writes. This
is a direct consequence of the script's `fsync()`-per-1MB design: every write
is forced to disk almost immediately, so dirty pages never get a chance to
accumulate. **This is the memory-side confirmation that the I/O workers are
doing synchronous, not buffered, writes.**

**PostgreSQL angle:** `kbdirty` climbing and staying high is a warning sign of
a checkpoint that's falling behind — dirty pages piling up faster than the
kernel (or Postgres's own bgwriter/checkpointer) can flush them, which
eventually forces a painful synchronous flush. Watching `kbdirty` alongside
Postgres's own `pg_stat_bgwriter.buffers_checkpoint` is a good habit before a
checkpoint-tuning conversation.

---

## 4. `ps --sort=-%mem` — who's actually holding the RAM

```
34015  34010 root  0.6  8.5 315840  S+  python3.9 loadtest.py   <- MEMORY_300MB
2042   1938  root  0.5  8.0 297976  Ssl gnome-shell
34014  34010 root  0.4  5.7 213328  S+  python3.9 loadtest.py   <- MEMORY_200MB
```

**RSS (resident set size) matches expectations almost exactly**: the 300MB
worker shows ~315MB RSS, the 200MB worker ~213MB RSS — the small overhead is
Python interpreter + `bytearray` object overhead. Confirms the "touch every
page" logic in `memory_worker` actually commits physical pages rather than
just reserving virtual address space (which would show large `VSZ` but tiny
`RSS`).

**PostgreSQL angle:** This VSZ-vs-RSS distinction matters directly for
Postgres backends — a backend's `VSZ` includes shared memory mapped from
`shared_buffers` (counted once per backend even though it's physically shared
across all of them), which is why summing `RSS` across all Postgres backends
**overcounts actual memory use**. Use `pmap` or the shared-memory-aware
columns, not a naive sum of `ps` RSS, when sizing total Postgres memory
footprint.

## Summary — what to look at, in order, for a "memory looks full" ticket
1. `free -m` — trust `available`, not `free`.
2. `vmstat 1` — are `si`/`so` non-zero? That's real swap pressure, not cache.
3. `sar -r 1` — is `kbdirty` climbing? Flush/checkpoint may be falling behind.
4. `ps --sort=-%mem` — which process actually holds the RSS, and is it shared (Postgres shared_buffers) or private?
