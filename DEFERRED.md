# Deferred Items

Items below are intentionally deferred until the 60-day paper trading period
completes. Each entry has a trigger condition; only start the work when the
condition is met.

| Item | Trigger condition | Priority | Origin |
|------|-------------------|----------|--------|
| Close-confirm stop vs intrabar stop (#6) | Count "stop hit intrabar then close recovers above stop" events; if frequent, run comparison experiment | P2 | v0.8 review |
| Quality grade calibration (#13) | Each grade (A/B/C/D) has >= 10 closed trades | P1 | v0.8 review |
| Exit timing analysis | Run alongside #13: check MFE after exit to see if short-stage exits prematurely close profitable longs | P1 | v0.8 review |
| Regime filter (ADX) (#7) | Only if segmented performance shows range-bound markets are the primary loss source | P2 | v0.8 review |
| Agent layer correlation (#9-12) | Resume agent framework development | P3 | v0.8 review |
| Portfolio-level drawdown brake (#14) | Multi-asset portfolio mode | P3 | v0.8 review |
| Trend base vs signal layer attribution | Run after paper trading: decompose combined return into base layer and signal layer contributions | P1 | v0.9 review |
| Cross-asset strategy validation (cycle on ETH, V3 on BTC) | Run after paper trading to separate asset effect from strategy effect | P2 | v0.9 review |
| Funding rate: perp vs spot comparison | After paper trading: compare perpetual (10% annual cost) vs spot (no funding) net returns | P1 | v0.9 review |
| Monte Carlo on WF folds | Bootstrap the 28 OOS fold returns for a realistic profit probability | P2 | v0.9 review |
