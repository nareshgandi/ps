# 07: Grafana Observability Stack for the Performance Masterclass

Turns M-OS-03's experiments from scrollback-and-hand-copied-numbers into a
visual, correlated, timestamped record. This is not "install Grafana and
look at a pretty graph" — the point is making the OS ↔ PostgreSQL
correlation from M-OS-03 Part 3 visible on one screen instead of built by
hand from two separate terminal logs.

```
                    Grafana
                       │
                       ▼
                  Prometheus
                 /           \
                /             \
               ▼               ▼
        node_exporter     postgres_exporter
              │                 │
              ▼                 ▼
          Linux OS          PostgreSQL

    loadtest.py --metrics-port  ──────►  Prometheus (what the experiment IS)
```

`loadtest.py` and `pgbench` remain the workload generators. Grafana becomes
the observability layer sitting on top of everything already built in
M-OS-01 through M-OS-03.

---

## 1. What to install (single lab VM)

```bash
# Prometheus
wget https://github.com/prometheus/prometheus/releases/latest/download/prometheus-*.linux-amd64.tar.gz
tar xvf prometheus-*.linux-amd64.tar.gz
sudo mv prometheus-*/prometheus prometheus-*/promtool /usr/local/bin/

# node_exporter
wget https://github.com/prometheus/node_exporter/releases/latest/download/node_exporter-*.linux-amd64.tar.gz
tar xvf node_exporter-*.linux-amd64.tar.gz
sudo mv node_exporter-*/node_exporter /usr/local/bin/

# postgres_exporter
wget https://github.com/prometheus-community/postgres_exporter/releases/latest/download/postgres_exporter-*.linux-amd64.tar.gz
tar xvf postgres_exporter-*.linux-amd64.tar.gz
sudo mv postgres_exporter-*/postgres_exporter /usr/local/bin/

# Grafana (Rocky/Alma/CentOS)
sudo tee /etc/yum.repos.d/grafana.repo <<EOF
[grafana]
name=grafana
baseurl=https://rpm.grafana.com
repo_gpgcheck=1
enabled=1
gpgcheck=1
gpgkey=https://rpm.grafana.com/gpg.key
EOF
sudo dnf install -y grafana
sudo systemctl enable --now grafana-server

# loadtest.py's own metrics export (optional, used in section 7)
pip install prometheus_client --break-system-packages
```

Always check each project's release page for the current version rather
than hardcoding a version number here — these move faster than a course
document should try to track.

---

## 2. What each component teaches

| Component | Purpose | What it exposes |
|---|---|---|
| `loadtest.py` | Generate controlled OS contention | worker counts, duration, fsync mode (via `--metrics-port`) |
| `pgbench` | Generate real PostgreSQL workload | TPS, latency (via terminal output, or `pg_stat_statements` if enabled) |
| `node_exporter` | Export Linux OS metrics | CPU, memory, disk, network, dirty pages |
| `postgres_exporter` | Export PostgreSQL metrics | connections, transactions, cache hit ratio, checkpoints |
| Prometheus | Store and query all of the above as time series | — |
| Grafana | Correlate and visualize everything on one timeline | — |

---

## 3. Minimal Prometheus config

```yaml
# /etc/prometheus/prometheus.yml
global:
  scrape_interval: 5s

scrape_configs:
  - job_name: 'node'
    static_configs:
      - targets: ['localhost:9100']

  - job_name: 'postgres'
    static_configs:
      - targets: ['localhost:9187']

  - job_name: 'loadtest'
    static_configs:
      - targets: ['localhost:9099']   # matches loadtest.py --metrics-port 9099
```

```bash
# node_exporter
node_exporter &

# postgres_exporter — point it at a monitoring role, not the superuser
export DATA_SOURCE_NAME="postgresql://postgres_exporter:PASSWORD@localhost:5432/bankforge?sslmode=disable"
postgres_exporter &

# Prometheus
prometheus --config.file=/etc/prometheus/prometheus.yml &
```

