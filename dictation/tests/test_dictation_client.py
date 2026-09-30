import io
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

from dictation_client import CorrectionCancelled, DictationClient


SKILL = Path(__file__).resolve().parents[1] / '.github/skills/correct-dictation/SKILL.md'


class DictationClientTests(unittest.TestCase):
    def setUp(self):
        self.client = DictationClient()
        self.sent = []
        self.client.send = self.sent.append

    def response(self, result):
        self.client.messages.put({'id': self.client.sequence + 1, 'result': result})

    def update(self, session, kind, text):
        self.client.messages.put({'method': 'session/update', 'params': {
            'sessionId': session,
            'update': {'sessionUpdate': kind, 'content': {'type': 'text', 'text': text}},
        }})

    def test_permission_and_client_tools_are_denied(self):
        for request_id, method in enumerate(['session/request_permission', 'fs/read_text_file',
                                             'fs/write_text_file', 'terminal/create'], start=10):
            self.client.messages.put({'id': request_id, 'method': method, 'params': {}})
        self.response({'stopReason': 'end_turn'})
        self.client.request('session/prompt', {'sessionId': 'current'})
        self.assertEqual(self.sent[1]['result'], {'outcome': {'outcome': 'cancelled'}})
        self.assertTrue(all(message['error']['code'] == -32601 for message in self.sent[2:]))

    def test_only_current_session_answer_is_streamed(self):
        self.update('previous', 'agent_message_chunk', 'Old text')
        self.update('current', 'agent_thought_chunk', 'Hidden reasoning')
        self.update('current', 'agent_message_chunk', 'Hello ')
        self.update('current', 'agent_message_chunk', 'world.')
        self.response({'stopReason': 'end_turn'})
        chunks = []
        self.client.request('session/prompt', {'sessionId': 'current'}, on_text=chunks.append)
        self.assertEqual(''.join(chunks), 'Hello world.')

    def test_tool_activity_stops_correction(self):
        self.update('current', 'tool_call', '')
        with self.assertRaisesRegex(RuntimeError, 'tool call'):
            self.client.request('session/prompt', {'sessionId': 'current'})

    def test_cancellation_is_acknowledged_without_streaming_late_text(self):
        cancelled = threading.Event()
        cancelled.set()
        self.update('current', 'agent_message_chunk', 'Late output')
        self.response({'stopReason': 'cancelled'})
        chunks = []
        with self.assertRaises(CorrectionCancelled):
            self.client.request('session/prompt', {'sessionId': 'current'},
                                cancelled=cancelled, on_text=chunks.append)
        self.assertEqual(self.sent[1]['method'], 'session/cancel')
        self.assertEqual(chunks, [])

    def test_timeout_is_bounded(self):
        with patch('dictation_client.time.monotonic', side_effect=[0, 181, 181, 187]):
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                self.client.request('session/prompt', {'sessionId': 'current'})
        self.assertEqual(self.sent[-1]['method'], 'session/cancel')

    def test_transport_and_rpc_errors(self):
        self.client.messages.put({'transport_error': 'Disconnected'})
        with self.assertRaisesRegex(RuntimeError, 'Disconnected'):
            self.client.request('initialize', {})
        self.client.messages.put({'id': 2, 'error': {'message': 'Sign in first'}})
        with self.assertRaisesRegex(RuntimeError, 'Sign in first'):
            self.client.request('initialize', {})

    def test_each_correction_uses_a_fresh_session_and_closes_it(self):
        self.client.start = Mock()
        self.client.workspace = Mock(name='workspace')
        self.client.capabilities = {'close': {}}
        session_ids = iter(['first', 'second'])
        prompts = []
        closed = []

        def request(method, params, **kwargs):
            if method == 'session/new':
                self.assertEqual(params['mcpServers'], [])
                return {'sessionId': next(session_ids)}
            if method == 'session/prompt':
                prompts.append(params)
                kwargs['on_text']('Corrected.')
                return {'stopReason': 'end_turn'}
            closed.append(params['sessionId'])
            return {}

        self.client.request = request
        self.assertEqual(self.client.correct('alpha transcript', SKILL), 'Corrected.')
        self.assertEqual(self.client.correct('beta transcript', SKILL), 'Corrected.')
        self.assertEqual(closed, ['first', 'second'])
        self.assertNotIn('alpha transcript', prompts[1]['prompt'][0]['text'])
        self.assertEqual(prompts[1]['sessionId'], 'second')

    def test_failure_closes_connection_and_does_not_retry_prompt(self):
        self.client.start = Mock()
        self.client.workspace = Mock()
        self.client.request = Mock(side_effect=[{'sessionId': 'current'}, RuntimeError('Disconnected')])
        self.client.close = Mock()
        with self.assertRaisesRegex(RuntimeError, 'Disconnected'):
            self.client.correct('hello', SKILL)
        self.assertEqual(self.client.request.call_count, 2)
        self.client.close.assert_called_once()

    def test_cancel_closes_session_not_process(self):
        self.client.start = Mock()
        self.client.workspace = Mock()
        self.client.capabilities = {'close': {}}
        self.client.request = Mock(side_effect=[{'sessionId': 'current'}, CorrectionCancelled('Cancelled.'), {}])
        self.client.close = Mock()
        with self.assertRaises(CorrectionCancelled):
            self.client.correct('hello', SKILL)
        self.client.close.assert_not_called()
        self.assertEqual(self.client.request.call_args.args[0], 'session/close')

    def test_start_flags_environment_and_close(self):
        client = DictationClient()
        process = Mock()
        process.stdin = io.StringIO()
        process.stdout = io.StringIO(json.dumps({'id': 1, 'result': {
            'protocolVersion': 1, 'agentCapabilities': {'sessionCapabilities': {'close': {}}},
        }}) + '\n')
        process.stderr = io.StringIO()
        process.poll.return_value = None
        with patch('dictation_client.shutil.which', return_value='copilot.exe'), \
                patch('dictation_client.subprocess.Popen', return_value=process) as launch, \
                patch.dict('os.environ', {'COPILOT_ALLOW_ALL': 'true', 'COPILOT_ASSISTED_APPROVAL': 'true'}):
            client.start()
            command = launch.call_args.args[0]
            options = launch.call_args.kwargs
            self.assertIn('--acp', command)
            self.assertIn('--available-tools=', command)
            self.assertNotIn('--allow-all-tools', command)
            self.assertNotIn('COPILOT_ALLOW_ALL', options['env'])
            self.assertNotIn('COPILOT_ASSISTED_APPROVAL', options['env'])
            self.assertFalse(options.get('shell', False))
            initialize = json.loads(process.stdin.getvalue())
            self.assertFalse(initialize['params']['clientCapabilities']['terminal'])
            workspace = Path(client.workspace.name)
            client.close()
        process.kill.assert_called_once()
        self.assertFalse(workspace.exists())
        self.assertTrue(process.stdin.closed)

    def test_reader_reports_invalid_json_and_eof(self):
        for content in ['not-json\n', '']:
            client = DictationClient()
            process = Mock()
            process.stdin = io.StringIO()
            process.stdout = io.StringIO(content)
            process.stderr = io.StringIO()
            process.poll.return_value = None
            with patch('dictation_client.shutil.which', return_value='copilot.exe'), \
                    patch('dictation_client.subprocess.Popen', return_value=process):
                with self.assertRaises(RuntimeError):
                    client.start()
            self.assertIsNone(client.process)
            process.kill.assert_called_once()


if __name__ == '__main__':
    unittest.main()