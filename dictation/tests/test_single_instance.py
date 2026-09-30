import os
from pathlib import Path
import runpy
import subprocess
import sys
import unittest
import uuid

WindowsInstance = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / 'single_instance.py')
)['WindowsInstance']


@unittest.skipUnless(os.name == 'nt', 'Windows instance guard')
class WindowsInstanceTests(unittest.TestCase):
    def test_other_process_signals_and_crash_releases_guard(self):
        name = 'Local\\dictation-test-' + uuid.uuid4().hex
        script = (
            'import sys; from single_instance import WindowsInstance; '
            'instance = WindowsInstance(sys.argv[1]); '
            'print(instance.primary, flush=True); sys.stdin.readline(); instance.close()'
        )
        process = subprocess.Popen(
            [sys.executable, '-c', script, name],
            cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self.assertEqual(process.stdout.readline().strip(), 'True')
            second = WindowsInstance(name)
            try:
                self.assertFalse(second.primary)
                self.assertTrue(second.activation_requested())
            finally:
                second.close()
            process.kill()
            process.wait(timeout=5)
            replacement = WindowsInstance(name)
            try:
                self.assertTrue(replacement.primary)
                self.assertFalse(replacement.activation_requested())
            finally:
                replacement.close()
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    def test_duplicate_signals_original_and_does_not_own_instance(self):
        name = 'Local\\dictation-test-' + uuid.uuid4().hex
        first = WindowsInstance(name)
        try:
            self.assertTrue(first.primary)
            self.assertFalse(first.activation_requested())
            for _ in range(3):
                second = WindowsInstance(name)
                try:
                    self.assertFalse(second.primary)
                finally:
                    second.close()
                self.assertTrue(first.activation_requested())
                self.assertFalse(first.activation_requested())
        finally:
            first.close()
        reopened = WindowsInstance(name)
        try:
            self.assertTrue(reopened.primary)
        finally:
            reopened.close()


if __name__ == '__main__':
    unittest.main()