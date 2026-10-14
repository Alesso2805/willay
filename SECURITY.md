# Security policy

Willay is a portfolio project, and its public demo runs with simulated data. Even so, if you find a vulnerability, please report it privately rather than in a public issue or pull request.

## How to report

Use GitHub's private vulnerability reporting: the repository's **Security** tab, then **Report a vulnerability**. Say what you found, how to reproduce it and what an attacker could do with it.

You will get an answer within a week. Fixes go to `main`, and the public demo is redeployed from it.

## In scope

- Seeing or changing another organization's data, over REST or the live events channel.
- Acting beyond your role, or without signing in.
- A station's API key: using one that should not work, guessing one, or recovering one.
- Acknowledging an alert that was sent to someone else, by email link or Telegram button.
- Personal data leaving the API: a contact's email shown to a role that should not see it, or a Telegram chat id.
- Secrets in the repository or its history.

## Out of scope

- The public demo's shared accounts and password: they are public on purpose.
- The demo's mailbox (`/correo`): it shows the demo's own simulated emails by design.
- Denial of service against the demo server, and load tests against it.
- Reports from automated scanners without a way to exploit the finding.

Please do not access data that is not yours.
