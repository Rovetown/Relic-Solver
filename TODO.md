# TODO - Relic Solver

> **Last Updated**: 2026-10-23

---

### README & Branding

> **Resolved 2026-10-24: the README 2.0 rewrite landed in `9f72a93`.** 631 lines
> to 156, with the shields.io badges and the Ko-fi badge folded in, which closes
> both items that lived here.
>
> Three things were removed rather than updated, per the brief: a "full
> documentation (coming soon)" link pointing at `#`, the documentation-yes badge
> making the same claim, and the mermaid diagrams, which restated the prose at
> greater length. Three were stale and are corrected: the cap range read 5-21
> and has been 5-36 since `c12c10f`, four of seven dependency versions had
> drifted, and the container diagram still described CSP nonce headers that
> `b9817d6` replaced with hashes. Node was added as a prerequisite, which it has
> been since the asset build landed.

### Frontend

> **Resolved 2026-10-23: the fonts are subsetted; the CSS was already inlined.**
>
> **Lever 1 - font subsetting. Done.** `scripts/subset_fonts.py` (recipe:
> `just subset-fonts`) cuts the three WOFF2 files to printable ASCII plus the
> four non-ASCII code points the page can actually produce and the fonts
> actually contain: U+00A0, U+2013, U+2014, U+2026. A scan of every template,
> stylesheet, script, data file and HTML entity found nothing else. U+2192 and
> U+2500 appear in source comments only and no font in this set has a glyph for
> them, so they fell back to a system font before and still do.
>
> | Font | Before | After |
> |------|--------|-------|
> | `pixelify-sans-latin.woff2` | 12,016 B | 7,580 B |
> | `press-start-2p-latin.woff2` | 12,512 B | 6,956 B |
> | `share-tech-mono-latin.woff2` | 13,500 B | 7,480 B |
>
> On the wire the three went from 40,980 B to 24,964 B, and the cold page from
> 78,618 B to 62,607 B - **20.4% of the page gone, 39% of the font bytes.**
> Verified: all 99 required glyphs present in each file, Pixelify Sans keeps its
> `fvar` table so `font-weight: 400 700` still varies, GPOS kerning survives, and
> every `name` record including the OFL copyright is byte-identical to upstream.
> A full-page screenshot at 2x device scale is **pixel-identical** to the same
> page rendered with the original fonts: 0 differing pixels out of 8,192,000.
> Originals kept in `assets/font-sources/`, which never ships.
>
> **Lever 2 - critical CSS inlining. Already done, before this item was written.**
> `index.html` inlines `style.min.css` through `inline_asset` with the CSP nonce,
> and falls back to a `<link>` only when the build artifact is missing. That is
> why `render-blocking-resources` scores 1 with an empty item list. The 8 s render
> delay is not a stylesheet hop.
>
> **What the saving did not do: move the slow-3G score.** It stayed at 56. At a
> 2000 ms round trip the score is set by round trips, not bytes - repeated runs of
> the identical build return LCP 14 s and 16 s at random, which is Lighthouse's
> simulation quantising to whole round trips. Mobile slow-4G LCP did improve, 1.4 s
> to 1.2 s. The 20% lighter page is a real win for metered and bandwidth-limited
> visitors; it is simply not what the 3G *score* measures.
>
> **Two caveats on those 3G numbers.** They were taken against a local waitress
> server, which speaks HTTP/1.1, while production negotiates HTTP/2 - so the 22
> requests queue in the measurement and multiplex in reality. And 6002 ms of the
> LCP is TTFB, which is distance. Only the CDN item below changes that.

- [ ] Integrate content from RelicSolverWiki project (separate repo or add to dev repo)
      - **blocked on a licensing and rate question, not on code.** The wiki is hosted on
      Miraheze, so before any fetching happens the owner needs to establish what the
      wiki's own content licence permits for reuse, and what Miraheze's terms allow in
      the way of automated requests. Miraheze runs MediaWiki, which means
      `api.php?action=query` exists and is the supported path; scraping rendered HTML is
      the path that gets rate-limited and is the one to avoid. Re-open once the answer
      is known.

