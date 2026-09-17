import argparse
import io
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx

from careerview import cli, store
from careerview.config import load_config
from careerview.filters import internship_category, is_relevant, locations_pass
from careerview.models import Listing
from careerview.poller import PollResult, dedup, run_poll
from careerview.sources.ashby import AshbySource
from careerview.sources.base import fetch_with_retry


def listing(uid='ashby:decagon:123', **kwargs):
    fields = dict(uid=uid, source='ashby', company='Decagon',
                  title='Engineering Intern (Summer 2027)', category='Software',
                  locations=['San Francisco'], terms=[],
                  url='https://jobs.ashbyhq.com/decagon/123/application', date_posted=100)
    fields.update(kwargs)
    return Listing(**fields)


class LocationTests(unittest.TestCase):
    def test_explicit_non_software_internships_are_not_mislabeled(self):
        for title in ('Accounting Intern', 'Mechanical Engineering Intern',
                      '2027 Electrical Engineer Intern', 'Product Management Intern',
                      'Summer Marketing Internship', 'Procurement/Buyer Co-op'):
            with self.subTest(title=title):
                self.assertEqual(internship_category(title), 'Other')
        for title in ('Software Engineering Intern - Finance', 'Flight Software Intern',
                      'Embedded Systems Intern', 'Engineering Intern', 'AI Research Intern',
                      'Data Science Intern', 'Quantitative Research Intern'):
            with self.subTest(title=title):
                self.assertEqual(internship_category(title, 'Engineering'), 'Software')
        self.assertEqual(internship_category('Summer Intern', 'Marketing'), 'Other')
        self.assertEqual(internship_category('Software Intern', 'Finance'), 'Software')

    def test_us_city_and_board_formats(self):
        for location in ('San Francisco', 'SF', 'SF Office', 'San Francisco - SF9',
                         'NYC', 'New York City', 'Hybrid - San Francisco',
                         'Boston (Hybrid)', 'San Francisco, California',
                         'Atlanta, Georgia', 'Seattle, WA', 'US, California, Palo Alto',
                         'San Francisco, Seattle, New York City',
                         'London; New York, NY', 'London / San Francisco',
                         'San Francisco, CA • New York, NY'):
            with self.subTest(location=location):
                self.assertTrue(locations_pass(listing(locations=[location]), 'us_remote'))

    def test_non_us_locations_are_not_city_substring_matches(self):
        for location in ('London', 'Toronto', 'Toronto, ON', 'Vancouver, BC',
                         'London, UK', 'Paris, France', 'Singapore', 'San Francisco, Argentina',
                         'Boston, United Kingdom', 'Bangalore, India', 'Tokyo, Japan'):
            with self.subTest(location=location):
                self.assertFalse(locations_pass(listing(locations=[location]), 'us_remote'))
        self.assertTrue(locations_pass(listing(locations=[]), 'us_remote'))
        self.assertTrue(locations_pass(listing(locations=['Remote']), 'us_remote'))
        self.assertTrue(locations_pass(listing(locations=['London']), 'all'))

    def test_ashby_preserves_structured_countries_and_null_addresses(self):
        jobs = [dict(id='one', title='Engineering Intern', location='HQ',
                     address={'postalAddress': {'addressCountry': 'United States'}},
                     secondaryLocations=[{'location': 'Toronto', 'address': {'postalAddress': {'addressCountry': 'Canada'}}},
                                         {'location': 'Boston', 'address': {'postalAddress': None}}]),
                dict(id='two', title='Engineering Intern', location='London', address=None)]
        response = Mock()
        response.json.return_value = {'jobs': jobs}
        with patch('careerview.sources.ashby.httpx.get', return_value=response):
            result = AshbySource('example', 'Example', ['intern'], []).fetch()
        self.assertEqual(result[0].locations, ['HQ, United States', 'Toronto, Canada', 'Boston'])
        self.assertTrue(locations_pass(result[0], 'us_remote'))
        self.assertFalse(locations_pass(result[1], 'us_remote'))


