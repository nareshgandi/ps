# loadtest.py — Code Review

## Purpose
Generates a mixed, oversubscribed workload (10 processes on a 2-vCPU lab VM) so
students can watch `top`, `vmstat`, `iostat`, and `pidstat` under real contention
before mapping those symptoms back to PostgreSQL internals.

## Workload inventory

| Process | Type | Behavior |
|---|---|---|
| CPU_HIGH | CPU-bound | Tight `sin/cos/sqrt` loop — floating point, no branches |
| CPU_MEDIUM | CPU-bound | Integer LCG (`(x*a+c) & mask`) — integer ALU only |
| MEMORY_100MB / 200MB / 300MB | Memory-bound | Allocates + touches every 4KB page, holds for `DURATION` |
| IO_WORKER_1 / 2 | Disk-bound | Writes 1MB blocks with `fsync()` after each, capped at 2.5 GiB/worker, then wraps and overwrites |
| MIXED_1 / 2 | CPU+memory | 100k sqrt() calls + touches a 50MB buffer, sleeps 0.1s per cycle |
| IDLE | Baseline | Sleeps for the full duration |

Total: 10 processes, 5 GiB disk cap, 300 second run.

## What's correct and worth keeping
- **`fsync()` per write in `io_worker`** is the single best design choice in the
  script — it forces synchronous disk I/O rather than letting writes sit in page
  cache, so `iostat`/`pidstat -d` show *real* device-level I/O. This is a good
  stand-in for how PostgreSQL's WAL writer behaves with `synchronous_commit = on`.
- **The disk-wrap logic is not a bug.** Once `bytes_written >= max_bytes`, the code
  seeks to offset 0, resets the counter, and prints a one-time message — the *next*
  loop iteration re-enters the write branch and continues writing 1MB blocks from
  the start. This sustains continuous I/O indefinitely while capping total disk
  usage at `MAX_TOTAL_DISK_GB` (5 GiB), which is exactly what your `df -h` output
  before/after confirms (no runaway disk growth).
- **Cleanup is safe** — `finally: os.remove(filename)` runs even on `Ctrl+C`
  because `main()` catches `KeyboardInterrupt`, terminates children, and joins
  them before exiting.
- **Two genuinely different CPU patterns** (floating point vs. integer) is a nice
  touch — it'll show up as different `%usr` behavior in `pidstat -u` if a student
  looks closely, useful for talking about CPU microarchitecture later if you want.

## Things to flag to students (not bugs, but worth a sentence each)

1. **10 processes on 2 vCPUs is deliberate oversubscription.** This is *why*
   `uptime` climbs to a load average of ~2.7–3.4 on a 2-core box. Say this
   explicitly in the module — otherwise it reads like something went wrong.
2. **Total explicit memory commitment is only ~600MB** (100+200+300MB) on a
   3.6GB VM. You will not see swap activity (confirmed: `vmstat`'s `so` column
   stayed at 0 throughout your run), so don't promise students they'll see
   swapping — this lab demonstrates memory *allocation visibility* (RSS growth
   in `ps`/`top`), not swap pressure. If you want to demonstrate real swap
   thrashing, you'd need to push allocations closer to `MemAvailable`.
3. **The lab VM is running a full GNOME desktop**, not a minimal server image.
   `ps aux --sort=-%mem` shows `gnome-shell` (298MB RSS), `gnome-software`
   (114MB), `packagekitd`, `evolution-*`, etc. consuming roughly 2GB of the
   3.6GB total *before the test even starts*. This is not representative of a
   real production PostgreSQL host and is worth one caveat slide, otherwise
   the "memused 45%" baseline looks confusing next to a real server.
4. Minor portability note: no `mp.set_start_method()` call, so this relies on
   the platform default (`fork` on Linux). Not an issue for this lab, but if
   this script is ever reused on macOS it will need `if __name__ == "__main__"`
   guards to already be correct (which they are) plus an explicit start method,
   since macOS defaults to `spawn`.

## Verdict
No functional bugs. Script does what it's designed to do and produced clean,
teachable output (visible `D`-state processes, sustained high write throughput,
oversubscribed load average, near-zero swap). Ready to use as-is; the notes
above are framing/narration additions for the module, not code changes.
