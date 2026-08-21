# Process & Network Analysis: ps -ef, ps aux, ss, ip addr

## 1. `ps -ef` vs `ps aux` — same data, different lens

`ps -ef` (UNIX-style, shows PPID clearly):
```
UID   PID   PPID  C STIME TTY  TIME CMD
root  33946 2677  0 18:15 pts/2 00:00:00 python3.9 loadtest.py
root  33947 33946 30 18:15 pts/2 00:00:16 python3.9 loadtest.py
```

`ps aux` (BSD-style, shows %CPU/%MEM directly):
```
USER  PID   %CPU %MEM  VSZ    RSS   TTY  STAT START TIME COMMAND
root  33947 30.0  0.2 237256  9008  pts/2 R+  18:15 0:16 python3.9 loadtest.py
```

**Use `-ef` to understand process ancestry** — here it clearly shows
`33946` (the `main()` launcher) as parent of `33947`-`33956` (the 10 worker
processes), which is exactly the `multiprocessing.Process` tree the script
creates. **Use `aux` when you need %CPU/%MEM sorted at a glance** — it's the
one that pipes cleanly into `--sort=-%cpu` or `--sort=-%mem`.

**PostgreSQL angle:** `ps -ef | grep postgres` (or `ps -ef --forest`) is how
you see the real Postgres process tree: postmaster → background workers
(checkpointer, walwriter, autovacuum launcher, logical replication workers) →
one process per client backend. Parent/child relationships matter when
killing a runaway process — killing the wrong process in that tree
(e.g., the postmaster instead of one backend) takes the whole instance down.

---

## 2. The `STAT` column, decoded from your actual output

Values seen across your samples: `S`, `R`, `D`, `I`, `Ss`, `Sl`, `Ssl`, `S+`, `R+`, `D+`

| Flag | Meaning | Seen on |
|---|---|---|
| `R` | Running or runnable | CPU_HIGH/CPU_MEDIUM workers during busy loops |
| `S` | Interruptible sleep (waiting on an event, can be woken) | IDLE worker, memory workers during `time.sleep()` |
| `D` | **Uninterruptible sleep — waiting on I/O, cannot be killed** | IO workers mid-`fsync()` |
| `s` (lowercase, in combos like `Ss`) | Session leader | shell/daemon processes |
| `l` | Multi-threaded | `gnome-shell`, `vmtoolsd` |
| `+` | In the foreground process group of its terminal | interactive shell jobs |

**The one to drill into students: `D` state + `SIGKILL` doesn't work.** A
process in `D` is inside a kernel call (usually disk I/O) that the kernel
won't interrupt. `kill -9` queues the signal but it isn't delivered until the
syscall returns. If a "hung" process won't die even with `-9`, check its
`STAT` — it's very likely `D`, and the fix is to find out why the underlying
I/O isn't completing (failing disk, NFS hang, etc.), not to keep sending
signals.

**PostgreSQL angle:** A Postgres backend stuck in `D` state that resists
`pg_terminate_backend()` almost always means the underlying storage is the
actual problem — the backend is parked inside a kernel write/read call. This
reframes the incident from "why won't Postgres respond" to "why is the
storage layer not completing I/O."

---

## 3. `ss -lntp` — is anything actually listening?

```
State   Local Address:Port   Process
LISTEN  127.0.0.1:631        cupsd
LISTEN  0.0.0.0:22           sshd
LISTEN  [::]:22              sshd
LISTEN  [::1]:631            cupsd
```

**Notable: no PostgreSQL here.** This lab VM doesn't have Postgres installed
or running yet — worth calling out explicitly in the session so students
aren't confused about why port 5432 is missing. Once Postgres is installed,
this same command should show:
```
LISTEN  0.0.0.0:5432   postgres
```
(or `127.0.0.1:5432` only, if `listen_addresses` is restricted — itself a
useful thing to point out as a connectivity troubleshooting step).

**PostgreSQL angle:** `ss -lntp | grep 5432` is the first command to run when
an app can't connect to Postgres at all (before checking `pg_hba.conf` or
credentials) — it answers "is the postmaster even listening, and on which
interface." Pair it with `ss -tn state established '( dport = :5432 or sport
= :5432 )'` to count and inspect live client connections at the OS level,
independent of `pg_stat_activity`.

---

## 4. `ip addr` — mostly context, not diagnosis

```
2: ens33: inet 192.168.234.132/24 ... state UP
```

Single NIC, DHCP-assigned, link up. Nothing actionable for this lab, but
establishes the IP a student would use for a remote `psql -h` connection test
later in the session, and is the natural jumping-off point for `ss -tn` if you
want to demonstrate inspecting live client connections by peer address.

## Summary — what to look at, in order, for a "process/connectivity" ticket
1. `ps -ef --forest | grep postgres` — confirm the process tree looks healthy (one postmaster, expected background workers, N backends).
2. `ps -eo pid,stat,cmd | grep postgres | grep ' D'` — any backend stuck in uninterruptible I/O wait?
3. `ss -lntp | grep 5432` — is Postgres even listening, and on which address?
4. `ss -tn state established '( sport = :5432 )'` — who's actually connected right now, at the OS level.
