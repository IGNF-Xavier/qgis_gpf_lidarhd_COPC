import pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class StreamDrainTests(unittest.TestCase):
 def test_stdout_is_drained_while_process_runs(self):
  s=(ROOT/'process_utils.py').read_text(encoding='utf-8')
  self.assertIn('threading.Thread',s);self.assertIn('_drain(line_queue,lines,feedback)',s)
  self.assertIn('stderr=subprocess.STDOUT',s);self.assertIn('env=env',s)
