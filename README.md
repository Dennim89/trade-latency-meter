# trade-latency-meter

A small stopwatch for the hot path of a trading or MEV bot, and a CLI that turns the recorded
timings into a report. It answers one question: where do the microseconds go between "event
arrived" and "transaction signed"? It also has offline benchmarks for building and signing Solana
(v0) and EVM (EIP-1559) transactions. **It never sends anything to a network.**

For developers of trading bots, market-data handlers and other latency-sensitive Python services
who want to measure the path instead of guessing.

Status: **experimental**. Offline paths (meter, report, demo, both signing benches) are tested in
this repo. Not yet verified against mainnet: the library has no network code, but it has not yet
been dropped into a live bot for this release. Built with AI coding agents (Claude, Codex).

## Sample output

Everything below was produced in the cloud sandbox this release was built in, by the command shown
above each block. Numbers from your machine will differ. Machine for all blocks: Intel Xeon
2.80 GHz VM (4 cores), Linux 6.18 x86_64, CPython 3.13.16, tlm 0.1.0.

`tlm demo --no-hist` runs a synthetic pipeline (fake event, parse, placeholder decision, build,
HMAC "signature", write to a local socket pair) through the meter:

```
cpu:    Intel(R) Xeon(R) Processor @ 2.80GHz (4 cores)
os:     Linux-6.18.44-fc-v80-x86_64-with-glibc2.39
python: CPython 3.13.16
libs:   tlm 0.1.0; solders 0.29.0, eth-keys 0.8.0, eth-hash 0.8.0, rlp 5.0.0, coincurve 21.0.0, eth-account 0.14.0
events: 2000

stage           count        p50        p90        p99      p99.9        max
parsed           2000    2.93 us    3.37 us    6.73 us   39.47 us  101.32 us
decided          2000     383 ns     651 ns     982 ns    3.46 us   21.40 us
built            2000     424 ns     557 ns    1.48 us    5.99 us    8.32 us
signed           2000    3.13 us    3.47 us    7.40 us   49.57 us   56.71 us
sent             2000    1.23 us    1.37 us    3.33 us   22.52 us   23.57 us
end-to-end       2000    8.39 us    9.81 us   30.38 us   64.66 us  137.06 us
event age        2000    2.97 ms    4.60 ms    4.96 ms    5.00 ms    5.00 ms
note: event age compares the local wall clock with a remote timestamp; it is only
      as accurate as the clock sync between the two machines (can be negative).

meter overhead: 301 ns per begin/mark/end call (bare clock read: 70 ns; 4 marks per event)
demo pipeline is synthetic: placeholder decision, HMAC instead of a chain signature,
local socket pair instead of a network.
```

"Event age" in the demo is a made-up remote timestamp 1 to 5 ms in the past. Without `--no-hist`
the demo also prints a text histogram per stage.

The signing benches (`tlm bench solana --n 20000`, `tlm bench evm --n 20000`; same machine; the
header lines are cut here, the CLI prints them):

```
bench solana: n=20000, 413 bytes; fresh in-memory key; nothing is sent

step              min        p50        p90        p99      p99.9        max
build        24.84 us   26.28 us   47.70 us   82.97 us  173.04 us    3.13 ms
sign         88.07 us   93.15 us  161.44 us  225.88 us  440.33 us    2.79 ms
build+sign  113.07 us  121.68 us  210.12 us  291.21 us  736.32 us    3.29 ms

bench evm: n=20000, chain id 1, backend CoinCurveECCBackend; fresh in-memory key; nothing is sent

step              min        p50        p90        p99      p99.9        max
rlp_encode   23.83 us   27.07 us   50.49 us  103.26 us  211.95 us    2.56 ms
keccak        8.87 us   10.15 us   19.90 us   51.25 us  117.06 us    2.54 ms
sign         91.98 us   98.92 us  173.48 us  268.28 us  823.57 us    3.48 ms
total       125.41 us  139.99 us  247.28 us  368.49 us    1.28 ms    3.73 ms
```

This is a shared cloud VM, so the tails (p99 and above) are noisy. Run it on the machine you care
about. The Python wrappers add their own cost; these numbers are for the Python path only.

## Quickstart

```
pip install -e '.[solana,evm-fast]'    # extras are optional; the meter, report and demo need none
tlm demo --no-hist
tlm demo --out timings.jsonl && tlm report timings.jsonl
tlm bench solana --n 20000
tlm bench evm --n 20000
```

`python -m trade_latency_meter ...` works the same as `tlm ...`. Requires Python 3.10+.

## Use it in your own code

```python
from trade_latency_meter import Meter

meter = Meter(capacity=8192)             # preallocated ring buffer

h = meter.begin("evt-1")                 # optional: remote_ts_ns=<epoch ns from the event>
...parse...
h.mark("parsed")
...decide...
h.mark("decided")
with h.stage("sign"):                    # times only this block
    ...sign...
h.mark("sent")
h.end()

meter.flush("timings.jsonl")             # on demand, or:
meter.start_flusher("timings.jsonl")     # background thread, then meter.stop_flusher("timings.jsonl")
```