Confirm all three targets are `UP` at `http://localhost:9090/targets` before
touching Grafana at all — debugging a blank Grafana panel is much harder
than debugging a red target in Prometheus's own UI.

**Give `postgres_exporter` a dedicated role, not superuser:**
```sql
CREATE USER postgres_exporter WITH PASSWORD 'PASSWORD';
GRANT pg_monitor TO postgres_exporter;
```
`pg_monitor` is the built-in role designed for exactly this — it grants read
access to the monitoring views without granting broader privileges.

---

## 4. Connect Grafana to Prometheus

```
Grafana UI -> Connections -> Data sources -> Add data source -> Prometheus
URL: http://localhost:9090
Save & Test
```

---

## 5. Dashboard IDs — verified, with caveats

I checked each of these against Grafana's public dashboard catalog before
including it here — dashboard IDs and their content do change over time, and
one figure from a source I reviewed while preparing this (a "newer" dashboard
described as ID 24919) turned out to be real but is not the only recent
option; there's also a separate, differently-numbered "PostgreSQL Monitoring
Dashboard" (24298) with an overlapping name and purpose. Given how fast this
catalog turns over, **don't treat any ID here as permanent — search
`grafana.com/grafana/dashboards` for "node exporter" or "postgres exporter"
at import time and confirm the description and required exporter version
still match your setup before importing.**

| Dashboard | ID | What it needs | Notes |
|---|---|---|---|
| **Node Exporter Full** | **1860** | `node_exporter` | The de facto standard for Linux OS metrics — CPU, memory, disk, filesystem, network. Confirmed current and by far the most widely used node_exporter dashboard as of this writing. Start here for the OS side. |
| **PostgreSQL Database** | **9628** | `postgres_exporter` | The most widely used general-purpose Postgres dashboard for this exporter — connections, transaction rates, tuple operations, cache hit ratio, locks, database sizes. Solid default, but older in design. |
| **PostgreSQL Exporter Quickstart / Postgres Overview** | **14114** | `postgres_exporter` | Ships as part of the official Postgres Exporter "mixin" (preconfigured dashboards + alerting + recording rules). Adds QPS, row-level insert/update/delete rates, deadlocks, conflicts alongside the same core connection/cache metrics as 9628. |
| **PostgreSQL Monitoring Dashboard** | **24919** or **24298** | `postgres_exporter` (or `pg_exporter`, check the specific one) | Two separately-numbered, similarly-named "PostgreSQL Monitoring" dashboards exist in the current catalog, both relatively recent. Check the exporter each one expects (some target `pg_exporter`, not the more common `postgres_exporter`) before importing — this is exactly the kind of detail that silently breaks a dashboard import. |

**Recommendation for the Masterclass: import exactly two off-the-shelf
dashboards, not four.**

```
1. Node Exporter Full (1860)         -> OS-layer overview
2. PostgreSQL Database (9628) OR
   PostgreSQL Exporter Quickstart (14114) -> pick whichever's panel set
                                             matches your PostgreSQL version's
                                             available stats views
```

Everything the Masterclass is actually *for* — the correlation, the
annotated before/after comparisons, the loadtest-specific panels — lives in
the **custom dashboard** built in Section 6, not in an imported one.

```bash
# Import via UI: Dashboards -> New -> Import -> enter ID -> select Prometheus data source
# Or via API:
curl -s https://grafana.com/api/dashboards/1860/revisions/latest/download \
  -o node-exporter-full.json
# then import node-exporter-full.json through the Grafana UI
```

---

## 6. The custom Masterclass dashboard

Build one dashboard named **"PostgreSQL Performance Engineering — Masterclass"**
with six rows. This is the artifact that makes the module yours rather than
a generic "import 1860" tutorial — it's built directly around what
`loadtest.py` and `pgbench` produce.

