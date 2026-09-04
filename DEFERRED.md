# Deferred Items

Items below are intentionally deferred until the 60-day paper trading period
completes. Each entry has a trigger condition; only start the work when the
condition is met.

| Item | Trigger condition | Priority |
|------|-------------------|----------|
| Close-confirm stop vs intrabar stop (#6) | Count "stop hit intrabar then close recovers above stop" events; if frequent, run comparison experiment | P2 |
| Quality grade calibration (#13) | Each grade (A/B/C/D) has >= 10 closed trades | P1 |
| Exit timing analysis | Run alongside #13: check MFE after exit to see if short-stage exits prematurely close profitable longs | P1 |
| Regime filter (ADX) (#7) | Only if segmented performance shows range-bound markets are the primary loss source | P2 |
| Agent layer correlation (#9-12) | Resume agent framework development | P3 |
| Portfolio-level drawdown brake (#14) | Multi-asset portfolio mode | P3 |