### Deployment & Domains

- [ ] **Put Cloudflare in front of the whole site** - revised 2026-10-23 after
      reading the live Namecheap zone and Cloudflare's import scan. Not started;
      three things have to be fixed before the nameservers move.

  **Current state.** Static responses come straight off the dyno: `server: Heroku`,
  `via: 1.1 heroku-router`, and no `cf-cache-status`, `x-cache` or `age` header at
  all. Of the 20 requests a cold load makes, 18 hit the origin.

  **Whole site, not an asset-only hostname.** The original framing of this item was
  "a CDN in front of the app's own static files", which implied a second hostname
  such as `cdn.iomreliccalc.me` serving `/static/` while the apex kept going
  straight to Heroku. That is the wrong shape here:

  - The measured problem is **TTFB, 6002 ms of a 14 s LCP on slow 3G** - the HTML's
    own round trips. An asset hostname does not touch the HTML, so the number does
    not move.
  - A second origin costs a fresh DNS lookup, TCP handshake and TLS handshake
    before the first asset can start. On a high-latency link that is more added
    latency than the cached bytes save.
  - It also means CORS for the fonts, the extra host in four CSP directives, and a
    second cache key, certificate and failure surface to watch.

  Cloudflare's free tier is a DNS-level reverse proxy, not a pull-zone: traffic is
  cached only where it already flows through the edge. Proxying the apex gets the
  asset caching *and* the TTFB fix in one move, and `/solve` can still be carved
  out onto a grey-clouded subdomain later if it ever needs to be.

  **Who it actually helps.** Anyone far from the dyno's single region - which
  here is the EU (Cedar, `heroku-26`), so European visitors already sit close to
  the origin and gain the least. The gain is largest for everyone else. A visitor in
  Australia pays roughly 250-300 ms per round trip to a US or EU dyno and the page
  needs several before the `h1` paints; with an edge in their city the handshakes
  are local and only a cache miss crosses the ocean, over Cloudflare's own
  backbone. Mobile users on high-latency carriers gain the most. The dyno also
  stops spending its two workers on sprite requests.

  **The 100-second cap is handled.** Cloudflare's free plan abandons an origin
  request after 100 s and serves its own `524`. `SOLVE_MAX_SECONDS` dropped from
  600 to 90 and the gunicorn `--timeout` from 620 to 120 (`Procfile`, `Dockerfile`,
  `src/relic_solver/config.py`), so the app's own error frame always arrives first
  and the edge never gets the chance to answer in our place.

  **Two faults to fix before the nameservers move.**

  1. **The two Heroku targets are pasted into both hosts.** Heroku issues one
     DNS target per custom domain, and this app's Domains table reads:

     | Domain | DNS target | ACM |
     |--------|------------|-----|
     | `iomreliccalc.me` | `still-finch-7hnub56njj8qhw11nq165i90.herokudns.com` | Ok |
     | `www.iomreliccalc.me` | `deep-lotus-ghqxpf5gy41q7zo09z42pw2a.herokudns.com` | Ok |

     One app, two domains, two targets - that is the normal arrangement, not two
     apps. (An earlier version of this entry read it as two apps round-robining.
     That was wrong and is corrected here.) The actual fault is that Namecheap
     holds *both* targets at `@` **and** both at `www`, so half of all apex
     lookups return the `www` target and vice versa. It works today only because
     both targets land on the same Heroku routing layer, which dispatches on the
     `Host` header - untidy rather than broken, which is why nothing has visibly
     failed. Delete the apex ALIAS pointing at `deep-lotus-…` and the `www`
     CNAME pointing at `still-finch-…`, leaving exactly one record per host.

  2. **Cloudflare's scan flattened the ALIAS into four static A records**
     (`99.83.217.1`, `75.2.43.161`, `76.223.11.49`, `15.197.129.158`). Those are
     the AWS Global Accelerator addresses Heroku's DNS resolves to today; they
     are not ours and Heroku rotates them without notice. Delete all four and
     create a single proxied CNAME `iomreliccalc.me` ->
     `still-finch-7hnub56njj8qhw11nq165i90.herokudns.com`. Cloudflare's CNAME
     flattening makes a CNAME legal at the apex and re-resolves it continuously,
     which is exactly what Namecheap's ALIAS does now. The `www` CNAME
     Cloudflare imported already points at `deep-lotus-…`, which is correct;
     leave it proxied.

  3. **The `thbwocoajmxu` CNAME must not be proxied.** It points at
     `gv-b7txv537cjhmpm.dv.googlehosted.com`, a Google site-verification record.
     A verification lookup has to return Google's value, not Cloudflare's proxy
     address. Set it to DNS only.

  The MX records (`eforward1-5.registrar-servers.com`) and the SPF TXT came across
  as DNS only, which is correct - leave them. DNSSEC is off at Namecheap: keep it
  off through the move, then optionally enable it in Cloudflare afterwards.

  **Mail is not used on this domain (confirmed 2026-10-23, forwarding disabled
  at Namecheap).** So the five `eforward1-5.registrar-servers.com` MX records can
  be deleted in Cloudflare rather than migrated. Replace the forwarding SPF TXT
  with `v=spf1 -all` and add a `_dmarc` TXT of `v=DMARC1; p=reject;` - with no
  mail to protect, both records exist purely to stop the domain being used as a
  spoofed sender. Keep the `thbwocoajmxu` Google verification CNAME unless it is
  known to be stale; it is harmless and deleting it loses whatever it verifies.

  **Both HTTPS layers stay.** Cloudflare's "Always Use HTTPS" redirects at the
  edge and saves the round trip to the dyno, but `FORCE_HTTPS` stays set on
  Heroku: the origin is still reachable directly through its `herokudns.com`
  target, and the app's own redirect is the only thing covering that path.
  Behind Full (Strict) the app redirect never fires anyway, because
  `request.is_secure` is already True, so it costs nothing. Note that HSTS at
  `app.py:373` is gated on `request.is_secure` rather than on `force_https`, so
  the two are independent. Leave Cloudflare's own HSTS setting off; the origin
  already sends the header and one source of truth is enough.

  **The Heroku ACM certificate stays too - Full (Strict) requires it.** The two
  certificates do different jobs: Cloudflare's Universal SSL secures visitor to
  edge, Heroku's ACM secures edge to dyno. Removing ACM breaks the second hop and
  Cloudflare answers 526. Watch the ACM status after cutover; if renewal ever
  starts failing, grey-cloud the record long enough for it to renew, then
  re-proxy.

  **Cloudflare's "only allow Cloudflare IPs at your origin" step does not apply
  to Heroku.** There is no firewall to configure on a dyno, so the origin stays
  reachable directly through its `herokudns.com` target by anyone who finds it.
  For a public calculator with no accounts that is an acceptable exposure. The
  approximation, if it ever matters, is Cloudflare Authenticated Origin Pulls or
  a shared secret header checked in `before_request`.

  **Order of operations.** Fix fault 1 at Namecheap first and confirm the site is
  served by one app. Then correct the Cloudflare zone (faults 2 and 3), set
  SSL/TLS to **Full (Strict)** *before* any traffic moves, and only then change the
  nameservers at Namecheap. Keep the Namecheap record list as the rollback sheet;
  do not delete it.

  **Getting the Heroku DNS target without the CLI.** Heroku Dashboard -> the app
  -> Settings -> Domains. The table lists each custom domain with its DNS Target,
  which is the same string `heroku domains` prints. Both targets are already
  visible in the Namecheap zone, so the only open question is which app is live -
  open each app's Domains table to find out.

  **After cutover, four app-level checks.**
  - `ProxyFix(x_proto=1)` at `app.py:198` should stay correct under Full (Strict),
    because both hops are then HTTPS and `X-Forwarded-Proto` reads `https` either
    way. It is the *Flexible* SSL mode that breaks it: Cloudflare would speak
    plain HTTP to Heroku, `request.is_secure` would be False, `_redirect_to_https`
    would bounce to HTTPS, and the result is an infinite loop. Confirm `is_secure`
    after cutover anyway.
  - `app.py:752` answers every `/.well-known/<path>` probe with 204. Heroku's
    router intercepts ACM's `/.well-known/acme-challenge/` before it reaches the
    dyno, which is why ACM reads Ok today, but if certificate renewal ever fails
    after cutover this route is the first suspect and a pass-through for
    `acme-challenge` is the fix.
  - ~~The rate limiter keys on client IP.~~ **Done 2026-10-24.** `_client_address`
    in `app.py` replaces `get_remote_address` as the limiter's key function: it
    reads `CF-Connecting-IP`, but only when the request's own peer address falls
    inside Cloudflare's published ranges, which are baked into `_CLOUDFLARE_CIDRS`
    from the live API. A missing header, an unparsable one, or a peer outside
    those ranges all fall back to the socket address, so a request sent straight
    to the `herokudns.com` target cannot rewrite its own rate-limit bucket.
    `scripts/check_cloudflare_ips.py` (`just check-cloudflare-ips`, and a
    non-blocking step in the weekly DNS workflow) reports drift between the baked
    list and Cloudflare's published one. 21 tests cover it.
  - A cache rule for `/static/` set to *use the origin's cache-control*, since the
    assets already send a one-year `immutable` `max-age` with `?v=<hash>` busting.
  - HTML capped at the 300 s `max-age` it already sends, so a deploy is visible
    within five minutes.

  **What it costs.** Nothing in money - unmetered bandwidth on the free plan, and
  Heroku custom domains and ACM certificates are already included. What it costs
  instead: a new single point of failure, no SLA, community-only support,
  Cloudflare terminating TLS so they see plaintext requests, DNS administration
  moving out of Namecheap, and some networks and countries that degrade or block
  Cloudflare.