class PollingTests(unittest.TestCase):
    def test_transient_failures_retry_but_missing_boards_do_not(self):
        source = SimpleNamespace(fetch=Mock(side_effect=[httpx.ReadTimeout('timed out'), [listing()]]))
        with patch('careerview.sources.base.time.sleep'):
            self.assertEqual(len(fetch_with_retry(source)), 1)
        self.assertEqual(source.fetch.call_count, 2)
        response = httpx.Response(404, request=httpx.Request('GET', 'https://example.invalid'))
        error = httpx.HTTPStatusError('missing board', request=response.request, response=response)
        source.fetch = Mock(side_effect=error)
        with self.assertRaises(httpx.HTTPStatusError):
            fetch_with_retry(source)
        source.fetch.assert_called_once()

    def test_decagon_copies_collapse_but_distinct_requisitions_survive(self):
        direct = listing()
        community = listing('simplify:123', source='simplify', title='Engineering Intern',
                            locations=['SF'], date_posted=200,
                            url=direct.url + '?embed=true&utm_source=test')
        other = listing('ashby:decagon:456', url='https://jobs.ashbyhq.com/decagon/456')
        self.assertEqual([job.uid for job in dedup([community, direct, other])], [direct.uid, other.uid])

    def test_greenhouse_and_lever_application_aliases(self):
        for first, second in (
            ('https://boards.greenhouse.io/acme/jobs/123', 'https://job-boards.greenhouse.io/acme/jobs/123?gh_src=test'),
            ('https://job-boards.greenhouse.io/acme/jobs/123', 'https://boards.greenhouse.io/embed/job_app?token=123'),
            ('https://jobs.lever.co/acme/123', 'https://jobs.lever.co/acme/123/apply?lever-source=test'),
        ):
            with self.subTest(first=first):
                self.assertEqual(len(dedup([listing(url=first), listing('other', title='Intern', url=second)])), 1)

    def test_alert_state_survives_feed_changes(self):
        old = listing('simplify:old', source='simplify', emailed=True, first_seen=42,
                      url='https://jobs.ashbyhq.com/decagon/123/application?embed=true')
        incoming = listing()
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'listings.json'
            store.save_listings({old.uid: old}, target)
            source = SimpleNamespace(name='ashby', slug='decagon', fetch=lambda: [incoming])
            with redirect_stdout(io.StringIO()):
                result = run_poll([source], target)
        self.assertEqual(result.new_listings, [])
        self.assertTrue(result.all_listings[incoming.uid].emailed)
        self.assertEqual(result.all_listings[incoming.uid].first_seen, 42)

    def test_concurrent_fetches_preserve_order_and_isolate_failures(self):
        barrier = threading.Barrier(2, timeout=3)
        def fetch(uid):
            barrier.wait()
            return [listing(uid, url=f'https://jobs.ashbyhq.com/decagon/{uid}')]
        sources = [SimpleNamespace(name='test', slug=uid, fetch=lambda uid=uid: fetch(uid))
                   for uid in ('one', 'two')]
        sources.append(SimpleNamespace(name='test', slug='broken', fetch=Mock(side_effect=RuntimeError('unavailable'))))
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()) as output:
            result = run_poll(sources, Path(temp) / 'missing.json')
        self.assertEqual(list(result.all_listings), ['one', 'two'])
        self.assertIn('test:broken fetch failed', output.getvalue())
        self.assertTrue(all(job.emailed for job in result.all_listings.values()))


class EmailEligibilityTests(unittest.TestCase):
    def run_command(self, result, email=True, dry_run=False):
        config = load_config()
        with patch.object(cli, 'load_config', return_value=config), \
             patch.object(cli, '_build_sources', return_value=[]), \
             patch.object(cli, 'run_poll', return_value=result), \
             patch.object(cli.notify, 'send_digest', return_value=True) as send, \
             patch.object(cli.store, 'save_listings') as save, \
             patch.object(cli.store, 'save_meta'), \
             patch.dict('os.environ', {'GMAIL_ADDRESS': 'sender@example.invalid', 'GMAIL_APP_PASSWORD': 'test', 'NOTIFY_TO': 'recipient@example.invalid'}), \
             redirect_stdout(io.StringIO()):
            code = cli.cmd_poll(argparse.Namespace(email=email, dry_run=dry_run))
        self.assertEqual(code, 0)
        return send, save

    def test_previously_filtered_decagon_gets_one_catchup_alert(self):
        missed = listing(first_seen=42, emailed=False)
        self.assertTrue(is_relevant(missed, load_config().relevance))
        result = PollResult({missed.uid: missed}, [], False, 1)
        send, save = self.run_command(result)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], [missed])
        self.assertTrue(missed.emailed)
        self.assertTrue(save.called)
        send_again, _ = self.run_command(result)
        send_again.assert_not_called()

    def test_inactive_and_still_irrelevant_roles_do_not_alert(self):
        jobs = [listing('inactive', active=False), listing('foreign', locations=['London']),
                listing('experienced', title='Senior Software Engineer')]
        send, _ = self.run_command(PollResult({j.uid:j for j in jobs}, [], False, 3))
        send.assert_not_called()

    def test_first_run_stays_silent_and_dry_run_does_not_consume_alerts(self):
        missed = listing()
        send, _ = self.run_command(PollResult({missed.uid:missed}, [], True, 1))
        send.assert_not_called()
        result = PollResult({missed.uid:missed}, [], False, 1)
        send, save = self.run_command(result, dry_run=True)
        send.assert_not_called()
        save.assert_not_called()
        self.assertFalse(missed.emailed)
        send, save = self.run_command(result, email=False)
        send.assert_not_called()
        self.assertTrue(save.called)
        self.assertFalse(missed.emailed)


if __name__ == '__main__':
    unittest.main()
