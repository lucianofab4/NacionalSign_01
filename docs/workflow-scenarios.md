# Workflow Scenarios

## Standard Sequential Signature
1. Requester uploads document and selects sequential template.
2. System enqueues signature requests in defined order.
3. Each signer is notified via email/SMS with secure link.
4. Signer authenticates (login/password or ICP) and signs.
5. Next signer activated; process repeats until completion.
6. System assembles final PDF and audit report, sends to all parties.

## Parallel Approval + Witness
- Steps 1-2 identical to sequential flow.
- Flow branches into parallel tasks: multiple approvers receive notifications simultaneously.
- Upon completion of parallel branch, witness receives request and must sign within deadline.
- If any approver refuses, workflow returns to requester with reason captured.

## Delegated (Procurator) Signature
- Principal assigns procurator with validity window.
- When principal is part of a workflow, procurator receives notification.
- Procurator authenticates with their own credentials and signs on behalf, log entry records delegation chain.

## Token-Based Simple Signature
- Suitable for external signers without account.
- System sends OTP via SMS/email.
- Signer enters token, acknowledges consent, signature recorded with token hash and IP metadata.

## ICP-Brasil Digital Signature Flow
- Signer launches web or desktop signing component.
- Certificate (A1/A3) used to sign SHA256 digest of document.
- Signature package stored with certificate data, CRL/OCSP validation recorded.
- TSA timestamp applied post-signature for non-repudiation.

## Refusal Handling
- Signer chooses "Refuse" and inputs mandatory justification.
- Requester receives immediate notification; workflow paused.
- Requester can adjust document/template or close workflow, creating audit record.

## Expiration & Reminders
- Each signature step may define expiration.
- Scheduled job checks upcoming expirations, sends reminders.
- Expired requests mark workflow as `expired` and notify requester.

## Public Verification
- Finalized document exposes verification code (UUID or short hash).
- Public endpoint allows third parties to validate status, hashes, signers, timestamps.
- If document revoked, verification page shows revocation reason and timestamp.