> **Resolved 2026-10-23: the edge negotiates HTTP/2.** Measured from the owner's
> machine against the live host:
>
> ```sh
> openssl s_client -alpn h2 -connect iomreliccalc.me:443 </dev/null 2>/dev/null | grep ALPN
> ```
>
> reports `ALPN protocol: h2`. The `curl` on that machine has no `--http2` or `--http3`
> option at all - it is built without nghttp2 - and without those flags it reports
> `1.1`, which is the client's own default and says nothing about the server. ALPN is
> the authoritative reading here; curl's was the useless one, the same way it was when
> this item was first written.
>
> **What it settles.** The page makes 19 same-origin requests. Under HTTP/1.1 those
> queue behind a six-connection-per-origin limit; under HTTP/2 they multiplex over one
> connection and the request count stops mattering much. So "minimize HTTP requests" is
> not worth effort on this app, and no Router 2.0 feature flag is needed - it is already
> on. Nothing in the codebase sees or influences this: `app.py`, all three JS files,
> `src/relic_solver/`, both Procfiles and `compose.yml` contain no reference to HTTP
> versions, ALPN or protocol negotiation, and gunicorn speaks HTTP/1.1 to the router
> either way.


> **Gated on the Cloudflare decision (2026-10-23).** If the site goes behind
> Cloudflare, this is a redirect rule at the edge and costs the visitor nothing
> extra. If it does not, it is the `before_request` hook described below. Do not
> build the hook until that choice is made.

