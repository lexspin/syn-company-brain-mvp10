"""Portable, synthetic record-versioning example. No network or model calls."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from brain import Brain

with TemporaryDirectory(prefix='syn-public-example-') as folder:
    brain=Brain(folder)
    brain.save('project','example',{'name':'Community energy guide','path':folder,'scope':'Synthetic example','refs':[]})
    first=brain.save('memory','units',{'name':'Units lesson','status':'candidate','source':'Synthetic public example','content':'Compare energy in kWh; keep power in kW.','refs':['project:example']})
    record=brain.get('memory','units')
    assert record['data']['content'].startswith('Compare energy')
    print('Synthetic project and versioned memory created and retrieved successfully.')
    print('Memory:',record['data']['name'],'version',record['version'])
