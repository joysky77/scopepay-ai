# ScopePay AI 0.2.0

ScopePay AI is a browser-local proof of concept that checks a service brief for a concrete deliverable, acceptance criterion, boundary, privacy handling, amount and deadline before enabling a PayPal sandbox handoff.

The embedded AI is a transparent TF-IDF similarity model trained on synthetic agreement concepts. It runs entirely in the browser and does not upload the brief. It is not legal advice, a fraud detector or a payment guarantee.

## Run in demo mode

```powershell
python server.py
```

Open `http://127.0.0.1:8787/`. Demo orders exist only in memory and never contact PayPal or move real money.
The server binds to loopback by default and refuses a remote host unless `SCOPEPAY_ALLOW_REMOTE=1` is explicitly set. Remote deployment needs its own authentication, TLS, CSRF controls and rate limiting.

## Run against PayPal sandbox

Set `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` in the process environment, then start the same server. Credentials stay server-side and are never returned to the browser or written to project files. Version 0.2.0 uses PayPal's sandbox OAuth and Orders v2 create/capture endpoints only.

## Current boundary

- Version 0.2.0 provides a complete local demo flow and an optional PayPal sandbox create/approve/capture flow.
- Demo mode creates no PayPal request. Sandbox funds are test funds and do not count as income.
- A client secret must never appear in frontend code, GitHub, screenshots or shared files.
- The project is independent and is not endorsed by PayPal.

## Verification

```powershell
python -m unittest discover -s tests -v

node tests/verify.cjs http://127.0.0.1:8787/
```

The tests cover amount and credential validation, session-bound demo orders, OAuth and Orders v2 request shapes against a mock transport, secret/brief exclusion, non-sandbox and untrusted approval URL refusal, remote-bind refusal, and both browser agreement paths.
