import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from live_output import read_output
from os_gateway import decorate

class LiveOutputTests(unittest.TestCase):
    def test_only_reported_bounded_os_document_can_be_previewed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'docs').mkdir();doc=root/'docs/guide.md';doc.write_text('Checked guide',encoding='utf8')
            state={'tasks':[{'id':'native:test','outputs':[{'reference':str(doc)}]}]}
            with patch('live_output.activity_view',return_value=state):
                self.assertEqual(read_output(root,'native:test',0),b'Checked guide')
                with self.assertRaises(ValueError):read_output(root,'unknown',0)
                with self.assertRaises(ValueError):read_output(root,'native:test',1)
                secret=root/'private.txt';secret.write_text('private',encoding='utf8');state['tasks'][0]['outputs'][0]['reference']=str(secret)
                with self.assertRaises(ValueError):read_output(root,'native:test',0)
                state['tasks'][0]['outputs'][0]['reference']=str(doc);doc.write_bytes(b'x'*(256*1024+1))
                with self.assertRaises(ValueError):read_output(root,'native:test',0)
    def test_real_renderer_hook_and_no_ambient_motion(self):
        original='<meta charset="utf-8">const N=BR.nodes, L=BR.links, byId=0;const AMB_N=8;let motion=!reduce;function draw(ts){try{drawBody(ts)}'
        served=decorate(original)
        self.assertIn('/map-live.js',served)
        self.assertIn('CompanyBrainLiveMap?.draw(ctx,N,L,view)',served)
        self.assertIn('CompanyBrainLiveMapRedraw',served)
        self.assertIn('const AMB_N=0;',served)
        self.assertIn('let motion=false;',served)
        self.assertIn('const AMB_N=8;',original)

if __name__=='__main__':unittest.main()
