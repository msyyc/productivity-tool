from pathlib import Path
import runpy
import tkinter as tk
import unittest
from unittest.mock import patch


WINDOW = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'correct_dictation.pyw'))


class SkillPathTests(unittest.TestCase):
    def test_uses_existing_repository_skill_without_a_local_copy(self):
        repository = Path(__file__).resolve().parents[2]
        relative_skill = Path('.github/skills/correct-dictation/SKILL.md')
        self.assertEqual(WINDOW['SKILL'], repository / relative_skill)
        self.assertTrue(WINDOW['SKILL'].is_file())
        self.assertFalse((repository / 'dictation' / relative_skill).exists())


class ClearInputTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        with patch('threading.Thread'):
            self.app = WINDOW['DictationWindow'](self.root)
        self.root.update_idletasks()

    def tearDown(self):
        self.root.after_cancel(self.app.poll_id)
        self.root.destroy()

    def poll(self):
        self.root.after_cancel(self.app.poll_id)
        self.app.poll()

    def test_clear_only_input_and_restore_focus(self):
        self.app.input.insert('1.0', 'Outdated text\nAnother line')
        self.app.set_output('Keep this output.')
        self.app.copy_button.configure(state='normal')
        with patch.object(self.app.input, 'focus_set') as focus:
            self.app.clear_button.invoke()
            focus.assert_called_once()
        self.assertEqual(self.app.input.get('1.0', 'end-1c'), '')
        self.assertEqual(self.app.output.get('1.0', 'end-1c'), 'Keep this output.')
        self.assertEqual(str(self.app.copy_button['state']), 'normal')
        self.app.clear_button.invoke()
        self.assertEqual(self.app.input.get('1.0', 'end-1c'), '')

    def test_clear_is_rightmost_at_minimum_window_size(self):
        self.root.geometry('480x480')
        self.root.update()
        clear = self.app.clear_button
        for button in (self.app.start_button, self.app.cancel_button):
            self.assertLessEqual(button.winfo_x() + button.winfo_width(), clear.winfo_x())
        self.assertLessEqual(clear.winfo_x() + clear.winfo_width(), clear.master.winfo_width())

    def test_clear_disabled_during_request_and_restored_after_completion(self):
        for kind in ('done', 'error'):
            self.app.input.delete('1.0', 'end')
            self.app.input.insert('1.0', 'Keep while busy')
            self.app.start()
            self.assertEqual(str(self.app.clear_button['state']), 'disabled')
            self.app.clear_input()
            self.assertEqual(self.app.input.get('1.0', 'end-1c'), 'Keep while busy')
            self.app.results.put((kind, 'Result'))
            self.poll()
            self.assertEqual(str(self.app.clear_button['state']), 'normal')

    def test_completed_output_can_be_edited_and_copied(self):
        self.app.results.put(('done', 'Corrected text.'))
        self.poll()
        self.assertEqual(str(self.app.output['state']), 'normal')
        self.app.output.delete('1.0', 'end')
        self.app.output.insert('1.0', 'Edited text.\nSecond line.')
        with patch.object(self.root, 'clipboard_clear') as clear, \
                patch.object(self.root, 'clipboard_append') as append:
            self.app.copy_button.invoke()
        clear.assert_called_once()
        append.assert_called_once_with('Edited text.\nSecond line.')
        self.assertEqual(self.app.status.get(), 'Copied')

    def test_output_editing_supports_undo_without_restoring_old_results(self):
        self.app.results.put(('done', 'First result.'))
        self.poll()
        self.app.output.insert('end', ' Edited.')
        self.app.output.edit_undo()
        self.assertEqual(self.app.output.get('1.0', 'end-1c'), 'First result.')
        self.app.results.put(('done', 'Second result.'))
        self.poll()
        with self.assertRaises(tk.TclError):
            self.app.output.edit_undo()
        self.assertEqual(self.app.output.get('1.0', 'end-1c'), 'Second result.')

    def test_output_locked_during_streaming_and_after_failed_or_cancelled_request(self):
        for cancelled in (False, True):
            self.app.results.put(('done', 'Previous result.'))
            self.poll()
            self.app.input.insert('1.0', 'New input')
            self.app.start()
            self.assertEqual(str(self.app.output['state']), 'disabled')
            self.assertEqual(str(self.app.copy_button['state']), 'disabled')
            self.app.results.put(('text', 'Partial result'))
            self.poll()
            self.app.output.insert('end', 'Unwanted edit')
            self.assertEqual(self.app.output.get('1.0', 'end-1c'), 'Partial result')
            if cancelled:
                self.app.cancel()
            self.app.results.put(('done' if cancelled else 'error', 'Interrupted'))
            self.poll()
            self.assertEqual(str(self.app.output['state']), 'disabled')
            self.assertEqual(self.app.output.get('1.0', 'end-1c'), '')
            self.app.cancelled.clear()

    def test_clear_disabled_when_closing(self):
        self.app.input.insert('1.0', 'Keep while closing')
        self.app.close()
        self.app.clear_input()
        self.assertEqual(str(self.app.clear_button['state']), 'disabled')
        self.assertEqual(self.app.input.get('1.0', 'end-1c'), 'Keep while closing')


if __name__ == '__main__':
    unittest.main()