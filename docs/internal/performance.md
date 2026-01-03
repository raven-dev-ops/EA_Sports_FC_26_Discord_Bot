# Performance & Profiling

- Command latency is logged with duration buckets and status counters.
- Avoid mass Discord writes: cache API lookups and reuse results where possible.
- Use `python -m scripts.profile --module offside_bot.__main__ --func main` for quick CPU profiling.
- Budget: keep typical slash command latency under 2s; avoid blocking network calls with missing timeouts.
- For long-running tasks, prefer background jobs via the scheduler (`services/scheduler.py`) instead of blocking interactions.
