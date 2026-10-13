import importlib.util,sys,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
original=importlib.util.spec_from_file_location
missing=root/'vendor/AI-OS-Dashboard-Current-1.0.4/server.py'
existing=root.parent/'V2/vendor/AI-OS-Dashboard-Current-1.0.4/server.py'
def specification(name,location,*args,**kwargs):
    if Path(location).resolve()==missing.resolve():
        location=existing
    return original(name,location,*args,**kwargs)
importlib.util.spec_from_file_location=specification
suite=unittest.defaultTestLoader.discover(str(root/'evaluations'))
importlib.util.spec_from_file_location=original
result=unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
