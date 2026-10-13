"""The chat UI points to a saved answer's existing library identity."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]


class ChatPresentationTests(unittest.TestCase):
    def test_retained_answers_and_replays_use_existing_library_record(self):
        node=shutil.which('node') or 'C:/Program Files/nodejs/node.exe'
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[1],'utf8'),script=html.split('<script>')[1].split('</script>')[0];
new Function(script);
const names=['chatLibraryState','chatLibraryHtml','knowledgeSourceCategory','knowledgeSourceHtml','webLink'];
const code=script.split('\n').filter(line=>names.some(n=>line.startsWith('function '+n+'('))).join('\n');
const context={URL,esc:String,recordLink:(kind,id,label,version)=>`<a href="#${kind}/${id}?version=${version}">${label}</a>`};
vm.createContext(context);vm.runInContext(code,context);
const turn={id:'original',state:'completed',discovery:[],attempts:[{stage:'answer',state:'completed'}]};
const saved={kind:'memory',id:'answer-original',version:2,archived:false,data:{type:'l2-answer-cache',capture:{turn_id:'original'}}};
let state=context.chatLibraryState(turn,[saved]);
assert.equal(state.record.id,'answer-original');assert.equal(state.canCapture,true);
let out=context.chatLibraryHtml(turn,state);
assert(out.includes('#memory/answer-original?version=2'));
assert(out.includes('Update library connections'));assert(!out.includes('Save answer to library'));
for(const mode of ['l1_reuse','l1_lookup']){
 const replay={id:'replay',state:'completed',attempts:[{stage:'l1-reuse',state:'completed'}],discovery:[{mode,reused_from:{id:'answer-original',version:1}}]};
 state=context.chatLibraryState(replay,[saved]);out=context.chatLibraryHtml(replay,state);
 assert.equal(state.canCapture,false);assert(out.includes('#memory/answer-original?version=1'));
 assert(!out.includes('archiveAnswer'));assert(!out.includes('Save answer'));
}
state=context.chatLibraryState(turn,[]);assert.equal(state.canCapture,true);
assert(context.chatLibraryHtml(turn,state).includes('Save answer to library'));
state=context.chatLibraryState(turn,[{...saved,archived:true}]);assert.equal(state.canCapture,false);
assert(context.chatLibraryHtml(turn,state).includes('Archived library answer'));
state=context.chatLibraryState(turn,[{...saved,data:{type:'l2-answer-cache',capture:{turn_id:'different'}}}]);assert.equal(state.record,undefined);
const source={id:'source',data:{source:'E:/Old/docs/directors/ART_DIRECTOR.md; SHA256 abc; segment 1/1',source_path:'E:/Old/docs/directors/ART_DIRECTOR.md'}};
assert.equal(context.knowledgeSourceHtml(source),'Role reference');
const video={id:'video',data:{type:'research-capture',source:'Capture provenance',capture:{provenance:{source_urls:['https://www.youtube.com/watch?v=example']}}}};
const preview=context.knowledgeSourceHtml(video);assert(preview.includes('Captured research'));assert(preview.includes('href="https://www.youtube.com/watch?v=example"'));assert(preview.includes('Open source'));
console.log('Existing identity, original version, replay read-only action and archive state passed.');
'''
        result=subprocess.run([node,'-e',script,str(ROOT/'app/workspace.html')],capture_output=True,text=True,encoding='utf-8',timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