### Row 1 — Workload (stat panels)
| Panel | PromQL |
|---|---|
| Active connections | `pg_stat_activity_count` |
| Transactions/sec | `rate(pg_stat_database_xact_commit{datname="bankforge"}[1m])` |
| Cache hit ratio | `pg_stat_database_blks_hit{datname="bankforge"} / (pg_stat_database_blks_hit{datname="bankforge"} + pg_stat_database_blks_read{datname="bankforge"})` |

(`pgbench`'s own `tps`/`latency average` aren't in Prometheus by default — either log them to a file per run and annotate manually, per Section 8, or wrap `pgbench` output into a small `node_exporter` textfile collector entry if you want them graphed live.)

### Row 2 — CPU (time series)
| Panel | PromQL |
|---|---|
| CPU usage by mode | `rate(node_cpu_seconds_total{instance="$node"}[1m])` (stacked by `mode`) |
| Load average | `node_load1`, `node_load5`, `node_load15` |
| Context switches/sec | `rate(node_context_switches_total[1m])` |
| Run queue length | derived — see M-OS-01's `vmstat` `r` column; no direct node_exporter equivalent, note this gap explicitly for students |

### Row 3 — Memory (time series)
| Panel | PromQL |
|---|---|
| Memory used / available / cached | `node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes`, `node_memory_MemAvailable_bytes`, `node_memory_Cached_bytes` |
| Swap in/out | `rate(node_vmstat_pswpin[1m])`, `rate(node_vmstat_pswpout[1m])` |
| **Dirty / Writeback** | `node_memory_Dirty_bytes`, `node_memory_Writeback_bytes` |

The **Dirty/Writeback panel is the single most important panel in this
dashboard** — it's the direct visual version of M-OS-02/M-OS-03's
`--no-fsync` experiment. Put it on its own row if your panel budget allows.

### Row 4 — Disk (time series)
| Panel | PromQL |
|---|---|
| Read/Write throughput | `rate(node_disk_read_bytes_total[1m])`, `rate(node_disk_written_bytes_total[1m])` |
| IOPS | `rate(node_disk_reads_completed_total[1m])`, `rate(node_disk_writes_completed_total[1m])` |
| Await (approx.) | `rate(node_disk_write_time_seconds_total[1m]) / rate(node_disk_writes_completed_total[1m])` |
| Utilization | `rate(node_disk_io_time_seconds_total[1m])` |

The await/utilization pair here is the Grafana version of M-OS-01's
`iostat -xz` `w_await`/`%util` reading — same nuance applies: high
utilization alone doesn't prove saturation, check it alongside await.

### Row 5 — PostgreSQL detail (time series)
| Panel | PromQL |
|---|---|
| Blocks read vs. hit | `rate(pg_stat_database_blks_read{datname="bankforge"}[1m])`, `rate(pg_stat_database_blks_hit{datname="bankforge"}[1m])` |
| Rows returned/fetched/inserted/updated/deleted | `rate(pg_stat_database_tup_returned{datname="bankforge"}[1m])` etc. |
| Deadlocks / conflicts | `rate(pg_stat_database_deadlocks{datname="bankforge"}[1m])` |

### Row 6 — PostgreSQL I/O and checkpoints
For PostgreSQL 17+ (`pg_stat_checkpointer`) vs ≤16 (`pg_stat_bgwriter`) —
same version split as M-OS-02/M-OS-03; `postgres_exporter`'s default query
set may need a custom queries file added for the newer view if you're on
17+. Check `postgres_exporter`'s `queries.yaml` support before assuming
either metric name is exposed out of the box.

| Panel | Metric (name depends on exporter version/config) |
|---|---|
| Checkpoints requested vs. timed | `pg_stat_bgwriter_checkpoints_req` / `_timed`, or `pg_stat_checkpointer_num_requested` / `_timed` |
| Checkpoint sync time | `pg_stat_bgwriter_checkpoint_sync_time`, or `pg_stat_checkpointer_sync_time` |
| Buffers written by checkpoint | `pg_stat_bgwriter_buffers_checkpoint`, or `pg_stat_checkpointer_buffers_written` |

