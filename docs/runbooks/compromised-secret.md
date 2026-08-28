# Compromised Secret

## Signal

An API key, refresh token, JWT signing secret, endpoint signing secret, or encryption key may have
been disclosed or misused.

## Response

1. Classify the credential and scope without copying its plaintext into tickets, chat, or logs.
2. Revoke affected API keys or refresh-token families immediately. Disable the endpoint while its
   signing secret is replaced. For JWT compromise, rotate the signing secret and invalidate active
   sessions according to the deployment procedure.
3. For an encryption-key incident, preserve ciphertext and key-version metadata; use an audited,
   staged re-encryption procedure. Never delete the old key before all required data is re-encrypted
   and verified.
4. Review bounded audit records, request IDs, key last-use times, and delivery attempts. Do not expose
   payloads, response previews, signatures, or endpoint URLs in the incident report.
5. Issue replacement credentials once, verify receiver signature handling, and monitor for continued
   use of revoked material.

## Escalate

Escalate immediately to the security owner for production credentials, signing/encryption root keys,
cross-tenant access, or evidence of data disclosure. Follow legal notification requirements outside
this repository's automation.
