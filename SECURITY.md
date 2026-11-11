# Security Policy

Thank you for taking the time to look at the security of Relic Solver. This
document is the policy referenced by
[`/.well-known/security.txt`](https://iomreliccalc.me/.well-known/security.txt).

## Supported versions

Only the currently deployed version of <https://iomreliccalc.me> and the
`main` branch of this repository receive security fixes. There are no
long-lived release branches to back-port to.

## Reporting a vulnerability

Please use one of these two channels. Both reach the same person.

1. **GitHub private vulnerability reporting** (preferred):
   <https://github.com/Rovetown/Relic-Solver/security/advisories/new>.
   This keeps the report, the discussion and the eventual advisory in one
   place, and it does not require you to encrypt anything.
2. **Email**: `tgtyiowk@rovetown.anonaddy.com`. This is a forwarding alias,
   so the address stays stable even if the mailbox behind it changes. For
   anything sensitive, encrypt to the PGP key published at
   <https://iomreliccalc.me/.well-known/pgp-key.txt>
   (fingerprint `EED2 386B 4049 4CDC F8B6 1B4C DDD8 5342 D44D 6BE0`).

Please do not open a public issue for a vulnerability, and please do not
disclose it publicly until a fix is deployed.

### What to include

A report is much faster to act on when it contains:

- the affected URL, endpoint or file, and the commit or deployment date,
- the steps or the exact request needed to reproduce it,
- what an attacker gains, in concrete terms,
- the `X-Request-Id` header from the response, if the issue showed up as an
  error. Every response carries one and it appears verbatim in the logs.

Proof of concept code, a HAR file or a short screen recording are all
welcome. Please keep any payload you send to the smallest one that
demonstrates the problem.

## What to expect

This is a single-maintainer hobby project, not a funded product, so the
timelines below are honest rather than ambitious:

- **Acknowledgement**: within 5 days.
- **First assessment**, including whether the report is accepted and a rough
  severity: within 14 days.
- **Fix**: as soon as it is practical. High severity issues that are
  remotely exploitable come before everything else on the board.
- **Credit**: you will be named in the advisory and the changelog unless you
  ask not to be.

There is no bug bounty. Nothing here can be paid out, and offering money for
reports would be dishonest about what this project is.

## Safe harbour

Research carried out in good faith under this policy will not be met with a
legal complaint or a report to your provider. In exchange, please:

- use only your own data and your own browser session for testing,
- stop at the point where you have proved the issue, and never read, change
  or delete data that is not yours,
- avoid anything that degrades the service for other people: no load tests,
  no denial of service, no automated scanning that outruns the published rate
  limits,
- keep what you find to yourself until the fix is out.

Breaking the three rules above takes a report outside this policy.

## Out of scope

The following are known and accepted, and a report about one of them will be
closed as such:

- missing security headers that the
  [Content Security Policy](https://iomreliccalc.me/) already covers, where
  the finding comes from a scanner's default list rather than an actual
  bypass,
- rate limits being reachable at all. They exist to shed load and the limits
  themselves are published in the API responses,
- vulnerabilities in a third-party service this project only consumes
  (Cloudflare, Heroku, GitHub). Report those to that vendor,
- results from an automated tool pasted without a working reproduction,
- clickjacking on a page with no authenticated state, and anything that
  needs a user to paste code into their own developer console,
- the absence of a feature, such as accounts, two-factor authentication or
  password rules. The site stores no accounts and no personal data. See
  the [privacy page](https://iomreliccalc.me/privacy).

## Signature and freshness

`security.txt` is clearsigned with the key above and carries an `Expires`
field. If it has expired, treat the contact details as stale and fall back
to the GitHub advisory link, which does not expire.
