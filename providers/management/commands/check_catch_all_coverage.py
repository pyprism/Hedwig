"""Flags domains with receive-enabled mailboxes but no catch-all mailbox
configured — mail to any address nobody explicitly provisioned (a typo, or an
address nobody set up yet) is silently dropped by ``providers.ingest.resolve_mailbox``
with nothing visible beyond a ``ProviderWebhookLog`` row with
``status=ignored``. Meant to run periodically (see
``providers.tasks.check_catch_all_coverage_task``) or ad hoc when onboarding
a domain.

Exit code is 0 unless ``--strict`` is passed and at least one domain is
flagged, so it can double as a CI/cron gate.
"""

from django.core.management.base import BaseCommand

from providers.catch_all_coverage import find_domains_missing_catch_all


class Command(BaseCommand):
    help = "Report domains with no catch-all mailbox configured, and recent dropped-mail counts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Look back this many days for dropped-inbound-mail counts (default: 7).",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit with status 1 if any domain is flagged.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        flagged = find_domains_missing_catch_all(days=days)

        if not flagged:
            self.stdout.write(
                self.style.SUCCESS(
                    "All domains with receive-enabled mailboxes have a catch-all configured."
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"{len(flagged)} domain(s) have receive-enabled mailboxes but no catch-all "
                f"mailbox — mail to unrecognized addresses is being silently dropped:"
            )
        )
        for domain, mailbox_count, dropped_count in flagged:
            self.stdout.write(
                f"  - {domain.name}: {mailbox_count} receiving mailbox(es), "
                f"{dropped_count} message(s) dropped for 'no mailbox matched' "
                f"in the last {days} day(s)"
            )

        if options["strict"]:
            raise SystemExit(1)
