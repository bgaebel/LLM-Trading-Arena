"""No live credentials or providers: durable budget, failures and complete backup recovery."""
import json
import os
import sqlite3
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch, Mock

import arena as core
import budget
import bundle
import engine03 as engine
from backup import digest
from operations import read_db
from provenance import capture_usage
from test_operations import snapshots


class BudgetBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'live.sqlite3'
        self.con = core.open_db(str(self.path))
        clean = {k: v for k, v in os.environ.items() if not k.startswith(('LLM_DAILY_', 'LLM_CALL_', 'OPENAI_INPUT_', 'OPENAI_OUTPUT_', 'ANTHROPIC_INPUT_', 'ANTHROPIC_OUTPUT_'))}
        clean.update(OPENAI_API_KEY='test-only', ANTHROPIC_API_KEY='')
        self.environment = patch.dict(os.environ, clean, clear=True)
        self.environment.start()
        self.quotes = {'BTCEUR': core.Quote(66000, 66005), 'ETHEUR': core.Quote(3200, 3200.2)}
        core.record_live_quotes(self.con, self.quotes)

    def tearDown(self):
        self.environment.stop()
        self.con.close()
        self.temp.cleanup()

    def config(self, cap='1', hold='.6'):
        os.environ.update(LLM_DAILY_BUDGET_EUR=cap, LLM_CALL_RESERVE_EUR=hold,
                          OPENAI_INPUT_EUR_PER_MILLION='1', OPENAI_OUTPUT_EUR_PER_MILLION='1',
                          ANTHROPIC_INPUT_EUR_PER_MILLION='1', ANTHROPIC_OUTPUT_EUR_PER_MILLION='1')

    def attempt(self, agent='gpt'):
        with self.con:
            row = self.con.execute('INSERT INTO llm_calls(ts,agent,symbol,ref_mid,status) VALUES(?,?,?,?,?)',
                                   (core.utcnow(), agent, 'BTCEUR', 66000, 'PENDING'))
        return row.lastrowid

    def test_pending_reservation_survives_restart_and_blocks_next_call(self):
        self.config()
        budget.reserve(self.con, self.attempt(), 'gpt')
        self.con.close()
        self.con = core.open_db(str(self.path))
        with self.assertRaises(budget.BudgetBlocked):
            budget.reserve(self.con, self.attempt(), 'gpt')

    def test_known_usage_settles_and_releases_unused_reservation(self):
        self.config()
        first = self.attempt()
        budget.reserve(self.con, first, 'gpt')
        result = budget.settle(self.con, first, {'input_tokens': 100000, 'output_tokens': 0}, 'ok', 1)
        self.assertEqual(result['charge_eur'], '0.1')
        budget.reserve(self.con, self.attempt(), 'gpt')

    def test_timeout_retains_full_reservation(self):
        self.config()
        first = self.attempt()
        budget.reserve(self.con, first, 'gpt')
        result = budget.settle(self.con, first, None, 'timeout', 35)
        self.assertEqual(result['charge_eur'], '0.6')
        self.assertIsNone(result['estimated_cost_eur'])
        with self.assertRaises(budget.BudgetBlocked):
            budget.reserve(self.con, self.attempt(), 'gpt')

    def test_overrun_blocks_further_requests_even_below_daily_cap(self):
        self.config(cap='5')
        first = self.attempt()
        budget.reserve(self.con, first, 'gpt')
        result = budget.settle(self.con, first, {'input_tokens': 2000000, 'output_tokens': 0}, 'ok', 1)
        self.assertTrue(result['reservation_exceeded'])
        with self.assertRaises(budget.BudgetBlocked):
            budget.reserve(self.con, self.attempt(), 'gpt')

    def test_cap_is_shared_by_providers(self):
        self.config()
        budget.reserve(self.con, self.attempt('gpt'), 'gpt')
        with self.assertRaises(budget.BudgetBlocked):
            budget.reserve(self.con, self.attempt('claude'), 'claude')

    def test_cap_without_prices_prevents_network(self):
        os.environ.update(LLM_DAILY_BUDGET_EUR='1', LLM_CALL_RESERVE_EUR='.1')
        call = Mock(side_effect=AssertionError('Network must not be reached'))
        engine.llm_cycle(self.con, snapshots(self.quotes), llm_fn=call)
        call.assert_not_called()
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM llm_calls WHERE status='BUDGET_BLOCKED'").fetchone()[0], 2)

    def test_zero_cap_blocks_every_call(self):
        self.config(cap='0')
        with self.assertRaises(budget.BudgetBlocked):
            budget.reserve(self.con, self.attempt(), 'gpt')

    def test_legacy_unknown_attempts_are_not_assumed_free(self):
        self.config()
        self.attempt()
        with self.assertRaises(budget.BudgetBlocked):
            budget.reserve(self.con, self.attempt(), 'gpt')

    def test_cached_usage_does_not_invent_provider_specific_price(self):
        self.config()
        first = self.attempt()
        budget.reserve(self.con, first, 'gpt')
        receipt = budget.settle(self.con, first, {'input_tokens': 10, 'output_tokens': 1, 'cache_creation_input_tokens': 5}, 'ok', 1)
        self.assertIsNone(receipt['estimated_cost_eur'])
        self.assertEqual(receipt['charge_eur'], '0.6')

    def test_invalid_response_still_records_usage_and_cost(self):
        self.config(hold='.1')
        def invalid(*args):
            capture_usage({'usage': {'input_tokens': 10, 'output_tokens': 5}})
            return {'action': 'INVALID'}, 'test-model'
        engine.llm_cycle(self.con, snapshots(self.quotes), llm_fn=invalid)
        _, ledger = budget.ledger(self.con)
        self.assertEqual(len(ledger['entries']), 2)
        self.assertTrue(all(entry['estimated_cost_eur'] == '0.000015' for entry in ledger['entries'].values()))
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM trades').fetchone()[0], 0)

    def test_provider_exception_still_records_received_usage(self):
        self.config(hold='.1')
        def failed(*args):
            capture_usage({'usage': {'input_tokens': 10, 'output_tokens': 5}})
            raise ValueError('Simulated schema failure after response')
        engine.llm_cycle(self.con, snapshots(self.quotes), llm_fn=failed)
        _, ledger = budget.ledger(self.con)
        self.assertTrue(all(entry['state'] == 'request_failed' and entry['estimated_cost_eur'] == '0.000015'
                            for entry in ledger['entries'].values()))

    def test_failed_snapshot_does_not_call_provider_and_releases_reservation(self):
        self.config(hold='.1')
        call = Mock(side_effect=AssertionError('Network must not be reached'))
        with patch('provenance.reserve_snapshot', side_effect=OSError('disk full')):
            engine.llm_cycle(self.con, snapshots(self.quotes), llm_fn=call)
        call.assert_not_called()
        _, ledger = budget.ledger(self.con)
        self.assertTrue(all(entry['charge_eur'] == '0' for entry in ledger['entries'].values()))

    def make_audited_decisions(self):
        def hold(*args):
            capture_usage({'usage': {'input_tokens': 10, 'output_tokens': 5}})
            return {'action': 'HOLD', 'target_fraction': 0, 'confidence': .5, 'reason': 'Synthetic test'}, 'test-model'
        self.config(hold='.1')
        engine.llm_cycle(self.con, snapshots(self.quotes), llm_fn=hold)

    def test_bundle_restores_database_snapshots_and_budget_together(self):
        self.make_audited_decisions()
        destination = self.root / 'complete.zip'
        bundle.backup_bundle(self.path, destination)
        output = self.root / 'restored'
        bundle.restore_bundle(destination, output)
        restored = read_db(output / self.path.name)
        try:
            self.assertEqual(restored.execute('SELECT COUNT(*) FROM decisions').fetchone()[0], 2)
            self.assertEqual(budget.summary(restored)['estimated_cost_eur'], '0.000030')
            for row in restored.execute('SELECT inputs FROM decisions'):
                audit = json.loads(row[0])['_audit']
                snapshot = output / 'llm-audit' / (self.path.name + '-' + str(audit['attempt']) + '.json')
                self.assertEqual(digest(snapshot), audit['snapshot_sha256'])
        finally: restored.close()
        with self.assertRaises(FileExistsError): bundle.restore_bundle(destination, output)

    def test_bundle_failure_preserves_earlier_snapshots(self):
        self.make_audited_decisions()
        bundle.rotate_bundles(self.path, self.root / 'backups', 1)
        previous = list((self.root / 'backups').glob('*.zip'))
        next((self.root / 'llm-audit').glob('*-1.json')).write_text('{}')
        with self.assertRaises(ValueError): bundle.rotate_bundles(self.path, self.root / 'backups', 1)
        self.assertEqual(list((self.root / 'backups').glob('*.zip')), previous)

    def test_bundle_retention_keeps_manual_archives(self):
        manual = self.root / 'backups' / 'manual.zip'
        bundle.backup_bundle(self.path, manual)
        for _ in range(3): bundle.rotate_bundles(self.path, manual.parent, 1)
        self.assertEqual(len(list(manual.parent.glob('*.zip'))), 2)
        bundle.verify_bundle(manual)

    def test_bundle_rejects_unlisted_traversal_entry(self):
        path = self.root / 'complete.zip'
        bundle.backup_bundle(self.path, path)
        with zipfile.ZipFile(path, 'a') as archive: archive.writestr('../outside', b'no')
        with self.assertRaises(ValueError): bundle.restore_bundle(path, self.root / 'restored')
        self.assertFalse((self.root / 'restored').exists())

    def test_stale_feed_between_models_stops_additional_requests(self):
        calls = []
        def first(*args):
            calls.append(True)
            with self.con: self.con.execute("UPDATE market SET ts='2000-01-01T00:00:00+00:00'")
            return {'action': 'HOLD', 'target_fraction': 0, 'confidence': .5, 'reason': 'Synthetic'}, 'test'
        engine.llm_cycle(self.con, snapshots(self.quotes), llm_fn=first)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM trades').fetchone()[0], 0)

    def test_raw_database_restore_refuses_to_drop_audit_sidecars(self):
        from backup import backup_database,restore_backup
        self.make_audited_decisions()
        snapshot=self.root/'raw.sqlite3'
        backup_database(self.path,snapshot)
        with self.assertRaisesRegex(ValueError,'complete audit'):
            restore_backup(snapshot,self.root/'unsafe.sqlite3')
        self.assertFalse((self.root/'unsafe.sqlite3').exists())

    def test_restored_budget_does_not_reopen_uncertain_same_day_spend(self):
        self.make_audited_decisions()
        snapshot=self.root/'complete.zip'
        bundle.backup_bundle(self.path,snapshot)
        bundle.restore_bundle(snapshot,self.root/'restored')
        restored=core.open_db(str(self.root/'restored'/self.path.name))
        try:
            with restored:
                row=restored.execute('INSERT INTO llm_calls(ts,agent,symbol,ref_mid,status) VALUES(?,?,?,?,?)',
                                     (core.utcnow(),'gpt','BTCEUR',100,'PENDING'))
            with self.assertRaises(budget.BudgetBlocked):budget.reserve(restored,row.lastrowid,'gpt')
            self.assertTrue(budget.summary(restored)['restore_day_block'])
        finally:restored.close()

    def test_nested_cache_usage_is_not_mispriced_as_standard_input(self):
        from provenance import take_usage
        capture_usage({'usage':{'input_tokens':100,'output_tokens':10,'input_tokens_details':{'cached_tokens':80,'cache_write_tokens':20}}})
        usage=take_usage()
        self.assertEqual(usage['cached_tokens'],80)
        self.config()
        first=self.attempt()
        budget.reserve(self.con,first,'gpt')
        result=budget.settle(self.con,first,usage,'ok',1)
        self.assertIsNone(result['estimated_cost_eur'])
        self.assertEqual(result['charge_eur'],'0.6')

    def test_bad_price_configuration_does_not_create_unknown_external_spend(self):
        os.environ['OPENAI_INPUT_EUR_PER_MILLION']='invalid'
        call=Mock(side_effect=AssertionError('Network must not be reached'))
        engine.llm_cycle(self.con,snapshots(self.quotes),llm_fn=call)
        call.assert_not_called()
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM llm_calls WHERE status='NOT_SENT'").fetchone()[0],2)
        self.config()
        budget.reserve(self.con,self.attempt(),'gpt')


if __name__ == '__main__': unittest.main()
