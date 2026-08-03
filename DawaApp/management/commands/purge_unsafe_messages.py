import re
import sys
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, OperationalError
from django.db.models import Count

from DawaApp.models import Message, Chat
from DawaApp.services import check_messages_batch, local_prescreen

DEFAULT_BATCH_SIZE = 15
DEFAULT_DELAY = 13.0  # seconds — keeps us under the 5 RPM free-tier limit


def _log(msg: str = "") -> None:
    """Write directly to stdout and flush immediately so nothing is buffered."""
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _retry_seconds(exc: Exception) -> float | None:
    """Extract the suggested retry delay from a Gemini 429 error message."""
    msg = str(exc)
    if "429" not in msg and "RESOURCE_EXHAUSTED" not in msg:
        return None
    m = re.search(r"retry in ([\d.]+)s", msg)
    return float(m.group(1)) + 2 if m else 65.0


def _call_with_retry(batch: list[dict]) -> list[dict]:
    """Call check_messages_batch, auto-waiting and retrying once on 429."""
    try:
        return check_messages_batch(batch)
    except Exception as exc:
        wait = _retry_seconds(exc)
        if wait is not None:
            _log(f"  Rate-limited (429) — waiting {wait:.0f}s then retrying…")
            time.sleep(wait)
            return check_messages_batch(batch)
        raise


