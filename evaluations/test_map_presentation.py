"""Human map labels retain actual source paths and declared relationships."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from brain import Brain
from check_map import rebuild
from map_graph import build_graph,file_presentation,identity,declared_sources


class MapPresentationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'runtime')
        self.root=Path(self.temp.name).resolve()
        self.brain=Brain(self.root)
        (self.root/'app').mkdir()
        (self.root/'app/brain.py').write_text('# implementation fixture',encoding='utf-8')
        (self.root/'docs').mkdir()
        self.source=self.root/'docs/source.md'
        self.source.write_text('# Original writing method\n\nReference text.\n',encoding='utf-8')
        self.brain.save('memory','policy',{'name':'Evidence policy','content':'Cite sources.','source':'Owner decision','status':'accepted'})
        self.brain.save('skill','writer',{'name':'Evidence writing','instructions':'PRIVATE_INSTRUCTION_SENTINEL','purpose':'Prepare source-backed drafts.','source_path':str(self.source),'source_links':[{'url':'/#memory/policy'}],'refs':['memory:policy']})
        self.brain.save('agent','director',{'name':'Editorial director','purpose':'Own editorial direction.','instructions':'Direct','skills':[],'tools':[]})
        self.brain.save('agent','writer',{'name':'Research writer','purpose':'Prepare clear documents.','parent':'director','instructions':'PRIVATE_INSTRUCTION_SENTINEL','skills':['writer'],'tools':['draft']})
        self.brain.save('loop','report',{'name':'Prepare report','steps':[{'agent':'writer','skill':'writer','tool':'draft','instruction':'Write a report.'}]})
        self.brain.save('project','work',{'name':'Research project','path':str(self.root),'scope':'Research work','refs':['memory:policy','skill:writer']})
        rebuild(self.root)

    def tearDown(self):self.temp.cleanup()

    def test_every_node_has_human_purpose_and_edges_have_both_directions(self):
        graph=build_graph(self.root,self.brain)
        self.assertTrue(all(n.get('label') and n.get('note') and n.get('display_kind') for n in graph['nodes']))
        nodes={n['id']:n for n in graph['nodes']}
        self.assertEqual(nodes['root']['area'],'system')
        self.assertTrue(all(e['s'] in nodes and e['t'] in nodes and e['label'] and e['inverse_label'] for e in graph['links']))
        self.assertNotIn('PRIVATE_INSTRUCTION_SENTINEL',json.dumps(graph))
        self.assertFalse(nodes['root']['audit_only'])
        self.assertTrue(nodes[identity(self.root/'app/brain.py')]['audit_only'])
        self.assertFalse(nodes['action:draft']['audit_only'])

    def test_relationships_are_declared_not_inferred(self):
        graph=build_graph(self.root,self.brain)
        current={n['record_id']:n['id'] for n in graph['nodes'] if n.get('record_id')}
        links={(e['s'],e['t'],e['relationship']) for e in graph['links']}
        self.assertIn((current['agent:writer'],current['agent:director'],'reports-to'),links)
        self.assertIn((current['agent:writer'],current['skill:writer'],'uses-playbook'),links)
        self.assertIn((current['skill:writer'],current['memory:policy'],'source-document'),links)
        self.assertIn((current['skill:writer'],identity(self.source),'source-document'),links)
        self.assertIn((current['loop:report'],'action:draft','workflow-action'),links)
        self.assertIn((current['agent:writer'],'action:draft','permitted-action'),links)
        self.assertIn(('action:draft',identity(self.root/'app/brain.py'),'implemented-by'),links)
        self.assertNotIn('action:email',{n['id'] for n in graph['nodes']})
        self.assertEqual(len(links),len(graph['links']))

    def test_current_and_historical_record_names_preserve_versions(self):
        record=self.brain.get('skill','writer')
        self.brain.save('skill','writer',record['data']|{'name':'Reviewed evidence writing'},1)
        rebuild(self.root)
        graph=build_graph(self.root,self.brain)
        bypath={n.get('path'):n for n in graph['nodes']}
        old=bypath[(self.root/'records/skill/writer/v0001.json').as_posix()]
        new=bypath[(self.root/'records/skill/writer/v0002.json').as_posix()]
        self.assertEqual(old['label'],'Evidence writing · version 1')
        self.assertNotIn('record_id',old)
        self.assertTrue(old['audit_only'])
        self.assertEqual(new['label'],'Reviewed evidence writing')
        self.assertEqual(new['version'],2)
        self.assertFalse(new['audit_only'])

    def test_component_and_reference_labels_come_from_known_sources(self):
        component=file_presentation(self.root,self.root/'app/brain.py','brain',{})
        self.assertEqual(component['label'],'Company Brain records and workflows')
        source=file_presentation(self.root,self.source,'source',{})
        self.assertEqual(source['label'],'Original writing method')
        folder=file_presentation(self.root,self.root,'Work folder',{})
        self.assertEqual(folder['display_kind'],'Folder')
        self.assertEqual(list(declared_sources({'validation':'Human-reviewed note','capture':'Historical label'})),[])


class MapFrontendTests(unittest.TestCase):
    def test_script_syntax_directional_cards_and_safe_text(self):
        node=shutil.which('node') or 'C:/Program Files/nodejs/node.exe'
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[1],'utf8'),script=html.split('<script>')[1].split('</script>')[0];
new Function(script);
const lines=script.split('\n'),names=['mapConnections','mapConnectionHtml','mapCardHtml'];
names.push('workingProfile','workingProfileFields','mapAreaLabel','mapCanvasLabel');
const functions=lines.filter(line=>names.some(name=>line.startsWith('function '+name+'('))).join('\n');
const esc=lines.find(line=>line.startsWith('const esc='));
const context={localStorage:{getItem:()=>null},window:{},graphView:null};vm.createContext(context);vm.runInContext(esc+'\n'+lines.find(line=>line.startsWith('const workingProfiles='))+'\n'+functions+'\n'+lines.find(line=>line.startsWith('window.prepareCompanyBrainGraph=')),context);
const a={id:'a',label:'Writer',kind:'app',note:'Prepare documents',area:'team'},b={id:'b',label:'<img src=x onerror=evil()>',kind:'memory',area:'knowledge',path:'C:/private',source_available:false};
const graph={nodes:[a,b],links:[{s:'a',t:'b',label:'Uses evidence',inverse_label:'Supports'}]};
assert.equal(context.mapConnections(a,graph)[0].label,'Uses evidence');
assert.equal(context.mapConnections(b,graph)[0].label,'Supports');
const out=context.mapCardHtml(b,context.mapConnections(b,graph));
assert(out.includes('&lt;img'));assert(!out.includes('<img'));
assert(!out.includes('/api/file?'));
const source=context.mapCardHtml({...b,path:'C:/safe/source.md',source_available:true},[]);
assert(source.includes('/api/file?path=C%3A%2Fsafe%2Fsource.md'));
assert(source.includes('Source and technical details'));
const filtered=context.window.prepareCompanyBrainGraph({nodes:[{...a,audit_only:false,layer:'apps'},{...b,audit_only:true,layer:'memory'}],links:graph.links});
assert.equal(filtered.nodes.length,1);assert.equal(filtered.links.length,0);assert.equal(filtered.counts.nodes,1);
assert(!context.mapConnectionHtml({label:'Uses',node:{...b,audit_only:true}}).includes('data-map-target'));
assert.equal(context.workingProfileFields('innovation').reasoning_effort,'ultra');
assert.equal(context.workingProfileFields('routine').model,'gpt-6.1-sol');
assert.equal(context.workingProfileFields('thinking').service_tier,'default');
assert.equal(context.workingProfileFields('light').model,'gpt-6-luna');
assert.throws(()=>context.workingProfileFields('priority'));
assert.equal(context.mapAreaLabel('current-agent-records'),'Team');
assert.equal(context.mapAreaLabel('current-memory-records-04'),'Knowledge 4');
assert.equal(context.mapAreaLabel('current-skill-records'),'Playbooks');
assert.equal(context.mapCanvasLabel('CURRENT-MEMORY-RECORDS-01'),'Knowledge 1');
assert.equal(context.mapCanvasLabel('My original source title'),'My original source title');
assert.equal(context.mapAreaLabel('actions'),'Capabilities');
assert(html.includes('wrap.prepend(controls)'));
console.log('Syntax, inverse relations, escaped content and unavailable-source behavior passed.');
'''
        result=subprocess.run([node,'-e',script,str(ROOT/'app/workspace.html')],capture_output=True,text=True,encoding='utf-8',timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