- [ ] **Redirect `www.iomreliccalc.me` to the apex host** - hygiene rather than an
      emergency, since the canonical tag already papers over it.

  **Current state.** Both hosts answer `200` with identical content:
  `https://iomreliccalc.me/` and `https://www.iomreliccalc.me/`. Plain HTTP on both
  already `308`s to HTTPS, so the only gap is that the two HTTPS hosts never converge.

  **Why bother.** The canonical tag added in `index.html` points both at the apex, so
  search engines will consolidate the ranking signals on their own - this is not an SEO
  fire. What a redirect buys on top of that: one set of CDN and browser cache entries
  instead of two, analytics that do not split the same visitor across two hostnames,
  no chance of a shared link pinning someone to the non-canonical host, and no reliance
  on a crawler honouring a hint when an HTTP-level answer is available.

  **Where it goes.** Heroku's router cannot do host-based redirects, so this is either
  app code or a DNS/CDN layer we do not currently run. In-app is the cheaper option: a
  `before_request` hook beside `_redirect_to_https` (`app.py:331`), gated on a new
  `CANONICAL_HOST` env var, issuing a `308` so the method and body survive the hop the
  same way the HTTPS redirect does.

  **Cost.** None. Heroku custom domains cost nothing extra and ACM certificates are
  included on the paid dynos this app already runs. Both hosts serve valid TLS today,
  which means both are already registered with ACM - no new add-on, no new bill.

  **What could break.**
  - The hook must compare against `request.host`, which ProxyFix (`app.py:198`)
    populates from `X-Forwarded-Host`. Comparing against the raw socket host instead
    would redirect every single request and loop forever.
  - It has to run after (or fused with) `_redirect_to_https`, otherwise an
    `http://www` request pays two redirects instead of one.
  - HSTS is set with `includeSubDomains`, so `www` must keep serving valid TLS even
    once it only ever redirects. Note the opposite approach - deleting the `www`
    domain from Heroku rather than redirecting it - would hard-break every existing
    `www` link, because HSTS forbids the browser from falling back to plain HTTP.
  - Must no-op when `CANONICAL_HOST` is unset, or local dev on `127.0.0.1:5000`
    would redirect to production.
  - Needs its own tests: apex passes through, `www` redirects once with `308`, and
    the unset-config case does nothing.

