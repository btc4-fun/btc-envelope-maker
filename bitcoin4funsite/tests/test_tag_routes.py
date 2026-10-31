"""Tag route integration with disposable state and explicit public fixtures."""
import sys
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from tag_access import TagLimiter, TagAudit

UID = '01020304050607'
ADDRESS = 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu'


class TagRoutes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = [100.0]
        self.lookup = Mock(return_value={'serial': '0587k45300', 'address': ADDRESS})
        self.activity = Mock()
        self.activity.snapshot.return_value = {'address': ADDRESS, 'confirmed_sats': 500,
                                               'pending_delta_sats': 0, 'transactions': []}
        self.audit = TagAudit(Path(self.temp.name) / 'audit')
        self.client = create_app({'TESTING': True, 'TAG_LOOKUP_ENABLED': True, 'TAG_LOOKUP': self.lookup,
            'TAG_ACTIVITY': self.activity, 'TAG_AUDIT': self.audit,
            'TAG_LIMITER': TagLimiter(str(Path(self.temp.name) / 'gate.db'), b'x'*32,
                                      lambda: self.clock[0])}).test_client()

    def test_lookup_is_gated_per_ip_and_audited_without_credentials(self):
        r = self.client.get('/api/tags/' + UID, headers={'Cookie': 'secret-cookie',
                                  'Authorization': 'Bearer secret-token'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json['serial'], '0587k45300')
        self.lookup.assert_called_once_with(UID)
        self.activity.snapshot.assert_called_once_with(ADDRESS, after_txid=None)
        denied = self.client.get('/api/tags/11121314151617')
        self.assertEqual(denied.status_code, 429)
        self.assertEqual(denied.headers['Retry-After'], '20')
        self.assertEqual(self.lookup.call_count, 1)
        self.clock[0] += 20
        self.assertEqual(self.client.get('/api/tags/' + UID).status_code, 200)
        logs = ''.join(p.read_text() for p in (Path(self.temp.name)/'audit').glob('*.jsonl'))
        self.assertNotIn('secret-token', logs)
        self.assertNotIn('secret-cookie', logs)
        self.assertIn('429', logs)

    def test_disabled_by_default_has_no_data_or_audit_side_effects(self):
        with patch.dict('os.environ', {'TAG_LOOKUP_ENABLED': ''}):
            audit = Mock()
            limiter = Mock()
            client = create_app({'TESTING': True, 'TAG_LOOKUP': self.lookup,
                                 'TAG_AUDIT': audit, 'TAG_LIMITER': limiter,
                                 'TAG_ACTIVITY': self.activity}).test_client()
            response = client.get('/api/tags/' + UID)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json, {'error': 'tag_lookup_disabled'})
            audit.record.assert_not_called()
            limiter.admit.assert_not_called()
            self.lookup.assert_not_called()
            self.activity.snapshot.assert_not_called()

    def test_invalid_cursor_uid_unknown_and_upstream_failure(self):
        for path in ['/api/tags/aa', '/api/tags/' + UID + '?after_txid=bad',
                     '/api/tags/' + UID + '?extra=1',
                     '/api/tags/' + UID + '?after_txid=' + 'a'*64 + '&after_txid=' + 'b'*64]:
            self.assertEqual(self.client.get(path).status_code, 400)
        self.lookup.assert_not_called()
        self.lookup.return_value = None
        self.assertEqual(self.client.get('/api/tags/' + UID).status_code, 404)
        self.activity.snapshot.assert_not_called()
        self.clock[0] += 20
        self.lookup.return_value = {'serial': '0587k45300', 'address': ADDRESS}
        self.activity.snapshot.side_effect = RuntimeError('secret upstream error')
        r = self.client.get('/api/tags/' + UID)
        self.assertEqual(r.status_code, 503)
        self.assertNotIn('secret', r.text)
        self.assertNotIn('confirmed_sats', r.json)
        logs = ''.join(p.read_text() for p in (Path(self.temp.name)/'audit').glob('*.jsonl'))
        self.assertIn('503', logs)

    def test_audit_failure_fails_closed_before_wallet_lookup(self):
        self.client.application.config['TAG_AUDIT'] = Mock(record=Mock(side_effect=OSError('private')))
        r = self.client.get('/api/tags/' + UID)
        self.assertEqual(r.status_code, 503)
        self.lookup.assert_not_called()


    def test_real_adapter_through_route_with_bounded_fixture_transport(self):
        from chain_activity import ChainActivity
        requests = []
        def transport(url, **options):
            requests.append((url, options))
            if url.endswith('/txs/chain'):
                return b'[]'
            return json.dumps({'address': ADDRESS,
                'chain_stats': {'funded_txo_sum': 800, 'spent_txo_sum': 300},
                'mempool_stats': {'funded_txo_sum': 0, 'spent_txo_sum': 100}}).encode()
        self.client.application.config['TAG_ACTIVITY'] = ChainActivity(transport)
        response = self.client.get('/api/tags/' + UID)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['confirmed_sats'], 500)
        self.assertEqual(response.json['pending_delta_sats'], -100)
        self.assertEqual(response.json['history_scope'], 'confirmed_only')
        self.assertEqual(response.json['consistency'], 'non_atomic')
        self.assertEqual(len(requests), 2)
        for url, options in requests:
            self.assertTrue(url.startswith('https://blockstream.info/api/address/' + ADDRESS))
            self.assertEqual(options['timeout'], 4)
        self.assertEqual(self.client.get('/api/tags/' + UID).status_code, 429)
        self.assertEqual(len(requests), 2)


if __name__ == '__main__':
    unittest.main()
