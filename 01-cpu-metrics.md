# CPU Analysis: uptime, top, pidstat -u, mpstat

## 1. `uptime` — the fastest first signal

```
18:16:02 up 11 min,  4 users,  load average: 1.38, 1.46, 1.02
```
climbing to:
```
18:16:22 up 11 min,  4 users,  load average: 2.69, 1.76, 1.13
18:16:30 up 12 min,  4 users,  load average: 2.95, 1.83, 1.16
```

**What it means:** Load average is the number of processes *runnable or waiting
on uninterruptible I/O*, averaged over 1/5/15 minutes. This is a **2-vCPU** VM
(confirmed in `mpstat`/`top` header), so a load average of **1.0 = fully
subscribed**. A reading of **2.69–2.95 means the run queue is roughly
1.3–1.5x oversubscribed** — processes are queuing for CPU time.

**PostgreSQL angle:** This is your first triage step on any "database is slow"
ticket, before touching `pg_stat_activity`. If `uptime`'s load average is well
above the CPU core count, backends are competing for scheduler time — query
plans and indexes may be fine, the box is just CPU-starved. Compare load
average to `nproc` (or `cat /proc/cpuinfo | grep -c processor`) every time.

---

## 2. `top` — the process-level breakdown

```
%Cpu(s): 55.0 us, 33.6 sy, 0.0 ni, 1.3 id, 4.7 wa, 3.1 hi, 2.2 si, 0.0 st
```

**Read this line first, always.** Column meanings:
- `us` (user) — time in application code (your Postgres backends, your CPU_HIGH/CPU_MEDIUM workers)
- `sy` (system) — time in kernel code (syscalls, scheduling, filesystem, page faults)
- `wa` (I/O wait) — CPU idle *while a process is blocked on disk I/O*
- `hi`/`si` — hardware/software interrupts

**What's notable in your run:** `sy` is unusually high — **33–54%** across
samples, sometimes exceeding `us`. On a normal application server you'd expect
`sy` to be a small fraction of `us`. Here it's driven by the `io_worker`
processes doing `write()` + `fsync()` in a tight loop (visible as
`kworker/*-kblockd` and `kworker/*-xfs-log` entries burning 20–37% CPU each in
your `top` snapshots) — that's the kernel's block layer and XFS journal doing
work on behalf of the fsync calls, not your Python code.

**PostgreSQL angle:** Elevated `sy` time on a real Postgres host is a classic
sign of **WAL fsync pressure or checkpoint I/O** — the backend calls `fsync()`
on WAL segments and the kernel's journaling/block layer eats CPU doing it.
Seeing `kworker/*-kblockd` or `*-xfs-log`/`*-jbd2` processes high in `top`
alongside high `sy` is a strong hint to go look at `pg_stat_bgwriter`,
`checkpoint_completion_target`, and `pg_stat_io` rather than tuning queries.

---

## 3. Per-process state — `R` vs `D` (from your `ps aux` / `ps -ef` output)

```
root  34017  34010 root  18.7  0.2 238284  9800 R+   python3.9 loadtest.py   (IO worker, growing file)
root  34018  34010 root  13.4  1.6 288460 59984 R+   python3.9 loadtest.py   (mixed worker)
```
and earlier:
```
33953   33946  root   17.7  0.2  238284  10036 D+   python3.9 loadtest.py
```

**The `STAT` column is one of the highest-value columns in `ps`.** `D` means
*uninterruptible sleep* — almost always waiting on disk I/O, and critically,
**a process in `D` state cannot be killed with a normal signal** (not even
`SIGKILL`) until the I/O completes. You caught one of the IO workers in `D`
state mid-run — that's the process blocked inside its `fsync()` call.

**PostgreSQL angle:** This is exactly the state to search for when a backend
appears "hung." `ps -eo pid,stat,cmd | grep postgres | grep D` finds backends
stuck on storage — a strong signal of a struggling disk/SAN/EBS volume rather
than a query planning problem. If you see many Postgres backends in `D`, don't
bother looking at `EXPLAIN ANALYZE` yet — go check `iostat` and the storage
layer first.

---

## 4. `pidstat -u` — per-process CPU with the runqueue-wait column

```
06:26:48 PM  34011  23.58   1.89   0.00   73.58   25.47  python3.9  (CPU_HIGH)
06:26:48 PM  34012  38.68   2.83   0.00   55.66   41.51  python3.9  (CPU_MEDIUM)
```

**Important nuance — don't confuse this `%wait` with I/O wait.** In `pidstat -u`,
the `%wait` column is *"time spent waiting to run on the CPU"* — i.e., the
process was **ready to run but the scheduler couldn't give it a core**, not
waiting on disk. This is CPU runqueue contention, distinct from the `wa` column
in `top`/`vmstat` (which is system-wide I/O wait). In your data, `CPU_HIGH` and
`CPU_MEDIUM` are spending **55–75% of their time simply waiting for a CPU
slot** — direct, process-level confirmation of the oversubscription `uptime`
already hinted at.

**PostgreSQL angle:** If a specific backend's `pidstat -u %wait` is high while
`%CPU` given to it is low, that backend is CPU-starved by *other* processes on
the box — could be other backends, a runaway autovacuum worker, or (in a
shared/virtualized environment) noisy neighbors. This tells you to look at
`max_connections`/pool sizing and total concurrent backend count, not the
individual query.

---

## 5. `mpstat -P ALL 1` — is the load spread evenly across cores?

```
CPU    %usr   %sys  %iowait  %irq  %idle
0     36.55  48.32     3.78  5.46   2.10
1     47.15  47.15     0.41  2.44   0.41
```

**What it means:** CPU 0 is carrying almost all the `%iowait` (3.78% vs
1's 0.41%) and more `%irq`/`%soft` — consistent with `irqbalance` and the
block-device interrupt/softirq handling landing disproportionately on core 0
in this VM, while CPU 1 is doing more pure `%usr` work.

**PostgreSQL angle:** Uneven per-core `%iowait` is worth checking on real
hardware/VMs with NUMA or IRQ-affinity quirks — a single core pegged by
interrupt handling can become an invisible bottleneck for one WAL writer or
background worker even when aggregate CPU looks fine. `mpstat -P ALL` is the
tool that reveals this; `top`'s single aggregate line hides it.

## Summary — what to look at, in order, for a "CPU seems high" ticket
1. `uptime` — is load average above core count?
2. `top` header — is it `us` (app work) or `sy` (kernel work, often I/O-related) that's high?
3. `ps -eo pid,stat,cmd` — any backends stuck in `D`?
4. `pidstat -u -p <pid>` — is the specific backend CPU-starved (`%wait`) or actually burning CPU (`%usr`)?
5. `mpstat -P ALL` — is one core doing disproportionate interrupt/iowait work?