> **Dropped 2026-10-23: `/solve` will not report per-field validation errors.**
> The browser validates all eight inputs against the same `min`/`max` the server
> enforces, marks the offending field and moves focus to it, so the only
> rejections that reach the flattened server message are crafted requests and the
> solve timeout - and on a timeout, highlighting an input is not useful advice.
> Not worth a public response-shape change plus a second copy of the field names
> living in the client. Recorded so it does not get re-raised.

> **Resolved 2026-10-23: the small favicon sizes exist and every page declares
> the same icon set.**
>
> The native artwork is 16x16. `favicon-96x96.png` and `icon-192.png` are that
> same drawing stored at 6x and 12x - reducing either to its native grid gives
> an identical image, 0 of 256 pixels different - so `favicon-16x16.png` is a
> lossless recovery of the original pixels and `favicon-32x32.png` is that grid
> at 2x nearest neighbour. No resampling anywhere, which is what the pixel art
> needed.
>
> `scripts/make_favicons.py` (recipe: `just favicons`) generates both PNGs and
> writes `favicon.ico` by hand as a two-entry container holding 16 and 32 as
> embedded PNGs. Pillow's own ICO writer resizes with a smoothing filter and
> would have blurred the 16 back out, which is why the container is emitted
> directly. Verified: the .ico reports both sizes and each entry is
> pixel-identical to its PNG, and the 32 is the 16 upscaled exactly 2x. The file
> also shrank, 3,993 B to 1,440 B, because the old one held a single 48x48.
>
> `templates/_icons.html` now holds the whole icon block - 16, 32, 96, the .ico,
> the apple-touch-icon and the manifest - and all three templates include it.
> Confirmed by rendering: `/`, `/privacy` and a 404 each emit the same six
> links, and `/favicon.ico` serves 1,440 bytes as `image/x-icon`. The templates
> can no longer drift the way they did when `privacy.html` and `404.html` lost
> the touch icon.
>
> **The icon-512 worry was mine and it was wrong.** `icon-512.png` is not a
> different drawing. Its native grid is 64x64 and the art inside it is the same
> 14x16 shape at exactly 3x, placed with 11px side and 8px top/bottom margins;
> cropped to the art and aligned, it matches the tab icon in 0 of 224 pixels.
> The earlier "125 of 256 pixels differ" was measuring that padding, not the
> artwork. The only real difference is that the large icon carries a safe-area
> margin the small ones do not, so it fills about 65% x 75% of its canvas
> against the tab icon's 87% x 100%. That is the normal convention for an
> installed-app icon and needs no change.

