# Session Cheat Sheet: OS Commands → PostgreSQL Investigation

Use this as the closing slide / handout. It's the "so what do I actually run,
in what order" summary of the four detail docs.

## Suggested live-session flow

1. Start `loadtest.py` in one terminal (`python3.9 loadtest.py`).
2. In a second terminal, run commands top-to-bottom below, pausing on each to
   let the room read the live numbers.
3. Close by mapping every command to the PostgreSQL side, using the table below.

## The triage sequence (fastest signal → most specific)

| Step | Command | 5-second read | What you saw in this lab |
|---|---|---|---|
| 1 | `uptime` | Load average vs. core count | 2.69–2.95 on a 2-vCPU box → oversubscribed |
| 2 | `top` | `us`/`sy`/`wa` split in the header | `sy` hit 33–54%, driven by fsync-heavy I/O workers |
| 3 | `vmstat 1` | `r`, `b`, `si/so`, `wa` columns | `r`≈5-6 (CPU contention), `si/so`≈0 (no swap), `bo` up to 508K |
| 4 | `free -m` | `available`, not `free` | 1633MB available, healthy despite low `free` |
| 5 | `iostat -xz 1` | `w_await` + `aqu-sz` together, not `%util` alone | `%util` 90%+ but `w_await` only ~2ms → disk not the bottleneck |
| 6 | `ps -eo pid,stat,cmd` | Any process in `D` state? | IO workers briefly in `D` mid-fsync |
| 7 | `pidstat -u/-d 1` | Per-process CPU-wait vs. per-process disk throughput | CPU workers 55-75% `%wait` (runqueue, not I/O); IO workers 150-450MB/s writes |
| 8 | `mpstat -P ALL 1` | Even load across cores? | CPU0 carried more `%iowait`/`%irq` than CPU1 |
| 9 | `ss -lntp` | Is the service even listening? | No Postgres running yet in this lab — port 5432 absent |
| 10 | `df -h` / `df -i` | Space AND inodes | Both healthy; disk cap in script (5GiB) confirmed working |

## Full OS → PostgreSQL mapping table (expanded)

| OS symptom | OS command | What to look for | PostgreSQL investigation |
|---|---|---|---|
| High CPU | `top`, `pidstat -u` | `us` vs `sy` split; per-process `%wait` (runqueue, not I/O) | `pg_stat_activity` (active queries), `pg_stat_statements` (which query burns CPU) |
| High memory | `free -m`, `vmstat`, `sar -r` | `available` not `free`; `si/so` for real swap; `kbdirty` for flush lag | `work_mem` × concurrent sorts/hashes, `max_connections`, `shared_buffers` sizing |
| High disk I/O | `iostat -xz`, `pidstat -d` | `w_await` + `aqu-sz` together, not `%util` alone; which PID owns the throughput | `pg_stat_io`, checkpoint frequency (`pg_stat_bgwriter`), WAL volume |
| High I/O wait | `vmstat` (`wa`), `top` (`wa`) | Sustained `wa` > ~10-20% while `bo`/`bi` are also high | Slow storage under real read/write mix — cross-check with `iostat` before blaming queries |
| Many processes | `ps -ef --forest`, `top` | Process tree shape; count of backend processes | `pg_stat_activity` backend count vs. `max_connections`; consider PgBouncer/Pgpool-II |
| Disk full | `df -h`, `df -i` | Both space AND inode usage | `PGDATA` size, `pg_wal` size specifically, log rotation, temp file bloat |
| Network issue | `ss -lntp`, `ss -tn`, `sar -n` | Is the port listening; who's connected at OS level | `pg_stat_activity` vs. `pg_stat_replication`; `pg_hba.conf` if connections are refused |
| Swap | `free -m`, `vmstat` (`si/so`) | Non-zero `si`/`so` = real pressure, not just low `free` | Total memory budget: `shared_buffers` + (`work_mem` × concurrent ops) + OS overhead |
| Process stuck | `ps -eo pid,stat,cmd` | `STAT` column = `D` (uninterruptible, can't be killed) | Backend stuck in `D` → storage problem, not a query problem; `pg_terminate_backend()` won't help until I/O returns |

## The two nuances worth repeating on camera

1. **`%util` in `iostat` is not the same as "disk is the bottleneck."** It
   measures time-with-outstanding-request, which can hit 90%+ on a fast disk
   handling many small ops without any of them actually queuing. Always pair
   it with `w_await` (latency) and `aqu-sz` (queue depth) before concluding
   storage is saturated.
2. **`pidstat -u`'s `%wait` column is CPU runqueue wait, not I/O wait.** It's
   easy to mis-read this as "waiting on disk." It means the process was
   ready to run and the scheduler couldn't give it a core — a CPU
   oversubscription signal, not a storage signal. `D` state in `ps`/`top` is
   the actual I/O-wait indicator at the process level.

## What this lab intentionally does NOT show
- Real swap thrashing (memory workers only commit ~600MB on a 3.6GB box)
- A live PostgreSQL instance to correlate against (this is pure OS-layer
  groundwork — module N+1 should connect `pg_stat_activity` output side-by-side
  with these same `top`/`iostat` snapshots on a running instance)
