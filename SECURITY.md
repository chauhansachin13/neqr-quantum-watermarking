# Security Policy

## Supported Versions

| Version | Supported |
| :--- | :--- |
| `3.0.x` | Yes |
| `< 3.0.0` | No |

## Threat Model & Hardening Controls

- **Web Server Exposure (`qwm ui` / `qwm serve`)**: Binds to `127.0.0.1:8765` by default. Put behind an authenticated TLS reverse proxy before exposing beyond localhost.
- **Request Validation & DoS Guardrails**:
  - Rejects `POST` payloads larger than `12 MiB` (`MAX_BODY`) with HTTP `413`.
  - Rejects invalid `Content-Length`, malformed JSON, non-object JSON payloads, and malformed data URLs with HTTP `400`.
  - Caps concurrent in-memory sessions with LRU eviction (`MAX_SESSIONS = 40`).
- **Path Traversal & Browser Hardening**:
  - Static asset reads verify resolved paths stay strictly inside `qwm/web/static`.
  - Responses include `X-Content-Type-Options: nosniff` and `Cache-Control: no-store`.
- **Network Safety**:
  - `qwm download-images` enforces HTTPS URLs (`https://`) before fetching standard benchmark images.
- **Cryptographic Tag Limits (Research Context)**:
  - Blind keyed modes use SHAKE-256 keystreams paired with Toeplitz MACs (`2^-8` forgery probability for `2×2` `keyed`/`keyed-opt`, `2^-12` for `4×4` `recovery`, and `2^-16` for `8×8` `recovery-dual`). Do not rely on `2×2` base unkeyed modes (`paper`, `lsb`, `opap`) against adaptive LSB-preserving forgery.

## Reporting a Vulnerability

Open a private security advisory on GitHub (`chauhansachin13/neqr-quantum-watermarking`) with reproduction steps, affected endpoint/CLI command, and expected impact. Avoid posting working exploits to public issues.