class Command(BaseCommand):
    help = (
        "Scan chat messages with Gemini (batched) and optionally delete unsafe ones. "
        "Defaults to dry-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Actually delete unsafe messages (without this, only report).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Only scan the N most recent messages.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Messages per Gemini API call (default: {DEFAULT_BATCH_SIZE}).",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=DEFAULT_DELAY,
            help=f"Seconds to wait between API calls (default: {DEFAULT_DELAY}).",
        )
        parser.add_argument(
            "--cleanup-empty-chats",
            action="store_true",
            help="Delete chats that have no messages left after the purge.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help=(
                "Treat skipped / inconclusive results (API errors, parse errors) "
                "as UNSAFE and delete them. Use this to enforce the 'safe or gone' rule."
            ),
        )

    def handle(self, *args, **options):
        do_delete = options["delete"]
        limit = options["limit"]
        batch_size = options["batch_size"]
        delay = options["delay"]
        cleanup_empty = options["cleanup_empty_chats"]
        strict = options["strict"]

        _log("Connecting to database…")
        try:
            connections["default"].ensure_connection()
            _log("Connected.")
        except OperationalError as exc:
            raise CommandError(
                f"Cannot reach the database: {exc}\n"
                "Check DB_HOST / DB_PASSWORD in your .env and that your IP is allowed."
            )

        _log("Loading messages…")
        qs = Message.objects.only(
            "id", "message", "chat_id", "sender_id", "receiver_id"
        ).order_by("-created_at")
        if limit:
            qs = qs[:limit]

        all_messages = list(qs)
        total = len(all_messages)

        if total == 0:
            _log("No messages found.")
            return

        mode = "DELETE" if do_delete else "DRY-RUN"
        strictness = " STRICT" if strict else ""
        batches = [all_messages[i : i + batch_size] for i in range(0, total, batch_size)]
        eta = len(batches) * delay
        _log(
            f"[{mode}{strictness}] {total} message(s) → {len(batches)} batch(es) "
            f"of {batch_size} | delay={delay:.0f}s | est. {eta:.0f}s\n"
        )

        unsafe: list[tuple] = []
        safe_count = 0
        skipped_count = 0
        api_error_batches = 0
        api_error_messages = 0

        for batch_num, batch in enumerate(batches, start=1):
            _log(f"--- Batch {batch_num}/{len(batches)} ({len(batch)} messages) ---")

            # Layer 1 — local prescreen. Anything we can flag locally never
            # touches the Gemini quota.
            results_map: dict[int, dict] = {}
            api_batch: list[dict] = []
            for msg in batch:
                text = (msg.message or "").strip()
                local = local_prescreen(text)
                if local["matched"]:
                    results_map[msg.id] = {
                        "id": msg.id,
                        "is_safe": local["is_safe"],
                        "reason": local["reason"],
                    }
                else:
                    api_batch.append({"id": msg.id, "text": text})

            batch_api_failed = False
            if api_batch:
                _log(f"  Calling Gemini for {len(api_batch)} message(s)…")
                try:
                    results = _call_with_retry(api_batch)
                    for r in results:
                        results_map[r["id"]] = r
                    _log(f"  Got {len(results)} result(s) back.")
                    # Even a "successful" return may be an api_error_fallback
                    # from services.check_messages_batch — detect that here.
                    if all(str(r.get("reason", "")).startswith("API_ERROR:") for r in results):
                        batch_api_failed = True
                except Exception as exc:
                    _log(f"  ERROR — batch {batch_num} failed: {exc}")
                    batch_api_failed = True
                    for p in api_batch:
                        results_map[p["id"]] = {
                            "id": p["id"],
                            "is_safe": True,
                            "reason": f"API_ERROR: {exc}",
                        }

            if batch_api_failed:
                api_error_batches += 1
                api_error_messages += len(api_batch)
                _log(
                    f"  ⚠  Batch {batch_num}: Gemini unreachable — {len(api_batch)} "
                    f"message(s) not evaluated (will be reported as SKIP, not deleted)."
                )

            for msg in batch:
                r = results_map.get(msg.id, {"is_safe": True, "reason": "No result returned."})
                reason = r.get("reason", "")
                is_safe = r.get("is_safe", True)

                # Distinguish "AI couldn't decide" (safe to treat as unsafe under
                # --strict) from "we never reached the AI" (must NEVER be deleted
                # by --strict — a network outage would wipe the whole DB).
                api_error = reason.startswith("API_ERROR:")
                ai_inconclusive = (
                    not api_error and (
                        reason.lower().startswith("skipped")
                        or "parse error" in reason.lower()
                        or "no result" in reason.lower()
                    )
                )

                if api_error:
                    skipped_count += 1
                    _log(f"  SKIP   id={msg.id} — {reason} (not deletable)")
                elif ai_inconclusive and strict:
                    preview = (msg.message or "")[:80]
                    unsafe.append((msg, f"[strict] {reason}"))
                    _log(f"  UNSAFE (strict) id={msg.id}  reason={reason!r}")
                    _log(f"         preview={preview!r}")
                elif ai_inconclusive:
                    skipped_count += 1
                    _log(f"  SKIP   id={msg.id} — {reason}")
                elif is_safe:
                    safe_count += 1
                    _log(f"  SAFE   id={msg.id}")
                else:
                    preview = (msg.message or "")[:80]
                    unsafe.append((msg, reason))
                    _log(f"  UNSAFE id={msg.id}  reason={reason!r}")
                    _log(f"         preview={preview!r}")

            if batch_num < len(batches):
                _log(f"\n  Waiting {delay:.0f}s before next batch…\n")
                time.sleep(delay)

        _log("")
        _log("—— Summary ——")
        _log(f"  Total scanned      : {total}")
        _log(f"  Safe               : {safe_count}")
        _log(f"  Unsafe             : {len(unsafe)}")
        _log(f"  Skipped/error      : {skipped_count}")
        if api_error_batches:
            _log(
                f"  API errors         : {api_error_batches} batch(es), "
                f"{api_error_messages} message(s) not evaluated by AI"
            )

        # Safety guard: refuse to delete anything when Gemini was unreachable
        # for every batch. Otherwise a network outage during --strict would
        # amount to "delete all messages the local filter didn't clear".
        if api_error_batches == len(batches) and unsafe and do_delete:
            _log(
                "\nABORT: Gemini was unreachable for every batch. Refusing to "
                "delete — nothing was actually evaluated by the AI. Fix the "
                "network / API key and re-run."
            )
            return

        if not unsafe:
            _log("\nNo unsafe messages found.")
            return

        if not do_delete:
            _log(
                f"\nDry-run only — re-run with --delete to remove "
                f"{len(unsafe)} unsafe message(s)."
            )
            return

        ids = [msg.id for msg, _ in unsafe]
        deleted, _ = Message.objects.filter(id__in=ids).delete()
        _log(f"\nDeleted {deleted} unsafe message(s).")

        if cleanup_empty:
            empty_chats = (
                Chat.objects.annotate(msg_count=Count("messages")).filter(msg_count=0)
            )
            empty_ids_list = list(empty_chats.values_list("id", flat=True))
            if empty_ids_list:
                removed, _ = Chat.objects.filter(id__in=empty_ids_list).delete()
                _log(f"Also deleted {removed} empty chat(s): {empty_ids_list}")
            else:
                _log("No empty chats to clean up.")