> **Ordering fixed 2026-10-23: the audit runs before the 2.0 push, not after.**
> The point is a clean local baseline captured while the tree is still the thing
> being measured, saved as JSON in the repository so later runs have something to
> diff against. Deploying first would mean the baseline describes a build nobody
> can reproduce locally.

- [ ] **Run `comprehensive-audit` LAST** - the final Front-End Checklist sweep,
      deliberately held until three things ahead of it are settled. Running it
      first would re-report findings that are already in flight.

  **1. Ko-fi and Discord - settled.** Discord carries its official mark beside
  GitHub's Octocat, and the support button moved out of the footer to a fixed
  top-right corner placement, which costs no page height and cannot be pushed
  off screen by a long result. Two small pieces remain, both listed under
  README & Branding rather than here: only the Ko-fi badge in `README.md`
  (the handle is `ko-fi.com/rovetown`).

  **2. Lighthouse - settled.** Every finding the 2026-10-22 run recorded is
  either fixed or recorded as declined with a reason. Confirmed good on the
  owner's own re-run. The `csp-xss` Medium was checked against CSP3 section
  6.7.3.2 and declined: that spec sets `allow all inline` only in the absence
  of a nonce or hash, and names `'unsafe-inline' 'nonce-abc'` as a list that
  does *not* allow all inline, so adding the keyword to our nonce'd
  `script-src` would be a no-op in every browser since CSP2.

  **3. The debugging thread - still open.** The one gate left:
  - Seventeen-plus commits sit on local `main`, unpushed and undeployed. The
    content-hash fingerprinting in `fa597c8` has only ever run against the dev
    server; it wants one check on a real deploy, where `_webapp` is a slug
    path rather than a working tree. The CSS inlining needs the same check,
    for the same reason.
  - The `www` host still answers `200` instead of redirecting to the apex,
    confirmed live. Tracked under Deployment & Domains.
  - Start the dev server with `--debug`, or Flask caches templates in memory
    and serves stale markup. That is what produced `Cannot read properties of
    undefined (reading 'fieldProblem')` - markup without the `solver-core.js`
    tag against a `solver.js` that needs it. Easy to recreate by starting the
    server the old way.


> **Privacy page updated 2026-10-24 for the Cloudflare cutover.** The page used
> to say the IP address was used for one purpose, the rate-limit counter. True
> of the app, no longer true of the whole picture: Cloudflare records the source
> address of every request and the dashboard shows both aggregates and a sample
> of individual recent requests. No setting on the free plan turns that off, so
> `privacy.html` now names Cloudflare, says what it records, and links their
> privacy policy for retention. Phrasing kept deliberately flat: the site logs no
> addresses, Cloudflare keeps ordinary traffic records the way every network in
> between does, and that is the whole of it. "We log your IP" would be both
> heavier and less accurate than what actually happens.
>
> Verified while writing it: the live site sends **no `Set-Cookie` at all**, so
> the "no cookies" claim still holds. That claim is coupled to a setting -
> turning on Bot Fight Mode or any challenge makes Cloudflare set `__cf_bm` or
> `cf_clearance`, and the page would have to change the same day. The page says
> as much, so the coupling is written down rather than remembered.

