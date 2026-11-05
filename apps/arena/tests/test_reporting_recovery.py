"""Filtered local HTTP and mocked provider/feed failures; no external network."""
import csv
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

import arena as core
import bitvavo
import main
from operations import Health
from provenance import strict_response, take_usage
from reporting import filters


class ReportingRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.sqlite3'
        self.con = core.open_db(str(self.path))

    def tearDown(self):
        self.con.close()
        self.temp.cleanup()

    def test_filter_offsets_are_normalized_to_utc(self):
        self.assertEqual(filters({'start': ['2026-01-01T02:00:00+02:00']})['start'], '2026-01-01T00:00:00+00:00')

    def test_invalid_filters_are_rejected(self):
        for query in ({'agent': ["gpt' OR 1=1"]}, {'symbol': ['BTC-EUR']},
                      {'start': ['not-a-date']}, {'start': ['2027-01-01'], 'end': ['2026-01-01']}):
            with self.subTest(query=query):
                with self.assertRaises(ValueError): filters(query)

    def seed_history(self):
        with self.con:
            for agent, symbol, ts in [('gpt', 'BTCEUR', '2026-01-01T00:00:00+00:00'),
                                      ('claude', 'BTCEUR', '2026-01-01T00:00:00+00:00'),
                                      ('gpt', 'ETHEUR', '2026-01-02T00:00:00+00:00')]:
                self.con.execute('INSERT INTO trades(ts,agent,symbol,side,qty,fill,notional,fee,slip_rate) VALUES(?,?,?,?,?,?,?,?,?)',
                                 (ts, agent, symbol, 'BUY', 1, 100, 100, .25, .0003))

    def test_filtered_json_csv_and_bad_request_on_real_loopback_http(self):
        self.seed_history()
        server = main.make_server(str(self.path), False, 0, Health())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with urllib.request.urlopen(base + '/api/history?agent=gpt&symbol=BTCEUR') as response:
                report = json.load(response)
            self.assertEqual(len(report['trades']), 1)
            self.assertEqual(report['trades'][0]['agent'], 'gpt')
            with urllib.request.urlopen(base + '/api/trades.csv?agent=gpt&end=2026-01-01T23%3A59%3A59Z') as response:
                rows = list(csv.DictReader(io.StringIO(response.read().decode('utf-8-sig'))))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['symbol'], 'BTCEUR')
            with urllib.request.urlopen(base + '/api/export.json?symbol=ETHEUR') as response:
                report = json.load(response)
            self.assertEqual(len(report['history']['trades']), 1)
            self.assertFalse(report['demo'])
            with self.assertRaises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(base + '/api/performance?agent=unknown')
            self.assertEqual(exc.exception.code, 400)
            self.assertEqual(self.con.execute('SELECT COUNT(*) FROM trades').fetchone()[0], 3)
        finally:
            server.shutdown()
            thread.join(3)
            server.server_close()

    def test_public_rate_limit_cooldown_is_shared_and_recovers(self):
        valid = [{'market': 'BTC-EUR', 'bid': '66000', 'ask': '66005'},
                 {'market': 'ETH-EUR', 'bid': '3200', 'ask': '3200.2'}]
        now = [100.]
        with patch('bitvavo._retry_not_before', 0.), patch('bitvavo.time.monotonic', side_effect=lambda: now[0]), \
             patch('arena.http_json', side_effect=[core.HTTPFailure(429, 10), valid]) as call:
            with self.assertRaises(core.HTTPFailure): bitvavo.quotes()
            with self.assertRaises(core.HTTPFailure): bitvavo.closed_candles('BTCEUR', 1)
            self.assertEqual(call.call_count, 1)
            now[0] = 111
            self.assertEqual(set(bitvavo.quotes()), set(core.SYMBOLS))
            self.assertEqual(call.call_count, 2)

    def test_network_failure_does_not_write_then_quote_worker_recovers(self):
        stop = threading.Event()
        valid = [{'market': 'BTC-EUR', 'bid': '66000', 'ask': '66005'},
                 {'market': 'ETH-EUR', 'bid': '3200', 'ask': '3200.2'}]
        calls = []
        def source(*args):
            calls.append(True)
            if len(calls) == 1:
                self.assertEqual(self.con.execute('SELECT COUNT(*) FROM trades').fetchone()[0], 0)
                raise urllib.error.URLError('Simulated disconnect')
            stop.set()
            return valid
        with patch('bitvavo._retry_not_before', 0.), patch('arena.http_json', side_effect=source), \
             patch.object(stop, 'wait', return_value=False):
            main.quote_worker(str(self.path), stop, Health())
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM trades').fetchone()[0], 2)

    def test_http_429_exposes_safe_status_and_delay_without_body(self):
        failure = urllib.error.HTTPError('https://example.invalid', 429, 'error', {'Retry-After': '10'}, io.BytesIO(b'PRIVATE BODY'))
        with patch('urllib.request.urlopen', side_effect=failure):
            with self.assertRaises(core.HTTPFailure) as exc:
                core.http_json('https://example.invalid')
        self.assertEqual(exc.exception.status, 429)
        self.assertEqual(exc.exception.retry_after, 10)
        self.assertNotIn('PRIVATE', str(exc.exception))

    def test_extra_model_fields_rejected_before_legacy_normalization(self):
        signal = {'action': 'HOLD', 'target_fraction': 0, 'confidence': .5, 'reason': 'test', 'unexpected': True}
        response = {'output': [{'content': [{'type': 'output_text', 'text': json.dumps(signal)}]}]}
        with self.assertRaises(ValueError): strict_response(response, 'https://api.openai.com/v1/responses')

    def test_inconsistent_model_action_target_rejected(self):
        for action, target in [('BUY', 0), ('SELL', .45)]:
            signal = {'action': action, 'target_fraction': target, 'confidence': .5, 'reason': 'test'}
            response = {'content': [{'type': 'text', 'text': json.dumps(signal)}]}
            with self.assertRaises(ValueError): strict_response(response, 'https://api.anthropic.com/v1/messages')

    def test_usage_captured_even_when_response_schema_fails(self):
        response = {'usage': {'input_tokens': 10, 'output_tokens': 2}, 'output': []}
        stream = Mock()
        stream.__enter__ = Mock(return_value=io.BytesIO(json.dumps(response).encode()))
        stream.__exit__ = Mock(return_value=False)
        take_usage()
        with patch('urllib.request.urlopen', return_value=stream):
            with self.assertRaises(ValueError):
                core.http_json('https://api.openai.com/v1/responses', payload={'model': 'test'})
        self.assertEqual(take_usage(), {'input_tokens': 10, 'output_tokens': 2})

    def test_rate_limit_reset_header_in_milliseconds_is_respected(self):
        failure=urllib.error.HTTPError('https://example.invalid',429,'error',{'bitvavo-ratelimit-resetat':'1900000900000'},io.BytesIO(b''))
        with patch('urllib.request.urlopen',side_effect=failure),patch('arena.time.time',return_value=1900000000):
            with self.assertRaises(core.HTTPFailure) as exc:core.http_json('https://example.invalid')
        self.assertEqual(exc.exception.retry_after,900)

    def test_public_429_without_headers_uses_conservative_cooldown(self):
        with patch('bitvavo._retry_not_before',0.),patch('bitvavo.time.monotonic',return_value=100.),patch('arena.http_json',side_effect=core.HTTPFailure(429)) as call:
            with self.assertRaises(core.HTTPFailure):bitvavo.quotes()
            self.assertEqual(bitvavo._retry_not_before,1000.)
            with self.assertRaises(core.HTTPFailure):bitvavo.quotes()
            self.assertEqual(call.call_count,1)

    def test_conflicting_duplicate_quote_is_rejected(self):
        rows=[{'market':'BTC-EUR','bid':'66000','ask':'66005'},
              {'market':'BTC-EUR','bid':'67000','ask':'67005'},
              {'market':'ETH-EUR','bid':'3200','ask':'3200.2'}]
        with patch('bitvavo._retry_not_before',0.),patch('arena.http_json',return_value=rows):
            with self.assertRaises(ValueError):bitvavo.quotes()

    def test_fractional_millisecond_candle_stamp_is_not_silently_rounded(self):
        rows=[[1800000000001,100,101,99,100,1]]
        with patch('bitvavo._retry_not_before',0.),patch('arena.http_json',return_value=rows):
            with self.assertRaises(ValueError):bitvavo.closed_candles('BTCEUR',1,now_epoch=1800000120)


if __name__ == '__main__': unittest.main()
