# ScopePay AI 0.1.0

ScopePay AI is a browser-local proof of concept that checks a service brief for a concrete deliverable, acceptance criterion, boundary, privacy handling, amount and deadline before enabling a PayPal sandbox handoff.

The embedded AI is a transparent TF-IDF similarity model trained on synthetic agreement concepts. It runs entirely in the browser and does not upload the brief. It is not legal advice, a fraud detector or a payment guarantee.

## Run

Open `index.html` in Microsoft Edge. Use only fictional or public text in the prototype.

## Current boundary

- Version 0.1.0 demonstrates the local AI agreement gate and a sandbox handoff state.
- No real transaction is created or captured.
- Before any contest submission, PayPal sandbox order creation must be connected with the account owner's sandbox client ID and tested end to end. A client secret must never appear in frontend code.
- The project is independent and is not endorsed by PayPal.

## Verification

```powershell
node Y:\Business\opportunities\paypal-ai-hackathon\scopepay-ai-v0.1.0\tests\verify.cjs
```

The test loads both synthetic examples in Edge, checks the readiness and risk gates, verifies the local-model API, and confirms the page makes no transaction request.
