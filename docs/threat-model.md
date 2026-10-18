# Threat model

Log lines are untrusted input. The parser applies line-size limits, the
aggregator bounds groups and context, and redaction runs before model input and
optional persistence. Prompt content is explicitly delimited as data and the
model receives no tools or command execution capability.

The application makes no network calls except to the configured localhost
Ollama endpoint. It does not upload logs or download models. Configure input
paths narrowly and avoid following untrusted symlinks. Generic regular
expressions cannot detect every secret format, so operators remain responsible
for log hygiene. SQLite failures are surfaced to the caller rather than
silently treated as successful persistence.

Remaining risks include resource pressure from maliciously high input rates,
false positives in configurable patterns, and sensitive information not
matching the configured redaction rules.
