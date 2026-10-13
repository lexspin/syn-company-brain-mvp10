import hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from connection_view import checked_operations

class ConnectionEvidenceTests(unittest.TestCase):
    def test_only_matching_hash_bound_operation_can_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); file=root/'evidence.json'
            file.write_text(json.dumps([{'id':'hf','operation':'read','status':'verified-operation','result':'Actual source returned','observed_at':'2026-10-11'}]))
            check={'tool':'read','status':'returned'}
            probe={'tool_checks':[check,{'tool':'invented','status':'returned'}],
                'operation_evidence':{'path':'evidence.json','sha256':hashlib.sha256(file.read_bytes()).hexdigest()}}
            actual=checked_operations(root,'hf',probe)
            self.assertEqual(len(actual),1)
            self.assertEqual(actual[0]['tool'],'read')
            self.assertEqual(actual[0]['result'],'Actual source returned ')
            check['result']='All paid generation and writes verified'
            self.assertNotIn('paid',checked_operations(root,'hf',probe)[0]['result'])
            self.assertEqual(checked_operations(root,'other',probe),[])
            file.write_text('[]')
            self.assertEqual(checked_operations(root,'hf',probe),[])

    def test_labels_missing_evidence_and_external_paths_do_not_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.assertEqual(checked_operations(root,'hf',{'tool_checks':[{'status':'returned'}]}),[])
            self.assertEqual(checked_operations(root,'hf',{'operation_evidence':{'path':'../outside','sha256':'x'}}),[])
            self.assertEqual(checked_operations(root,'hf',None),[])

if __name__=='__main__':unittest.main()
