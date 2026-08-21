# Disk I/O Analysis: iostat, pidstat -d, vmstat (bi/bo), df

## 1. `iostat -xz 1` — the single most important disk command

Baseline (before IO workers hit steady state):
```
Device  r/s  rkB/s  w/s    wkB/s     w_await  aqu-sz  %util
dm-0   27.91 1276.03 225.81 139587.50   2.02    0.48   37.31
```

Steady state (IO workers overwriting continuously):
```
Device  r/s  rkB/s  w/s    wkB/s     w_await  aqu-sz  %util
dm-0    0.00    0.00 710.89 457737.13   1.81    1.28   93.76
```

**Columns to teach, in priority order:**
- **`w_await`** — average milliseconds a write waits (queue + service time).
  This is *the* number for "is storage actually slow." Yours stayed
  **~1.5–3ms even at 450+ MB/s of write throughput** — that's excellent
  latency, meaning the underlying storage (likely SSD-backed VM disk) is not
  the bottleneck here, even though...
- **`%util`** climbed to **90-94%**, which *looks* saturated but isn't the
  full story — `%util` measures "percentage of time the device had at least
  one request outstanding," which can hit ~100% on a fast device serving many
  small back-to-back requests without any of them actually queuing up.
  **The key teaching point: don't call a disk "saturated" from `%util` alone
  — always check `w_await` and `aqu-sz` together.**
- **`aqu-sz`** (average queue size) — stayed low, **~1.0–1.3**, meaning
  requests were rarely queuing behind each other. Combined with low
  `w_await`, this confirms the storage kept up with 450+ MB/s of sustained
  synchronous writes without becoming a bottleneck.

**PostgreSQL angle:** This is exactly the workflow for diagnosing "queries are
slow, is it disk?" — run `iostat -xz 1` during the slow period. High
`%util` alone doesn't condemn the disk; high `w_await` (multi-millisecond,
climbing into tens of ms) alongside high `aqu-sz` (deep queue) is the real
signal of a storage bottleneck, and maps directly to what you'd eventually see
in `pg_stat_io` as elevated read/write times.

---

## 2. `pidstat -d 1` — which process is generating the I/O

```
UID  PID    kB_rd/s   kB_wr/s   iodelay  Command
0    34016     0.00  200099.67    0      python3.9   (IO_WORKER_1)
0    34017     0.00  208493.11    0      python3.9   (IO_WORKER_2)
```

**Nearly 200MB/s per process, ~400MB/s combined** — matches the aggregate
`iostat` write throughput almost exactly, confirming these two processes are
the entire source of the disk load (as designed). `iodelay` (time this
specific process spent waiting on I/O completion) stayed at 0 in most
samples — the writes were completing fast enough that the process rarely
had to wait.

**PostgreSQL angle:** `pidstat -d -p <pid> 1`, aimed at a specific Postgres
backend PID, is how you confirm *which query/session* is driving disk I/O
before diving into `pg_stat_statements` or `EXPLAIN (ANALYZE, BUFFERS)`. It's
the process-level complement to `iostat`'s device-level view — `iostat` tells
you the disk is busy, `pidstat -d` tells you *who's* keeping it busy.

---

## 3. `vmstat 1` — `bo` as a lightweight proxy

```
bi     bo
  0  75577
  0 472555
  0 487930
  0 508425
```

`bo` (blocks written out, in KB by default) tracks almost exactly with the
`iostat` write throughput — jumping from ~75MB/s to ~470-510MB/s once the IO
workers hit steady state. `bi` (blocks read in) stayed near zero the whole
run — expected, since `io_worker` never reads the file back.

**PostgreSQL angle:** `vmstat`'s `bi`/`bo` won't tell you *which* backend or
*which* file, but it's the fastest single-command gut check for "is this box
doing heavy write I/O right now" — useful as a first command in an SSH
session before reaching for `iostat` or `pg_stat_io`.

---

## 4. `df -h` / `df -i` — capacity, not performance

```
/dev/mapper/cs-root   42G   15G   28G  34% /
```
```
/dev/mapper/cs-root  21854208  132693  21721515  1%  /
```

Both space (34% used) and inode usage (1% used) stayed healthy throughout —
confirming the script's 5 GiB disk cap worked as designed and nothing leaked.

**PostgreSQL angle:** Two separate failure modes to check on a real Postgres
host, and `df` is the only tool for both:
- **`df -h`** — is `PGDATA` (and separately, the WAL/`pg_wal` directory if
  it's on its own mount) running out of space? Postgres will refuse writes
  and can even crash-loop if `pg_wal` fills up.
- **`df -i`** — a database with millions of small files (e.g., many
  partitions/indexes, or a runaway temp-file situation) can exhaust inodes
  while space usage still looks fine. Always check both, not just space.

## Summary — what to look at, in order, for an "is it disk?" ticket
1. `vmstat 1` — quick check: is `bo`/`bi` unusually high, and is `wa` also high?
2. `iostat -xz 1` — look at `w_await` and `aqu-sz` together, not `%util` alone.
3. `pidstat -d -p <pid> 1` — pin the I/O to a specific process/backend.
4. `df -h` and `df -i` — rule out "disk is full" or "inodes exhausted" before anything else.
