"""Drain pending Items through the auto-moderation pipeline.

Schedule from cron / a systemd timer / your task runner:

    */5 * * * * cd /path/to/dawa-backend && python manage.py moderate_listings --loop

`--loop` keeps draining until no more `Pending` items are found this pass.
Omit it to process exactly one batch (safer inside a lock-free crontab).
"""
from __future__ import annotations

import asyncio
import logging

from django.core.management.base import BaseCommand

from listingModeration.config import config
from listingModeration.pipeline import process_batch


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the listing auto-moderation pipeline on pending Items."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--batch-size",
            type=int,
            default=None,
            help=f"Items per drain pass (default: {config.batch_size} from config).",
        )
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Keep draining until no more pending items remain.",
        )
        parser.add_argument(
            "--max-passes",
            type=int,
            default=50,
            help="Safety cap on --loop iterations (default: 50).",
        )

    def handle(self, *args, **opts) -> None:
        batch = opts.get("batch_size") or config.batch_size
        loop = opts.get("loop")
        max_passes = int(opts.get("max_passes") or 50)

        totals = {"processed": 0, "approved": 0, "rejected": 0, "needs_review": 0, "failed": 0}
        passes = 0

        while True:
            passes += 1
            counts = asyncio.run(process_batch(batch))
            for k in totals:
                totals[k] += counts.get(k, 0)

            self.stdout.write(
                self.style.SUCCESS(
                    f"pass {passes}: processed={counts.get('processed', 0)} "
                    f"approved={counts.get('approved', 0)} rejected={counts.get('rejected', 0)} "
                    f"needs_review={counts.get('needs_review', 0)} failed={counts.get('failed', 0)}"
                )
            )

            if not loop:
                break
            if not counts.get("processed"):
                break
            if passes >= max_passes:
                self.stdout.write(
                    self.style.WARNING(f"--max-passes={max_passes} reached; stopping loop")
                )
                break

        self.stdout.write(self.style.SUCCESS(f"totals: {totals}"))
