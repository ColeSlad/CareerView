import argparse
import io
import smtplib
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx

from careerview import cli, health, store
from careerview.health import SourceCheck
from careerview.models import Listing
from careerview.poller import run_poll


def check(key='ashby:acme', *, error=None, timestamp=100, count=0):
    return SourceCheck(key, key.split(':')[-1].capitalize(), 'ashby', key.split(':')[-1],
                       timestamp, 1.25, None if error else count, error)


def job():
    return Listing('ashby:acme:1', 'ashby', 'Acme', 'Software Intern', 'Software',
                   ['Remote'], [], 'https://jobs.ashbyhq.com/acme/1', emailed=True, first_seen=42)


class HealthTests(unittest.TestCase):
    def test_zero_listings_success_failure_history_and_recovery(self):
        previous = {'poll_health': health.build_health({}, [check()], 90, 100, 10)}
        self.assertEqual(previous['poll_health']['status'], 'healthy')
        failed = health.build_health(previous, [check(error='HTTP 404', timestamp=200)], 190, 200, 10)
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['last_success_at'], 100)
        self.assertEqual(failed['sources'][0]['last_success_at'], 100)
        self.assertIsNone(failed['sources'][0]['listing_count'])
        again = health.build_health({'poll_health': failed}, [check(error='HTTP 404')], 290, 300, 10)
        self.assertEqual(again['sources'][0]['consecutive_failures'], 2)
        recovered = health.build_health({'poll_health': again}, [check(timestamp=400)], 390, 400, 10)
        self.assertEqual(recovered['last_success_at'], 400)
        self.assertEqual(recovered['sources'][0]['consecutive_failures'], 0)
        self.assertEqual(recovered['sources'][0]['last_success_at'], 400)

    def test_partial_failure_empty_configuration_and_removed_sources(self):
        previous = {'poll_health': health.build_health({}, [check('ashby:old')], 90, 100, 10)}
        result = health.build_health(previous, [check(), check('ashby:broken', error='HTTP 404')], 190, 200, 10)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['last_success_at'], 100)
        self.assertEqual(len(result['sources']), 2)
        self.assertEqual(health.sorted_sources({'poll_health': result})[0]['company'], 'Broken')
        self.assertEqual(len(health.sorted_sources({'poll_health': result}, 'ACME')), 1)
        self.assertEqual(health.build_health({}, [], 100, 200, 100)['status'], 'no_sources')

    def test_staleness_boundary_missing_and_legacy_data(self):
        self.assertIn('Health not recorded', health.summary({}, 100, 45))
        legacy = {'last_run': 100, 'fetched_count': 10}
        self.assertFalse(health.is_stale(legacy, 2799, 45))
        self.assertTrue(health.is_stale(legacy, 2800, 45))
        self.assertIn('STALE', health.summary(legacy, 2800, 45))
        self.assertIn('All sources last succeeded: not recorded', health.details(legacy, 200, 15, 45))
        fresh = {'poll_health': health.build_health({}, [check()], 90, 100, 10)}
        self.assertFalse(health.needs_attention(fresh, 200, 45))
        fresh['poll_health']['email_status'] = 'failed'
        self.assertTrue(health.needs_attention(fresh, 200, 45))

    def test_errors_do_not_store_urls_or_credentials(self):
        request = httpx.Request('GET', 'https://example.invalid?app_key=supersecret')
        response = httpx.Response(403, request=request)
        errors = [httpx.HTTPStatusError('supersecret', request=request, response=response),
                  httpx.ReadTimeout('supersecret'), ValueError('supersecret')]
        for error in errors:
            self.assertNotIn('supersecret', health.error_summary(error))
        self.assertEqual(health.error_summary(errors[0]), 'HTTP 403')

    def test_source_identity_distinguishes_sites_and_feed_branches(self):
        first = SimpleNamespace(name='workday', tenant='acme', wd='wd1', site='US')
        second = SimpleNamespace(name='workday', tenant='acme', wd='wd1', site='UK')
        self.assertNotEqual(health.source_identity(first)[0], health.source_identity(second)[0])
        feed = SimpleNamespace(name='simplify', repo='org/repo', branch='main')
        self.assertIn('org/repo@main', health.source_identity(feed)[0])

    def test_failed_fetch_preserves_snapshot_and_email_history_until_recovery(self):
        old = job()
        source = SimpleNamespace(name='ashby', slug='acme', company_name='Acme',
                                 fetch=Mock(side_effect=ValueError('bad response')))
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            path = Path(temp) / 'listings.json'
            store.save_listings({old.uid: old}, path)
            failed = run_poll([source], path)
            self.assertIsNone(failed.source_checks[0].listing_count)
            self.assertEqual(failed.retained_uids, {old.uid})
            self.assertTrue(failed.all_listings[old.uid].emailed)
            self.assertEqual(failed.all_listings[old.uid].first_seen, 42)
            store.save_listings(failed.all_listings, path)
            source.fetch.side_effect = None
            incoming = job()
            incoming.emailed = False
            source.fetch.return_value = [incoming]
            recovered = run_poll([source], path)
            self.assertEqual(recovered.new_listings, [])
            self.assertTrue(recovered.all_listings[old.uid].emailed)
            source.fetch.return_value = []
            empty = run_poll([source], path)
            self.assertEqual(empty.all_listings, {})
            self.assertIsNone(empty.source_checks[0].error)

    def test_failed_source_copy_is_not_retained_when_another_feed_returns_same_job(self):
        old = job()
        incoming = job()
        incoming.uid = 'simplify:copy'
        incoming.source = 'simplify'
        sources = [SimpleNamespace(name='ashby', slug='acme', fetch=Mock(side_effect=ValueError())),
                   SimpleNamespace(name='simplify', fetch=lambda: [incoming])]
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            path = Path(temp) / 'listings.json'
            store.save_listings({old.uid: old}, path)
            result = run_poll(sources, path)
        self.assertEqual(list(result.all_listings), [incoming.uid])
        self.assertTrue(result.all_listings[incoming.uid].emailed)


