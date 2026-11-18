# Relic Solver

[![Version](https://img.shields.io/github/v/tag/Rovetown/relic-solver?label=version)](https://github.com/Rovetown/relic-solver/tags)
[![CI](https://img.shields.io/github/actions/workflow/status/Rovetown/relic-solver/ci-main.yml?branch=main&label=tests)](https://github.com/Rovetown/relic-solver/actions/workflows/ci-main.yml)
[![Python](https://img.shields.io/badge/python-3.14+-blue)](https://www.python.org/)
[![License](https://img.shields.io/github/license/Rovetown/relic-solver)](LICENSE)

Work out the odds of hitting a set of divine relic targets in a single reroll
of [Idle Obelisk Miner](https://apps.apple.com/app/idle-obelisk-miner/id6448125670).
Enter how many chests you have and which relics you want; the answer comes back
as a probability, an expected number of rerolls, and a gem cost.

**[iomreliccalc.me](https://iomreliccalc.me)**

An unofficial tool. Not affiliated with Checkbox Entertainment.

## What it computes

The same question, four ways. Stop at whichever level answers it for you.

**If you have never played.** You open chests. A few of them hold a rare relic.
You want a certain number of certain relics. This works out your chances.

**If you play the game.** Regular chests almost never drop a divine relic: one
in 25,000. Divine chests always drop one. Which relic you get depends on how
many you already hold, because new kinds unlock as your total grows and each
kind stops dropping once it hits its cap. So the order the drops arrive in
changes the answer, and you cannot get there by multiplying a few numbers
together.

**If you have met probability before.** Each drop moves you from one state to
another, where a state is how many of each of the five relic types you hold.
That is a Markov chain. Some states are winning states, and once you reach one
you stay in it, because relic counts only ever go up. Walk the chain forward,
adding up the probability that lands in a winning state, and you have the
answer for a fixed number of drops. The number of drops is itself random, so
weight each possible count by how likely it is and add those up too.

**If you want the implementation.** A forward walk over an absorbing Markov
chain held in a dense 4D array indexed by the D2 to D5 counts, with D1 implied
by the step number minus the rest. Transitions are slice-and-shift along each
axis against per-tier uniform weights; absorption is a boolean mask. The outer
sum weights the cumulative absorbed mass at each step by the Binomial(n,
1/25000) PMF, truncated at the `ppf` of `1 - 1e-15`.

## Game mechanics

### Divine drops

- Regular relic chests have a **1 in 25,000** chance of producing a divine relic.
- Divine chests produce exactly one each.
- Rerolling resets everything. Divines accumulate only within a single reroll.

### Unlock thresholds

Five relic types, unlocked by the **total** divines accumulated so far:

| Total divines | Types available | Newly unlocked |
|:-------------:|-----------------|----------------|
| 0 | D1 | Rainbow Floor Chance |
| 3 | D1, D2 | Supernova Multiplier |
| 6 | D1 to D3 | Rainbow Floor Multiplier |
| 10 | D1 to D4 | Fishing Ticks 5x Chance |
| 30 | D1 to D5 | Rainbow Void Portal Chance |

Thresholds are checked **before** each drop, which costs people a reroll more
often than anything else here. With exactly three divine chests, all three land
on D1: the totals seen beforehand are 0, 1 and 2, and none of them has reached
3. A type needs **threshold + 1** divines before it can receive its first drop,
so D2 needs four, not three.

### Obelisk level

Divines owned are not the only gate. Your Obelisk level gates the same types,
and **both** gates must be open before a type can drop:

| Type | Divines owned | Obelisk level |
|------|:-------------:|:-------------:|
| D1 Rainbow Floor Chance | 0 | none |
| D2 Supernova Multiplier | 3 | 23 |
| D3 Rainbow Floor Multiplier | 6 | 25 |
| D4 Fishing Ticks 5x Chance | 10 | 37 |
| D5 Rainbow Void Portal Chance | 30 | 64 |

Obelisk level does not change inside a reroll, so it is a fixed ceiling on the
unlock tier rather than a per-drop check. A target on a type your level locks
out is impossible, and the solver returns 0 for it without walking the chain.
Locking the higher types can make a lower target **more** likely, because the
drops that would have gone to them land on what is left.

The page offers the level as five bands, one per threshold: below 23, 23 to 24,
25 to 36, 37 to 63, and 64+, and starts on the lowest. `obelisk_level` is a
required field of the `/solve` body: a request without it is answered with
`400 Missing fields`, because a level the caller never stated cannot be
guessed without changing the answer.

### Caps

D1 is uncapped. D2 to D5 share one configurable cap, between 5 and 36. A type
that reaches the cap leaves the drop pool, and the types still in the pool
share its probability equally.

### Cost

A reroll costs 200 gems. Expected cost is `ceil(expected_rerolls) * 200`,
rounded up because you cannot buy part of a reroll.

## How the solver works

[`src/relic_solver/solver.py`](src/relic_solver/solver.py).

**Bound the random part.** Divines from regular chests follow Binomial(n,
1/25000). Rather than loop over every chest, the solver asks SciPy for the
smallest `k_max` with `P(K <= k_max) >= 1 - 1e-15`. For 150,000 chests that is
about 25 possible counts instead of 150,000.

**Walk the chain.** Each drop is one step. For every live state, work out which
types are unlocked by divines owned and by Obelisk level and still under the
cap, split the state's probability equally between them, and move it.

**Absorb the winners.** A state that meets the target in every dimension is
removed and its probability added to a running total. This is safe because
counts only increase, so every descendant of a winning state also wins. It is
also what stops the state space exploding.

**Weight and sum.** After `d` total drops the result takes on
`P(K = k) * absorbed(d)`. Weighting the cumulative absorbed mass at each step
is equivalent to tracking when each state was first absorbed, without having
to track it.

### Two implementations

`_solve_numpy` is the default: one dense array of shape `(cap+1)^4`, with
transitions as array slices rather than a loop over states. `_solve_dict` is
the original per-state version, kept because two implementations that agree
are evidence and one is an assertion. Thirteen parametrised tests check they
agree to within `1e-12`.

Measured at cap 21 with 2 million chests, the array version takes about 500 ms
against 105 s for the dict version.

## Technical detail

Everything above is the whole story. What follows is the same material drawn
out, for anyone who wants to see the shape of it rather than read about it.

<details>
<summary><b>How a reroll plays out</b></summary>

#### Reroll flow

```mermaid
%%{init: {'theme': 'dark'}}%%
flowchart TD
    REROLL(["Player rerolls (200 gems)"]) --> RESET["Everything resets
    Divine counts = 0
    Relic types locked"]

    RESET --> CHESTS{"Chest type?"}

    CHESTS -- "Regular relic chest" --> DIVINE_ROLL{"Roll $$\color{#7fdbff}\frac{1}{25{,}000}$$"}
    CHESTS -- "Divine chest" --> GUARANTEED["Guaranteed
    divine relic"]

    DIVINE_ROLL -- "$$\color{#7fdbff}\frac{24{,}999}{25{,}000}$$" --> NOTHING["No divine relic
    from this chest"]
    DIVINE_ROLL -- "$$\color{#7fdbff}\frac{1}{25{,}000}$$" --> DROP["Divine relic drop"]
    GUARANTEED --> DROP

    DROP --> TOTAL["Increment total
    divine count"]
    TOTAL --> UNLOCK{"Check unlock
    thresholds"}

    UNLOCK --> POOL["Build available
    drop pool"]
    POOL --> CAP_CHECK{"Check caps
    for D2-D5"}
    CAP_CHECK --> EQUAL["Equal probability
    $$\color{#7fdbff}P(\text{type}_i) = \frac{1}{|\text{pool}|}$$"]
    EQUAL --> ASSIGN["Assign relic type
    D1, D2, D3, D4, or D5"]
    ASSIGN --> INCREMENT["Increment that
    relic type's count"]

    INCREMENT --> MORE{"More chests
    to open?"}
    NOTHING --> MORE
    MORE -- "Yes" --> CHESTS
    MORE -- "No" --> FINAL["Final divine
    relic counts"]
```

#### Unlock thresholds

```mermaid
%%{init: {'theme': 'dark'}}%%
flowchart LR
    T0["$$\color{#7fdbff}\geq 0$$ divines
    D1 only"] --> T1["$$\color{#7fdbff}\geq 3$$ divines
    D1, D2"] --> T2["$$\color{#7fdbff}\geq 6$$ divines
    D1-D3"] --> T3["$$\color{#7fdbff}\geq 10$$ divines
    D1-D4"] --> T4["$$\color{#7fdbff}\geq 30$$ divines
    All 5 types"]
```

Thresholds are checked *before* each drop. With exactly 3 divine chests,
all 3 land on D1 (totals seen: 0, 1, 2). D2 needs at least **4** divines
to receive its first drop, not 3.

#### Cap system

```mermaid
%%{init: {'theme': 'dark'}}%%
flowchart TD
    DROP_TYPE{"Which type
    was dropped?"} --> D1_CHECK{"D1?"}
    DROP_TYPE --> DX_CHECK{"D2-D5?"}

    D1_CHECK -- "Yes" --> UNCAPPED["D1 is UNCAPPED
    No limit on count"]

    DX_CHECK -- "Yes" --> CAP_VAL{"$$\color{#7fdbff}\text{count} \lt \text{cap}$$?
    (cap range: 5-36)"}
    CAP_VAL -- "Yes" --> ACCEPT["Accept drop
    Increment count"]
    CAP_VAL -- "No (at cap)" --> REMOVE["Remove type from
    drop pool"]
    REMOVE --> REDISTRIBUTE["Remaining types share
    $$\color{#7fdbff}P = \frac{1}{|\text{pool}| - 1}$$"]
```

#### Example walkthrough

**Setup**: 10 divine chests, cap = 5, targets = (0, 2, 0, 0, 0)

| Drop # | Total before | Available pool | Drop lands on | State (D1-D5) |
|:------:|:------------:|----------------|:-------------:|:-------------:|
| 1 | 0 | D1 | D1 | (1,0,0,0,0) |
| 2 | 1 | D1 | D1 | (2,0,0,0,0) |
| 3 | 2 | D1 | D1 | (3,0,0,0,0) |
| 4 | 3 | D1, D2 | D2 (50%) | (3,1,0,0,0) |
| 5 | 4 | D1, D2 | D1 (50%) | (4,1,0,0,0) |
| 6 | 5 | D1, D2 | D2 (50%) | (4,2,0,0,0) |
| 7 | 6 | D1, D2, D3 | D1 (33%) | (5,2,0,0,0) |
| ... | | | | Target met at drop 6 |

This is one possible path. The solver computes the probability across
**all** possible paths simultaneously using the Markov chain.

</details>

<details>
<summary><b>System architecture</b></summary>

```mermaid
%%{init: {'theme': 'dark'}}%%
C4Container
    title Relic Solver - Container Diagram

    Person(player, "Player", "Idle Obelisk Miner player calculating divine relic drop odds")

    Container_Boundary(platform, "Heroku (EU region)") {
        Container(app, "Web Application", "Flask + gunicorn", "Routes, LBYL validation, NDJSON streaming, rate limiting, CSP with hashed inline styles")
        Container(solver, "Solver Library", "NumPy + SciPy", "4D Markov chain with absorbing states, binomial weighting, expected rerolls and gem cost")
        Container(config, "Game Config", "Python module", "Divine chance 1/25000, unlock thresholds, Obelisk thresholds, caps 5-36, relic names")
    }

    ContainerDb_Ext(redis, "Redis Cloud", "Redis 30 MB", "Deterministic result cache, LRU eviction, no TTL")
    System_Ext(edge, "Cloudflare", "Free plan: TLS termination, static cache, www to apex redirect")

    Rel(player, edge, "Page, assets, POST /solve", "HTTPS")
    Rel(edge, app, "Whatever it cannot serve from cache", "HTTPS, Full (Strict)")
    Rel(app, edge, "NDJSON stream", "HTTPS")
    Rel(edge, player, "Cached assets and streamed results", "HTTPS")
    Rel(app, solver, "solve(), expected_rerolls(), expected_gems()")
    Rel(solver, config, "Imports constants")
    Rel(app, redis, "GET / SET cache key", "TCP")

    UpdateRelStyle(player, edge, $textColor="#7fdbff", $lineColor="#7fdbff", $offsetY="10", $offsetX="-90")
    UpdateRelStyle(edge, app, $textColor="#7fdbff", $lineColor="#7fdbff", $offsetY="-20")
    UpdateRelStyle(app, edge, $textColor="#a0203a", $lineColor="#a0203a", $offsetX="40")
    UpdateRelStyle(edge, player, $textColor="#a0203a", $lineColor="#a0203a", $offsetX="40")
    UpdateRelStyle(app, solver, $textColor="#f8f8f2", $lineColor="#bd93f9", $offsetY="-10")
    UpdateRelStyle(solver, config, $textColor="#f8f8f2", $lineColor="#bd93f9", $offsetY="-10")
    UpdateRelStyle(app, redis, $textColor="#ffb86c", $lineColor="#ffb86c", $offsetX="-20")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

| Path | Protocol | Notes |
|------|----------|-------|
| Browser to Cloudflare | HTTPS (edge TLS termination) | JSON request, NDJSON response |
| Cloudflare to Flask | HTTPS, Full (Strict) | Cache miss, or anything uncacheable |
| Flask to Redis | TCP (REDISCLOUD_URL) | Deterministic cache, no TTL |
| Flask to Solver | In-process function call | Worker thread for long solves |
| Browser to Cloudflare (static) | HTTPS, served from the edge cache | Scripts, fonts and images, all same-origin; the stylesheet is inlined in the page |

</details>

<details>
<summary><b>The solver, step by step</b></summary>

The solver computes:

$$P(\text{success}) = \sum_{k=0}^{k_{\max}} P(K = k) \cdot P(\text{target met} \mid d_{\text{divine}} + k \text{ total drops})$$

where $K \sim \text{Binomial}(n, p)$ is the random divine count from $n$
regular chests at $p = \frac{1}{25{,}000}$ per chest.

```mermaid
%%{init: {'theme': 'dark'}}%%
flowchart TD
    START([solve called]) --> VALIDATE

    subgraph Validation
        VALIDATE[Validate inputs
        len targets = 5
        chests >= 0, divines >= 0]
        VALIDATE --> CLAMP["Clamp D2-D5 targets
        to relic_cap"]
        CLAMP --> TRIVIAL{All targets
        are zero?}
        TRIVIAL -- Yes --> RETURN_1["Return 1.0"]
    end

    TRIVIAL -- No --> BINOM

    subgraph Binomial Precomputation
        BINOM["Compute $$\color{#7fdbff}k_{\max}$$
        via $$\color{#7fdbff}\text{ppf}(1 - 10^{-15},\; n,\; p)$$
        Tightest upper bound on
        random divine count"]
        BINOM --> PMF["Vectorized PMF
        $$\color{#7fdbff}P(K = k) = \binom{n}{k} p^k (1-p)^{n-k}$$
        One scipy call for $$\color{#7fdbff}k = 0 \ldots k_{\max}$$"]
        PMF --> DMAX["$$\color{#7fdbff}d_{\max} = d_{\text{divine}} + k_{\max}$$"]
    end

    DMAX --> ZERO_CHECK{"$$\color{#7fdbff}d_{\max} = 0$$?"}
    ZERO_CHECK -- Yes --> RETURN_0["Return 0.0"]
    ZERO_CHECK -- No --> INIT

    subgraph NumPy 4D State Array
        INIT["Allocate prob array
        shape $$\color{#7fdbff}(\text{cap}+1)^4$$
        axes = D2, D3, D4, D5
        D1 count is implicit"]
        INIT --> GRIDS["Coordinate grids via mgrid
        + static absorption mask
        + per-type cap masks"]
        GRIDS --> TIERS["Build 5 tier weight arrays
        $$\color{#7fdbff}w_{\text{tier}}(s) = \frac{1}{n_{\text{avail}}(s)}$$
        per state per unlock tier"]
    end

    TIERS --> STEP

    subgraph Markov Chain Walk
        STEP["Select unlock tier
        from total divines
        vs thresholds, then
        clamp to the Obelisk tier"]
        STEP --> WEIGHT["Weight probability
        $$\color{#7fdbff}\text{weighted} = \text{prob} \cdot w_{\text{tier}}$$"]
        WEIGHT --> D1["D1 transition
        new_prob = weighted.copy
        State unchanged"]
        D1 --> SHIFT["D2-D5 transitions
        Slice-and-shift per axis
        $$\color{#7fdbff}\text{arr}[1\!:] \mathrel{+}= \text{arr}[:\!-1]$$
        Only for unlocked types"]
        SHIFT --> ABSORB["Absorption
        $$\color{#7fdbff}d_1 = \text{step} - \sum_{i=2}^{5} d_i$$
        Zero out states where
        all targets are met"]
        ABSORB --> ACCUM["Accumulate
        $$\color{#7fdbff}\text{result} \mathrel{+}= P(K\!=\!k) \cdot \text{absorbed}$$"]
        ACCUM --> EARLY{All mass
        absorbed?}
        EARLY -- Yes --> TAIL["Sum remaining
        binomial tail"]
        EARLY -- No --> TIMEOUT{Deadline
        exceeded?}
        TIMEOUT -- Yes --> ERROR[Raise TimeoutError]
        TIMEOUT -- No --> NEXT{"$$\color{#7fdbff}\text{step} \lt d_{\max}$$?"}
        NEXT -- Yes --> STEP
    end

    NEXT -- No --> RESULT
    TAIL --> RESULT
    RESULT[["Return $$\color{#7fdbff}\min(\text{result},\; 1.0)$$"]]
    RETURN_1 --> DONE([Done])
    RETURN_0 --> DONE
    RESULT --> DONE
```

| Input range | Behavior |
|-------------|----------|
| 0 chests, 0 divines | Returns 0.0 immediately ($d_{\max} = 0$) |
| All-zero targets | Returns 1.0 immediately (trivial case) |
| Small inputs (< 10K chests) | Dict solver would be faster (~70us overhead from array allocation) |
| Typical inputs (10K-500K) | NumPy solver handles in < 100ms |
| Measured at cap 21, 2M chests | ~500ms, against 105s for the dict solver |

</details>

<details>
<summary><b>What happens when you press Run Solver</b></summary>

```mermaid
%%{init: {'theme': 'dark'}}%%
sequenceDiagram
    actor User
    participant Browser as Browser (solver.js)
    participant Flask as Flask (app.py)
    participant Redis as Redis (Cache)
    participant Solver as Solver (solver.py)

    User->>Browser: Fill form, click Calculate
    Browser->>Browser: Build JSON payload<br/>{chests, divines, cap, targets}

    Browser->>Flask: POST /solve<br/>Content-Type: application/json<br/>If-None-Match: "etag" (if cached)

    Note over Flask: Rate limit check<br/>10/minute per IP

    Flask->>Flask: Validate input (LBYL)<br/>Type checks, range checks

    alt Validation fails
        Flask-->>Browser: 400 JSON {error: "..."}
        Browser->>Browser: Show error message
    end

    Flask->>Flask: Normalize D2-D5 targets<br/>min(target, relic_cap)
    Flask->>Flask: Build cache key<br/>solve:{chests}:{divines}:{cap}:{obelisk}:{targets}

    Flask->>Redis: GET cache_key

    alt Cache hit + ETag match
        Redis-->>Flask: Cached result
        Flask-->>Browser: 304 Not Modified
        Browser->>Browser: Use local ETag cache
    else Cache hit (no ETag)
        Redis-->>Flask: Cached result
        Flask-->>Browser: NDJSON {type: result, cached: true}
        Browser->>Browser: Display results
    else Cache miss
        Redis-->>Flask: null

        Flask->>Solver: Start worker thread<br/>solve(chests, divines, targets,<br/>cap, obelisk_level, progress_callback)

        loop Every ~1% progress
            Solver-->>Flask: progress_callback(step, total)
            Flask-->>Browser: NDJSON {type: progress, percent: N}
            Browser->>Browser: Update progress bar
        end

        Note over Flask,Browser: Keepalive every 20s<br/>prevents Heroku 30s timeout

        Solver-->>Flask: probability
        Flask->>Flask: expected_rerolls(prob)<br/>expected_gems(prob)

        Flask->>Redis: SET cache_key (fire-and-forget)

        Flask-->>Browser: NDJSON {type: result,<br/>probability, rerolls, gems,<br/>solve_time_ms}
        Browser->>Browser: Store ETag for future 304s
    end

    User->>Browser: See probability,<br/>expected rerolls, gem cost
```

#### NDJSON message types

| Type | Fields | When sent |
|------|--------|-----------|
| `progress` | `percent` (0-100) | Every ~1% of Markov chain steps |
| `progress` | `percent: -1` | Keepalive (every 20s if solver is slow) |
| `result` | `probability`, `expected_rerolls`, `expected_gems`, `solve_time_ms` | Solver finished |
| `result` | Same + `cached: true` | Cache hit (single line, no progress) |
| `error` | `error` (string) | Solver raised ValueError or TimeoutError |

#### Caching strategy

```mermaid
%%{init: {'theme': 'dark'}}%%
flowchart TD
    REQ["Incoming /solve request"] --> NORMALIZE["Normalize targets
    D2-D5 clamped to cap"]
    NORMALIZE --> KEY["Build key
    solve:chests:divines:cap:d2,d3,d4,d5"]
    KEY --> REDIS_GET{"Redis GET"}

    REDIS_GET -- "Hit" --> ETAG_CHECK{"ETag match?"}
    ETAG_CHECK -- "Yes" --> R304["304 Not Modified
    No body transferred"]
    ETAG_CHECK -- "No" --> CACHED_RESPONSE["Return cached result
    {cached: true}"]

    REDIS_GET -- "Miss" --> SOLVE["Run solver"]
    SOLVE --> REDIS_SET["Redis SET
    fire-and-forget, no TTL"]
    REDIS_SET --> STREAM["Stream result
    to browser"]

    REDIS_GET -- "Redis down" --> SOLVE
```

</details>

## Running it locally

**Needs:** Python 3.14+, [uv](https://docs.astral.sh/uv/),
[Node.js](https://nodejs.org/) for the CSS and JS build, and
[just](https://github.com/casey/just) to drive the recipes.

```sh
just sync     # uv sync + npm install
just dev      # build assets, then run on http://127.0.0.1:5000
just test     # the Python suite
just --list   # everything else
```

Run the dev server through `just dev` rather than `flask run`. It passes
`--debug`, and without it Flask caches templates in memory and will serve you
markup from before your last edit.

Redis is optional. Without it the result cache and the rate limiter both fall
back to in-process storage, which is fine for development and wrong for
production, where every worker would keep its own counters.

## Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) covers the test suites, project layout,
  commit conventions and pre-commit hooks.
- [DEPLOYMENT.md](DEPLOYMENT.md) covers Heroku, the environment variables and
  the deploy commands.

## Author

**Rovetown** ([@Rovetown](https://github.com/Rovetown))

Issues and pull requests are welcome at
[the issues page](https://github.com/Rovetown/relic-solver/issues).

## License

Copyright 2026 [Rovetown](https://github.com/Rovetown).
[MIT](LICENSE) licensed.
