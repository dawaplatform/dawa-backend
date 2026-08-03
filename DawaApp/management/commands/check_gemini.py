"""
Diagnose Gemini connectivity end-to-end. Runs three independent checks:
  1. Is GEMINI_API_KEY set?
  2. Can we resolve DNS + open a TLS socket to generativelanguage.googleapis.com?
  3. Can we make a real Gemini call and get a valid response?
"""
import os
import socket
import ssl
import sys
import time

from django.core.management.base import BaseCommand


def _log(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


class Command(BaseCommand):
    help = "Diagnose Gemini API connectivity, key format, and model availability."

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            default=None,
            help="Override the model to test (defaults to services.DEFAULT_GEMINI_MODEL).",
        )
        parser.add_argument(
            "--list-models",
            action="store_true",
            help="After the connectivity check, list the models this key can access.",
        )

    def handle(self, *args, **options):
        _log("=== Gemini connectivity check ===\n")

        # 1. Key present?
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            _log("✗ GEMINI_API_KEY (or GOOGLE_API_KEY) is not set.")
            _log("  Get one at https://aistudio.google.com/apikey")
            return
        prefix = key[:5]
        key_type = (
            "Auth API key (new format, recommended)" if key.startswith("AQ.")
            else "Standard API key (legacy, being deprecated Sep 2026)" if key.startswith("AIza")
            else "UNKNOWN — this may not be a valid Gemini API key"
        )
        _log(f"✓ GEMINI_API_KEY is set. prefix={prefix!r}  type={key_type}")

        # 2. Raw TCP + TLS to Google's endpoint.
        host = "generativelanguage.googleapis.com"
        port = 443
        _log(f"\n→ TCP+TLS handshake to {host}:{port} …")
        t0 = time.time()
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((host, port), timeout=15) as raw:
                with ctx.wrap_socket(raw, server_hostname=host) as tls:
                    _log(f"✓ TLS handshake OK in {time.time()-t0:.2f}s "
                         f"| cipher={tls.cipher()[0]} tls={tls.version()}")
        except socket.gaierror as exc:
            _log(f"✗ DNS lookup failed: {exc}")
            _log("  Your machine cannot resolve Google's hostname. "
                 "Check /etc/resolv.conf, VPN, or DNS server.")
            return
        except (socket.timeout, TimeoutError) as exc:
            _log(f"✗ Connection timed out after {time.time()-t0:.2f}s: {exc}")
            _log("  The network path to Google is blocked or extremely slow. "
                 "Try a different network / disable VPN / check firewall.")
            return
        except ssl.SSLError as exc:
            _log(f"✗ TLS error: {exc}")
            return
        except Exception as exc:
            _log(f"✗ Unexpected socket error: {exc!r}")
            return

        # 3. Real Gemini call via plain REST (not the SDK).
        from DawaApp.services import DEFAULT_GEMINI_MODEL
        model = options["model"] or os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
        _log(f"\n→ Calling REST endpoint for model={model!r} …")
        try:
            import requests
        except ImportError:
            _log("✗ requests package is not installed.")
            return

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        )
        body = {
            "contents": [{"parts": [{"text": "Reply with the single word: pong"}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 16},
        }
        try:
            t0 = time.time()
            resp = requests.post(
                url,
                json=body,
                headers={"Content-Type": "application/json", "x-goog-api-key": key},
                timeout=30,
            )
            elapsed = time.time() - t0
            if resp.status_code == 200:
                data = resp.json()
                parts = (
                    (data.get("candidates") or [{}])[0].get("content", {}).get("parts") or [{}]
                )
                text = "".join(p.get("text", "") for p in parts).strip()
                _log(f"✓ REST call OK in {elapsed:.2f}s | response.text = {text!r}")
                _log("\nAll checks passed. Gemini is reachable and the key works.")
                return

            _log(f"✗ HTTP {resp.status_code} in {elapsed:.2f}s")
            _log(f"  Body: {resp.text[:400]}")
            body_lower = (resp.text or "").lower()
            if resp.status_code == 401:
                _log("  → Key authentication failed. Regenerate at")
                _log("    https://aistudio.google.com/apikey")
            elif resp.status_code == 403:
                if "project has been denied" in body_lower or "permission_denied" in body_lower:
                    _log("  → PROJECT-level denial (not a key format problem). Fix:")
                    _log("    1. Open https://aistudio.google.com/apikey")
                    _log("    2. Click 'Create API key' → pick 'Create a new project'")
                    _log("       (do NOT reuse the current project — it's the one denied).")
                    _log("    3. Copy the new key into .env as GEMINI_API_KEY and re-run.")
                    _log("    Root cause: your current project either has abuse flags or the")
                    _log("    Generative Language API was never enabled on it.")
                else:
                    _log("  → Permission denied. The key may lack Gemini API access.")
            elif resp.status_code == 404:
                _log(f"  → Model {model!r} doesn't exist. Use --list-models to see what's")
                _log("    available, or try 'gemini-flash-lite-latest' / 'gemini-3.5-flash-lite'.")
            elif resp.status_code == 429:
                _log("  → Rate-limited. Wait a minute or switch to a lighter model.")
        except requests.Timeout:
            _log(f"✗ Request timed out after 30s")
            _log("  → Network path to Google is very slow. Try another network / VPN.")
        except Exception as exc:
            _log(f"✗ Unexpected error: {exc!r}")
            return

        # 4. Optional: enumerate models the key can see.
        if options.get("list_models"):
            _log("\n→ Listing available models …")
            try:
                r = requests.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    headers={"x-goog-api-key": key},
                    timeout=15,
                )
                if r.status_code != 200:
                    _log(f"✗ HTTP {r.status_code}: {r.text[:300]}")
                    return
                names = [m.get("name", "") for m in r.json().get("models", [])]
                gen_names = sorted(
                    n.replace("models/", "") for n in names
                    if "generateContent" in str(r.text)  # coarse filter, cheap
                )
                _log(f"✓ {len(names)} model(s) visible to this key.")
                for n in sorted(names):
                    _log(f"    {n}")
            except Exception as exc:
                _log(f"✗ Failed to list models: {exc!r}")