class HealthCommandTests(unittest.TestCase):
    def setUp(self):
        self.saved_meta = {}
        self.saved_listings = {}
        self.source = SimpleNamespace(name='ashby', slug='acme', company_name='Acme', fetch=lambda: [])
        self.send = Mock()
        self.initial = job()
        self.initial.emailed = False
        for mock in (
            patch.object(cli, '_build_sources', side_effect=lambda _: [self.source]),
            patch.object(store, 'load_listings', return_value={self.initial.uid: self.initial}),
            patch.object(store, 'load_meta', return_value={}),
            patch.object(store, 'save_listings', side_effect=lambda data: self.saved_listings.update(data)),
            patch.object(store, 'save_meta', side_effect=lambda data: self.saved_meta.update(data)),
            patch.object(cli.notify, 'send_digest', self.send),
            patch.dict('os.environ', {'GMAIL_ADDRESS': 'sender@example.invalid',
                                     'GMAIL_APP_PASSWORD': 'test', 'NOTIFY_TO': 'to@example.invalid'}),
        ):
            mock.start()
            self.addCleanup(mock.stop)

    def run_command(self, *, dry=False, email=False):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return cli.cmd_poll(argparse.Namespace(email=email, dry_run=dry))

    def test_total_failure_is_persisted_and_fails_without_emailing_stale_rows(self):
        self.source.fetch = Mock(side_effect=ValueError())
        self.assertEqual(self.run_command(email=True), 1)
        self.assertEqual(self.saved_meta['poll_health']['status'], 'failed')
        self.assertIn(self.initial.uid, self.saved_listings)
        self.send.assert_not_called()

    def test_email_failure_still_persists_poll_health_and_leaves_alert_pending(self):
        self.source.fetch = lambda: [job()]
        self.send.side_effect = smtplib.SMTPException('private diagnostic')
        self.assertEqual(self.run_command(email=True), 1)
        self.assertEqual(self.saved_meta['poll_health']['status'], 'healthy')
        self.assertEqual(self.saved_meta['poll_health']['email_status'], 'failed')
        self.assertFalse(self.saved_listings[self.initial.uid].emailed)

    def test_missing_email_config_still_persists_health(self):
        self.source.fetch = lambda: [job()]
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(self.run_command(email=True), 1)
        self.assertEqual(self.saved_meta['poll_health']['email_status'], 'failed')
        self.send.assert_not_called()

    def test_dry_run_does_not_write_health_or_listings_or_send_email(self):
        self.assertEqual(self.run_command(dry=True, email=True), 0)
        self.assertEqual(self.saved_meta, {})
        self.assertEqual(self.saved_listings, {})
        self.send.assert_not_called()

    def test_successful_empty_source_is_healthy(self):
        self.assertEqual(self.run_command(), 0)
        self.assertEqual(self.saved_meta['poll_health']['status'], 'healthy')
        self.assertEqual(self.saved_meta['poll_health']['sources'][0]['listing_count'], 0)


if __name__ == '__main__':
    unittest.main()