A mark closes a stage: its duration is the time since the previous mark (or since `begin`).
Stage names are free-form strings and the report keeps their first-seen order. Time spent between
`with h.stage(...)` blocks is not attributed to a stage but is counted in end-to-end.
`meter.stage("x")` is a shortcut that uses the most recently begun event (single-threaded code).

The hot path (`begin`, `mark`, `end`) does a clock read and a few list writes: no logging, no I/O,
no locks. `tlm overhead` measures that cost on your machine; `tlm demo` prints it too. The clock
and wall clock are injectable (`Meter(clock=..., wall_clock=...)`), which is how the tests are
deterministic.

## Commands

| Command | What it does |
|---|---|
| `tlm report FILE [--json] [--bins N]` | per stage and end to end: count, p50, p90, p99, p99.9, max, plus a text histogram |
| `tlm bench solana [--n N] [--seed S] [--json]` | build and sign a v0 transaction shaped like a swap (two compute-budget instructions, six accounts, one program instruction with 24 bytes of data); build and sign timed separately |
| `tlm bench evm [--n N] [--chain-id ID] [--json]` | build and sign an EIP-1559 transaction; RLP encoding, Keccak-256 and signing timed separately |
| `tlm demo [--n N] [--out FILE] [--no-hist] [--json]` | synthetic pipeline through the meter |
| `tlm overhead [--json]` | cost of one meter call on this machine |

Settings come from flags or environment variables (`TLM_BENCH_N`, `TLM_CHAIN_ID`, `TLM_DEMO_N`);
see `.env.example`. Exit codes: 0 ok, 2 bad input or file, 3 bench unavailable.

Percentiles use linear interpolation between closest ranks (numpy's default). With fewer than
1000 samples p99.9 is interpolated close to max, and the report says so. Benches run 50 unrecorded
warm-up rounds first.

## Output formats

Timings file (JSONL, one event per line, durations in nanoseconds; `age_ns` only when the event
had a remote timestamp):

```
{"id":0,"stages":[["parsed",47034],["decided",4284],["built",9104],["signed",69062],["sent",24950]],"total_ns":156044,"age_ns":2494491}
```

`tlm report --json` (one stage shown; values are nanoseconds):

```
{"count": 2000, "min": 4243.0, "p50": 7181.0, "p90": 9367.7, "p99": 44524.96, "p99.9": 76715.415, "max": 115307.0, "mean": 8011.258}
```

`tlm report` text: the table above, then one histogram per stage with log-spaced bins:

```
end-to-end histogram (log-spaced bins):
    12.16 us -   20.03 us |############################## 1352
    20.03 us -   32.99 us |############                   537
    32.99 us -   54.35 us |#                              57
```

`tlm bench ... --json`: `{"system": {...}, "bench": "evm", "n": 3, "chain_id": 1, "secp256k1_backend": "CoinCurveECCBackend", "stages": {"keccak": {"count": 3, "min": ..., "p50": ..., "max": ...}}}`.

## Dependencies

The core (meter, report, demo, overhead) uses only the standard library. Extras, each only for the
benches:

- `solana`: `solders>=0.18` builds and signs v0 transactions (Rust bindings, the same wire format
  as the chain).
- `evm`: `rlp>=3.0` encodes, `eth-hash[pycryptodome]>=0.5` computes Keccak-256, `eth-keys>=0.4`
  signs with secp256k1.
- `evm-fast`: the same plus `coincurve>=18`, a C backend that `eth-keys` uses automatically. Without
  it signing falls back to a pure-Python backend that is far slower; the bench prints which backend
  ran.
- `test`: everything above plus `pytest` and `eth-account>=0.10` (used only to check that the EVM
  bench produces a transaction that `eth-account` can decode).

If an extra is missing, the bench prints which package to install and exits with code 3.

## Safety

- The benches create a fresh random key in memory for each run. No key is read from or written to
  disk, and nothing is signed with a real key.
- Programs, accounts, recipients, calldata and blockhashes in the benches are random bytes with no
  meaning on any chain. The Solana compute-budget values are placeholders that only give the
  transaction its usual shape.
- There is no network code. The test suite blocks `socket.connect` and fails if anything calls it.
- The demo's "decision" is a parity check on a counter. It is not a strategy.

## Limitations

- Python only. A Python bot's own overhead is visible here; a bot written in Rust or C++ needs its
  own timing.
- A handle must be ended before `capacity` newer events begin, or its ring slot is reused. A handle
  belongs to one thread. An event whose `end()` is never called holds back the flusher until the
  ring laps it; it is then counted in `meter.lost`.
- Each event holds up to 16 marks; extra marks are counted in `meter.dropped_marks` and ignored.
- Event age compares the local wall clock with a remote timestamp, so it is only as accurate as
  the clock sync between the two machines. Do not read it as network latency.
- `perf_counter_ns` cost (tens of nanoseconds) is included in every measurement; the benches do
  not subtract it.
- The benches time library calls from Python. They say nothing about a different implementation of
  the same steps.
- Not yet verified against mainnet or any live system; there is no network path to verify.

## Tests

```
pip install -e '.[test]'
python -m pytest -q
```

Last run in the sandbox above: 31 passed. Tests run offline (`socket.connect` is blocked), use
fixed seeds and a fake clock, and never sleep more than 0.2 s. Bench tests skip cleanly if the
signing libraries are not installed.

## License

MIT. See `LICENSE`.