> **Resolved 2026-10-24: the CSP uses content hashes, not a nonce.** Option (b).
>
> `g.csp_nonce` is gone. `inline_asset()` now records the sha256 of exactly what
> it inlined, after the url() rewrite, and `_set_security_headers` emits that as
> `'sha256-...'` on `style-src`. `script-src` needs nothing extra: every script on
> every page is a same-origin file covered by `'self'`. The `<style nonce=...>`
> attribute is gone from `index.html`.
>
> The digest is stable for a whole deploy, so an edge-cached copy stays valid -
> which was the point. A response that inlines nothing (`/privacy`, a 404, the
> HTTPS redirect) carries a bare `style-src 'self'`, so no page advertises an
> inline allowance it does not use.
>
> Verified in chromium, firefox and webkit against a live server: page styled,
> `body` background `rgb(107, 81, 82)`, `h1` in Press Start 2P, **0 console
> errors and 0 CSP violations** in all three. Plus a test that recomputes the
> digest from the `<style>` body actually shipped and compares it to the header,
> so a drift between the two fails rather than silently serving an unstyled page.

- [ ] **Re-run the Cloudflare Radar URL scan after the 2.0 deploy.** An earlier
      scan was taken against the deployed build, which still carries the old CSP
      (`cdn.jsdelivr.net` plus `'unsafe-inline'` on `style-src`) and has no
      `/privacy` page. Any finding it reports about headers describes that build,
      not the tree. Re-scan once deployed and judge it then.

- [ ] **Enable DNSSEC** - decided 2026-10-24, not yet done.

  Cloudflare -> DNS -> Settings -> Enable DNSSEC, then copy the Key Tag,
  Algorithm (13), Digest Type (2) and Digest into Namecheap's DNSSEC section on
  the Domain tab. Enabling it in Cloudflare alone does nothing; the DS record at
  the registrar is the half that counts, and `just check-dns` now has a soft row
  that reads WAIT until it exists.

  **The one rule:** if the nameservers ever move away from Cloudflare, delete the
  DS record at Namecheap first and wait a day. Moving while DS records exist
  makes the domain unresolvable everywhere until caches expire.

- [ ] **`GET /privacy` returns 404 in production.** The page only exists in the
      unpushed work, so the deployed site has no privacy policy at all right
      now. Resolved by the 2.0 deploy; listed because it is a gap today.

- [ ] **Purge the Cloudflare cache on deploy.** Found 2026-10-24: a deploy
      landed and `/privacy` kept serving the previous build from the edge.

  The origin was correct the whole time. `/privacy` sends
  `public, max-age=3600` and the cache rule respects origin headers, so the
  edge held the pre-deploy copy and will go on holding it for up to an hour.
  `/` recovered on its own because it sends `max-age=300`.

  Nothing is broken, but "deployed" and "what visitors see" are an hour apart
  on that page, which is the kind of gap that gets debugged twice before anyone
  remembers the cache.

  **The fix is a purge step in `deploy.yml`**, after the Heroku push succeeds:

  ```sh
  curl -X POST "https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/purge_cache"     -H "Authorization: Bearer $CF_API_TOKEN"     -H "Content-Type: application/json"     --data '{"files":["https://iomreliccalc.me/","https://iomreliccalc.me/privacy"]}'
  ```

  Needs two repository secrets: a zone ID, and a token scoped to **Zone ->
  Cache Purge -> Purge** on this zone alone. Do not reuse a global API key for
  it.

  Purging by URL rather than everything, because the fingerprinted assets are
  immutable and there is no reason to make visitors re-fetch them.

  **The alternative**, if the secrets are not wanted: drop `/privacy` to
  `max-age=300` to match the index. Cheaper, but it only narrows the window
  rather than closing it.

