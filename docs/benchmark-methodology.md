# Benchmark methodology

Run `logtriage benchmark --repeat 1000 > benchmark.json` with the same Python
environment and scenario when comparing changes. The command uses deterministic
synthetic logs and the rules-only provider, then records the sample size,
throughput, processing time, grouping, alerts, and environment. These are
observations on the machine running the command, not guarantees. Model latency
must be measured separately with a locally installed model and should include
warm-up policy, model tag, quantization metadata from `logtriage doctor`, and
the number of samples.