Place this row directly beside Row 4 (OS disk metrics) — this adjacency is
the entire point of the dashboard: PostgreSQL's own view of its I/O next to
the OS's view of the same I/O, on the same timeline.

```
POSTGRESQL I/O (Row 6)              OS DISK I/O (Row 4)
        │                                   │
        ▼                                   ▼
  pg_stat_checkpointer              node_exporter disk metrics
        │                                   │
        └───────────────┬───────────────────┘
                        ▼
                   CORRELATE
```

---

## 7. Make `loadtest.py` self-documenting

`loadtest.py` supports `--metrics-port` (requires `pip install
prometheus_client`), exposing what the current experiment *is* as
Prometheus gauges:

```bash
python3 loadtest.py --duration 120 --no-fsync --metrics-port 9099
```

```
loadtest_cpu_workers
loadtest_memory_workers
loadtest_io_workers
loadtest_mixed_workers
loadtest_idle_workers
loadtest_duration_seconds
loadtest_no_fsync        # 1 or 0
loadtest_running         # 1 while active, 0 otherwise
```

Add a small **Row 0 — Experiment Configuration** (stat panels) at the top of
the custom dashboard using these gauges: CPU workers, memory workers, I/O
workers, fsync mode. Now every screenshot or recording of the dashboard
during an experiment carries its own configuration label — a viewer doesn't
need to cross-reference a separate terminal to know what was running when
the graphs moved. This is a meaningfully better artifact for a course
recording or a written report than "trust me, this is the `--no-fsync` run."

---

## 8. Annotations — marking the timeline

Grafana annotations let you mark exactly when each phase of an M-OS-03
experiment started, directly on the graph — this replaces hand-written
timestamp tables with something visual and shareable.

**Manually, during a live session:** Ctrl+Click (or Cmd+Click) on any time
series panel and add a text annotation. Do this at minimum for:
```
Baseline started
loadtest started
pgbench started
sysctl change applied
loadtest stopped
Rollback applied
```

**Programmatically, for scripted/repeatable runs**, via Grafana's HTTP API:
```bash
curl -X POST http://admin:admin@localhost:3000/api/annotations \
  -H "Content-Type: application/json" \
  -d '{"text":"loadtest --no-fsync started","tags":["experiment"],"time":'$(date +%s000)'}'
```
Wrap this in a small shell function and call it at the start/end of each
phase in your experiment scripts — this is a natural companion to the
control-group repeat loop from M-OS-03 Part 2, since every repeat gets its
own annotated boundary automatically instead of relying on memory.

---

## 9. The experiment-results dashboard (optional second custom dashboard)

A second, simpler dashboard — **"M-OS Experiment Results"** — works well as
the literal artifact students submit for grading. Structure it as a table,
manually filled in per experiment (Grafana's Text/Table panels can hold
static data, or pull from a small results table if you're logging into
Postgres itself):

```
Experiment          CPU workers  Mem workers  IO workers  Fsync   BEFORE TPS  AFTER TPS  BEFORE Dirty  AFTER Dirty
Dirty-page buildup   0            0            2           off     1250        1480       420MB         120MB
CPU affinity (taskset) 6          0            0           n/a     980         1310        n/a           n/a
```

This table format is deliberately the same shape as M-OS-03's five-number
results block — the dashboard is a visual complement to that written report,
not a replacement for it.

---

## 10. Recommended dashboard set — summary

| Purpose | Dashboard |
|---|---|
| Linux OS overview | 1860 — Node Exporter Full |
| PostgreSQL overview | 9628 or 14114 — pick based on your PostgreSQL version's exposed stats |
| Masterclass correlation | Custom — Section 6, built specifically around `loadtest.py` + `pgbench` |
| Experiment results | Custom (optional) — Section 9 |

Two imported dashboards, two custom ones. Don't install more than that for
this module — every additional imported dashboard is one more thing that can
silently break on a metric-name mismatch with your specific `postgres_exporter`
version, and none of them replace the correlation work the custom dashboard
is built to teach.
