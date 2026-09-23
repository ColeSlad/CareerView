import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import DataTable, Input, Static

from careerview import health, status_store
from careerview.config import load_config
from careerview.health import SourceCheck
from careerview.models import Listing
from careerview.tui.app import CareerViewApp
from careerview.tui.health_screen import HealthScreen


ROOT = Path(__file__).resolve().parents[1]


class TuiHealthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = status_store.connect(Path(self.temp.name) / 'status.db')
        self.addCleanup(self.db.close)
        config = load_config(ROOT / 'config.yaml', ROOT / 'companies.yaml')
        self.now = 200
        self.meta = {'poll_health': health.build_health({}, [
            SourceCheck('ashby:acme', 'Acme', 'ashby', 'acme', 100, 1, 0),
            SourceCheck('ashby:broken', 'Broken', 'ashby', 'broken', 100, 1, None, 'HTTP 404'),
        ], 90, 100, 10)}
        listing = Listing('test:1', 'test', 'Acme', 'Software Intern', 'Software',
                          ['Remote'], [], 'https://example.invalid')
        for mock in (
            patch('careerview.tui.app.status_store.connect', return_value=self.db),
            patch('careerview.tui.app.load_config', return_value=config),
            patch('careerview.tui.app.store.load_listings', return_value={listing.uid: listing}),
            patch('careerview.tui.app.store.load_meta', side_effect=lambda: self.meta),
            patch('careerview.store.now_ts', side_effect=lambda: self.now),
            patch.object(CareerViewApp, '_git_pull_best_effort'),
        ):
            mock.start()
            self.addCleanup(mock.stop)

    async def test_health_search_selection_and_shortcuts_do_not_change_listings(self):
        app = CareerViewApp()
        async with app.run_test(size=(120, 38)) as pilot:
            self.assertIn('1 failed', str(app.query_one('#health-line', Static).render()))
            await pilot.press('h')
            self.assertIsInstance(app.screen, HealthScreen)
            table = app.screen.query_one(DataTable)
            self.assertEqual(table.row_count, 2)
            self.assertEqual(str(table.get_row_at(0)[0]), 'FAILED')
            self.assertIn('HTTP 404', str(app.screen.query_one('#health-source-detail', Static).render()))
            await pilot.press('a', 'm', 'enter')
            self.assertEqual(status_store.load_all(self.db), {})
            self.assertIsInstance(app.screen, HealthScreen)
            await pilot.press('/')
            app.screen.query_one(Input).value = 'Acme'
            await pilot.pause()
            self.assertEqual(table.row_count, 1)
            self.assertEqual(app.search_text, '')
            self.assertEqual(table.get_row_at(0)[3], '0')
            app.screen.query_one(Input).value = 'missing'
            await pilot.pause()
            self.assertEqual(table.row_count, 0)
            self.assertIn('No matching', str(app.screen.query_one('#health-source-detail', Static).render()))
            await pilot.press('escape')
            self.assertEqual(app.query_one('#table', DataTable).row_count, 1)

    async def test_refresh_updates_health_and_clock_marks_it_stale(self):
        app = CareerViewApp()
        async with app.run_test(size=(120, 38)) as pilot:
            await pilot.press('h')
            self.now = 2800
            app.screen.update_summary()
            app._update_health_line()
            self.assertIn('STALE', str(app.screen.query_one('#health-summary', Static).render()))
            self.assertIn('STALE', str(app.query_one('#health-line', Static).render()))
            self.meta = {'poll_health': health.build_health(self.meta, [
                SourceCheck('ashby:acme', 'Acme', 'ashby', 'acme', 2800, 1, 0)
            ], 2790, 2800, 10)}
            await pilot.press('r')
            self.assertIn('Healthy', str(app.screen.query_one('#health-summary', Static).render()))
            self.assertNotIn('STALE', str(app.screen.query_one('#health-summary', Static).render()))
            self.assertEqual(app.screen.query_one(DataTable).row_count, 1)
            self.assertEqual(app.query_one('#table', DataTable).row_count, 1)

    async def test_legacy_empty_and_failed_sync_are_visible_at_small_size(self):
        self.meta = {'last_run': 100}
        app = CareerViewApp()
        async with app.run_test(size=(80, 24)) as pilot:
            app.sync_error = True
            app._update_health_line()
            self.assertIn('Sync failed', str(app.query_one('#health-line', Static).render()))
            await pilot.press('h')
            self.assertEqual(app.screen.query_one(DataTable).row_count, 0)
            self.assertIn('not recorded', str(app.screen.query_one('#health-summary', Static).render()))
            self.assertIn('Sync failed', str(app.screen.query_one('#health-summary', Static).render()))
            await pilot.press('escape')


if __name__ == '__main__':
    unittest.main()