- [ ] **Walk production in DevTools.** Everything measured so far was measured
      against a local server, and the two differ in ways that change the answer.

  The local server is waitress over HTTP/1.1 with no edge in front. Production
  is HTTP/2 to the origin, HTTP/3 offered to the browser, and a Cloudflare cache
  in between. The slow-3G Lighthouse numbers in particular were taken where 22
  requests queue behind a six-connection limit, which is not what a visitor
  meets.

  **Console.** Expect one CSP violation until Bot Fight Mode is off, from
  Cloudflare's injected JS Detections script. Anything else is ours and is news.

  **Network.** Confirm on the wire rather than from the config: `cf-cache-status`
  HIT with an `age` on the static assets, `h2` or `h3` as the protocol, `br` as
  the content encoding, and the three subset fonts at roughly 7 KB each rather
  than the 12 to 13 KB they used to be.

  **Performance.** Which element is LCP and what its phases are; whether any long
  task appears now that the what's-new dialog runs on load; whether CLS stays near
  the 0.027 measured locally.

  **Application.** Two localStorage keys and nothing else: `relicSolverInputs` and
  `relicSolver.whatsNew`. No cookies at all, which is what the privacy page
  claims.

  **Coverage.** How much of the inlined CSS and the two scripts actually runs on
  first paint. The stylesheet is inlined on every page load, so dead rules cost
  bytes on every visit rather than once.

  **The dialog.** Open production in a private window and confirm the release
  notes appear for a first-time visitor, dismiss once, and confirm they stay gone
  on reload. That path has only ever been exercised against a dev server.

- [ ] **Turn off Cloudflare's JS Detections.** It injects an inline script into
      every page and the CSP blocks it, which is the console error reported on
      2026-10-24.

  What Cloudflare injects, immediately before `</body>`:

  ```js
  window.__CF$cv$params={r:'<per-request ray id>',t:'<per-request token>'};
  // ...builds a hidden 1x1 iframe and loads
  // /cdn-cgi/challenge-platform/scripts/jsd/main.js
  ```

  `script-src 'self'` has no `'unsafe-inline'` and no hash, so the browser
  refuses it and logs the violation. **The CSP is behaving correctly**; this is
  a third party writing script into pages it is only supposed to be delivering.

  **A hash cannot fix it.** The `r` and `t` values are minted per request, so
  the script body differs every time and any `'sha256-...'` is stale the moment
  it is written. The hash in the reported error does not match the body seen
  from here one minute later, which is the same fact from the other direction.

  **The fix is a dashboard toggle.** Security -> Bots -> turn **Bot Fight Mode**
  off, which also turns off the JS Detections that ride along with it. This was
  already the recommendation when the settings were walked on 2026-10-23, for a
  different reason: it challenges non-browser callers, and `/solve` is a
  documented JSON endpoint.

  **Do not "fix" it by loosening the CSP.** `'unsafe-inline'` on `script-src`
  would undo `87ac2a5` and `b9817d6` together, to permit an invisible iframe
  nobody asked for.

- [ ] **Optional: let Cloudflare Web Analytics through the CSP** - only if the
      beacon is actually wanted.

  The Analytics tab in the Cloudflare dashboard is built from the edge's own
  request logs. It injects nothing, costs nothing at runtime and raises no CSP
  question, so there is nothing to disable and nothing to allow.

  **Web Analytics** is the separate product, and it is the one that injects a
  script from `static.cloudflareinsights.com`. The CSP in `app.py` allows scripts
  only by per-request nonce and has no host-source at all, so that beacon is
  blocked today and logs a violation on every page load it is enabled for.
  Allowing it means adding the host to `script-src` and `connect-src`, which
  reopens exactly the host-source hole the current policy closes. Worth it only
  if the per-visitor data is genuinely wanted; the edge analytics already answer
  "how much traffic, from where, how much cached".

### CI/CD (GitHub Actions)

- [ ] Optional: publish to PyPI if the solver becomes a standalone package
      - **deliberately parked 2026-10-23.** Wanted eventually, not now.

### Last - after everything above

- [ ] Easter egg: yellow text popups, like IOM's "already used codes" animation.
      Held until last on purpose: it is pure decoration, and it writes into the same
      part of the DOM the result renderer owns, so doing it before the rest is settled
      invites a conflict for no benefit.
