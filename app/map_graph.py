"""Read the MAPS signposts into V2's graph schema; never store dashboard truth."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import uuid

from check_map import SECTIONS, configured, entry, key, read_json, check, rebuild
from presentation import display_records,record_display_name,human_name

AREA_TITLES = {
    'active-playbooks':'Playbook files', 'append-only-store':'Recovery history',
    'application-source':'Workspace components', 'verification':'Validation checks',
    'team-workspaces':'Team workspaces', 'workspace':'Workspace entry points',
    'workspace-guides':'Workspace guides', 'technical-journals':'Technical journals',
    'owned-state':'Working state', 'routines':'Local routines', 'routine-history':'Routine outcomes',
    'project-locations':'Project folders', 'current-agent-records':'Team',
    'current-skill-records':'Playbooks', 'current-memory-records':'Knowledge',
    'current-loop-records':'Workflows', 'current-project-records':'Projects',
    'current-stack-records':'Workspace setup', 'record-history':'Previous versions',
    'record-projections':'Saved record index', 'original-skill-sources':'Original playbook sources',
    'skill-reference-guides':'Playbook reference guides', 'company-methodology':'Company methods',
    'original-technical-journals':'Original technical journals', 'thesis-and-research':'Thesis and research',
    'youtube-research-notes':'Video research notes', 'youtube-research-transcripts':'Video transcripts',
    'recovered-source-documents':'Original source documents', 'run-artifacts':'Prepared documents',
    'operational-state':'Local service state', 'history-collection':'Private conversation history',
    'owner-added':'Additional references',
}
AREA_PURPOSES = {
    'Team':'Roles and responsibilities, connected to their playbooks and references.',
    'Playbooks':'Reusable procedures connected to the roles and knowledge they support.',
    'Knowledge':'Saved references, decisions and research, with their sources and versions.',
    'Workflows':'Configured sequences of work, linked to the roles assigned to each step.',
    'Projects':'Registered work and scope, connected to existing project folders.',
    'Project folders':'Existing locations registered for work; registration does not read or execute their contents.',
    'Previous versions':'Earlier saved records kept for comparison and traceability.',
    'Workspace components':'The implementation files that support this local workspace.',
    'Validation checks':'Checks used to verify implementation behavior and recovery.',
    'Recovery history':'Private operational records used to recover saved work.',
    'Private conversation history':'Private historical context accessed through dedicated recall, separate from current instructions.',
    'Local routines':'Local scheduled checks and briefings, active while this computer and service are awake.',
    'Routine outcomes':'Recorded results of local routine runs.',
    'Prepared documents':'Documents written by recorded workflow runs.',
}
COMPONENTS = {
    'brain.py':('Company Brain records and workflows','Manages versioned records, source checks, conversations and workflow results.'),
    'server.py':('Local workspace service','Serves published views and records requests for the backend worker.'),
    'workspace.html':('Workspace interface','Provides the project, team, knowledge, workflow and review screens.'),
    'commands.py':('Work request queue','Retains requests and their outcomes so uncertain work is not silently repeated.'),
    'read_models.py':('Published workspace views','Creates the file views read by the dashboard and local memory connection.'),
    'file_ledger.py':('Recoverable record history','Preserves committed changes and rebuilds the local query projection.'),
    'codex_runtime.py':('Codex connection','Runs bounded specialist calls with explicit tool configuration and call receipts.'),
    'routing_context.py':('Specialist selection','Builds compact discovery cards before loading the selected procedure.'),
    'memory_mcp.py':('Local knowledge connection','Provides four read-only tools for current knowledge, projects and playbooks.'),
    'history_intake.py':('Conversation history intake','Preserves selected historical messages with source and coverage information.'),
    'history_recall.py':('Historical context lookup','Finds bounded historical excerpts while keeping their date, scope and provenance.'),
    'archive_research.py':('Research library capture','Saves explicitly selected research and links it to projects and playbooks.'),
    'improvements.py':('Playbook improvement proposals','Turns owner corrections into proposals for explicit review and versioned application.'),
    'routine_engine.py':('Local routine runner','Runs the registered local checks and briefings and records their outcomes.'),
    'check_map.py':('Source navigation check','Builds and validates direct links between the workspace and its source files.'),
    'map_graph.py':('Company Brain map','Turns real source locations and declared relationships into this map.'),
    'git_service.py':('Git checkpoint connection','Creates and synchronizes saved repository checkpoints.'),
    'bootstrap.py':('Workspace initialization','Loads the starting definitions when an empty local workspace is initialized.'),
    'migrate_library.py':('Source library migration','Imports selected company references and procedures with their provenance.'),
}
RELATION_LABELS = {
    'area':('Has work area','Work area of'), 'contains':('Contains','Listed in'),
    'snapshot-of':('Saved copy of','Has saved copy'), 'declared-reference':('References','Referenced by'),
    'reports-to':('Reports to','Manages'), 'uses-playbook':('Uses playbook','Available to'),
    'assigned-role':('Assigns work to','Assigned in'), 'workflow-playbook':('Includes playbook','Included in'),
    'project-root':('Stored in folder','Folder for'), 'execution':('Has result','Result of'),
    'source-document':('Based on source','Source for'), 'reference-guide':('Uses reference guide','Reference guide for'),
    'permitted-action':('Can perform','Available to'), 'workflow-action':('Runs action','Action used by'),
    'implemented-by':('Supported by component','Implements action'),
}
ACTION_PURPOSES = {
    'index':('Update knowledge index','Refreshes the local search index from currently accepted knowledge.'),
    'retrieve':('Find supporting evidence','Retrieves current accepted knowledge for the requested subject.'),
    'draft':('Prepare a document','Makes a bounded Codex call using the assigned role, playbook and saved evidence.'),
    'validate':('Check saved evidence','Checks that cited saved evidence is present and current; it does not independently verify every claim.'),
    'propose-memory':('Propose reusable knowledge','Saves a candidate knowledge record from workflow output for review.'),
}
DISPLAY_KINDS={'agent':'Team role','skill':'Playbook','memory':'Knowledge','loop':'Workflow','project':'Project','stack':'Workspace setup'}
RUN_STATES={'needs_review':'Ready for review','accepted':'Accepted','running':'In progress','queued':'Waiting to start','failed':'Needs attention','cancelled':'Stopped','interrupted':'Interrupted'}


def plain_name(value):
    return re.sub(r'\s+',' ',str(value).replace('_',' ').replace('-',' ')).strip()


def record_purpose(record):
    data=record.get('data',{});kind=record.get('kind')
    for field in ('purpose','description','scope'):
        value=data.get(field)
        if isinstance(value,str) and value.strip():return value.strip()[:300]
    if kind=='loop':return 'A configured workflow with '+str(len(data.get('steps',[])))+' steps. Open it to inspect assignments and expected results.'
    if kind=='memory':return 'Saved knowledge with source attribution. Open it to read the evidence, limitations and related records.'
    if kind=='agent':return 'A registered team role. Open it to inspect its scope, responsibilities and playbooks.'
    if kind=='skill':return 'A reusable procedure. Open it to read when and how it should be used.'
    if kind=='project':return 'Registered project scope and an existing work folder, linked to shared knowledge and playbooks.'
    return 'Saved workspace configuration. Open it to inspect the recorded choices.'


def file_presentation(root,path,label,info):
    """Describe known files using recorded metadata, without inventing deployment state."""
    path=Path(path);name=label;note='';display_kind='Reference document'
    if path.is_relative_to(root/'records') and path.suffix=='.json' and path.stem.startswith('v'):
        record=read_json(path,{})
        if isinstance(record,dict) and isinstance(record.get('data'),dict):
            name=record_display_name(record)+' · version '+str(record.get('version',int(path.stem[1:])))
            note=record_purpose(record);display_kind=DISPLAY_KINDS.get(record.get('kind'),'Saved record')
    elif path.parent==root/'app' and path.name in COMPONENTS:
        name,note=COMPONENTS[path.name];display_kind='Workspace component'
    elif path.is_relative_to(root/'evaluations'):
        name='Check: '+plain_name(path.stem.removeprefix('test_'))
        note='Automated checks for '+plain_name(path.stem.removeprefix('test_'))+'. A file in the map is not proof that its checks passed.';display_kind='Validation check'
    elif path.is_dir():
        name=label;note=('Private historical context accessed through dedicated recall; raw conversation files are not opened from this map.' if info.get('authority')=='private_archive_collection' else 'An existing project or reference location. Registration does not run work or read everything in the folder.');display_kind='Folder'
    elif path.suffix.lower()=='.md':
        try:
            # Titles improve file names; source text remains data, not instructions.
            with path.open(encoding='utf-8-sig') as stream:head=stream.read(4096)
            heading=re.search(r'^#\s+(.+)$',head,re.M)
            if heading:name=heading.group(1).strip()[:150]
        except (OSError,UnicodeError):pass
    if not note:
        authority=info.get('authority','')
        note={'original_source':'An original source referenced by this workspace. Follow its links to see where it is used.',
              'source_snapshot':'A saved source copy retained for attribution and comparison.',
              'run_artifact':'A document prepared by a recorded workflow run.',
              'append_only_store':'Private operational history retained for recovery and audit.',
              'routine_definition':'Defines the local routine schedule, limits and output location.',
              'generated_projection':'A generated view of owned records; the original records remain authoritative.'}.get(authority,'A workspace reference. Its connections show the records and work areas that reference it.')
    return {'label':human_name(name),'note':note,'display_kind':display_kind}


def declared_sources(data):
    """Yield explicit source paths only, never infer a dependency from free text."""
    if isinstance(data.get('source_path'),str):yield data['source_path'],'source-document'
    for field in ('source_refs','journal_refs','paper_refs'):
        for value in data.get(field,[]):
            if isinstance(value,str):yield value,'source-document'
            elif isinstance(value,dict) and isinstance(value.get('path'),str):yield value['path'],'source-document'
    for value in data.get('source_links',[]):
        if isinstance(value,dict) and isinstance(value.get('path'),str):yield value['path'],'source-document'
    validation=data.get('validation',{})
    if not isinstance(validation,dict):validation={}
    for value in validation.get('relative_links',[]):
        if isinstance(value,dict) and isinstance(value.get('path'),str):yield value['path'],'reference-guide'
    capture=data.get('capture',{})
    if not isinstance(capture,dict):capture={}
    provenance=capture.get('provenance',{})
    if not isinstance(provenance,dict):provenance={}
    if isinstance(provenance.get('source_file'),str):yield provenance['source_file'],'source-document'


def identity(path):
    return "file:" + hashlib.sha256(key(path).encode("utf-8")).hexdigest()[:20]


def _walk(root):
    root = Path(root).resolve()
    config = configured(root)
    if not config:
        raise ValueError("The memory map has not been built. Run app/check_map.py --rebuild.")
    master = root / "memory-map" / config["master"]
    areas = []
    for line in master.read_text(encoding="utf-8").splitlines():
        parsed = entry(line)
        if not parsed:
            continue
        label, target, _ = parsed
        path = Path(target).resolve()
        values, section = [], None
        for area_line in path.read_text(encoding="utf-8").splitlines():
            if area_line.startswith("## ") and area_line[3:] in SECTIONS:
                section = area_line[3:]
            value = entry(area_line)
            if value:
                name, source, note = value
                values.append({"label": name, "path": str(Path(source).resolve()), "note": note, "section": section})
        areas.append({"label": label, "path": path, "entries": values})
    return master, areas


def approved_source_paths(root) -> list[str]:
    """Exact existing files only; project folders confer no recursive read access."""
    master, areas = _walk(root)
    paths = {key(master): master}
    for area in areas:
        paths[key(area["path"])] = area["path"]
        for value in area["entries"]:
            path = Path(value["path"])
            if path.is_file():
                paths[key(path)] = path
    return sorted(path.as_posix() for path in paths.values())


def source_roots(root) -> list[str]:
    """Parent-directory hints. Authorization must still require exact file membership."""
    parents = {Path(path).parent.resolve() for path in approved_source_paths(root)}
    return sorted(p.as_posix() for p in parents if p != Path(p.anchor))


def _stamp(path):
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        return {"ts": modified.isoformat(), "day": modified.date().isoformat(),
                "changed": (datetime.now(timezone.utc) - modified).total_seconds() < 86400}
    except OSError:
        return {"ts": None, "day": None, "changed": False}


def _kind(path, section, metadata):
    authority = metadata.get("authority", "")
    if path.is_dir() or section == "Projects":
        return "project", "core"
    if authority == "run_artifact":
        return "note", "runs"
    if section == "Skills":
        return "skill", "skills"
    if section == "Routines":
        return "routine", "routines"
    if path.suffix.lower() in {".py", ".html", ".js", ".ps1"}:
        return "app", "apps"
    if section == "Memory" or authority in {"original_source", "source_snapshot", "append_only_store"}:
        return "memory", "memory"
    return "note", "core"


def build_graph(root, brain=None):
    """Build actual file nodes, source links and optional live record/run relationships."""
    root = Path(root).resolve()
    master, areas = _walk(root)
    manifest = read_json(root / "memory-map/catalog.json", {"documents": []})
    metadata = {key(x["path"]): x for x in manifest.get("documents", [])}
    nodes = {"root": {"id": "root", "label": "Company Brain", "kind": "root", "layer": "core", "display_kind":"Shared workspace",
                      "area": "system", "path": master.as_posix(), "note": "Your projects, people, playbooks and knowledge, connected to their real source files.", **_stamp(master)}}
    links, files, linked = [], {}, set()

    def connect(source, target, relationship="contains", kind="tree"):
        signature=(source,target,relationship)
        if source==target or signature in linked:return
        linked.add(signature)
        label,inverse=RELATION_LABELS[relationship]
        links.append({"s": source, "t": target, "k": kind, "relationship": relationship,'label':label,'inverse_label':inverse})

    for area in areas:
        tag = area["path"].stem
        area_id = "area:map:" + tag
        base=re.sub(r'-\d+$','',tag);title=AREA_TITLES.get(base,area['label']);page=re.search(r'-(\d+)$',tag)
        nodes[area_id] = {"id": area_id, "label": title+(' ('+str(int(page.group(1)))+')' if page else ''), "kind": "area", "layer": "core", "area": tag,'display_kind':'Work area',
                          "path": area["path"].as_posix(), "note": AREA_PURPOSES.get(title,'Direct links to '+title.lower()+', with their sources and related work.'), **_stamp(area["path"])}
        connect("root", area_id, "area")
        for value in area["entries"]:
            path = Path(value["path"])
            ident = identity(path)
            files[key(path)] = ident
            info = metadata.get(key(path), {})
            kind, layer = _kind(path, value["section"], info)
            nodes.setdefault(ident, {"id": ident, "label": value["label"], "kind": kind, "layer": layer,
                                    "area": tag, "path": path.as_posix(), "note": value["note"],
                                    "exists": path.exists(), "authority": info.get("authority", "owner_declared_source"),
                                    **_stamp(path)})
            nodes[ident].update(file_presentation(root,path,value['label'],info))
            if value['note']:nodes[ident]['note']=value['note']
            connect(area_id, ident)
    for target, info in metadata.items():
        canonical = info.get("canonical_path")
        if canonical and target in files and key(canonical) in files:
            connect(files[target], files[key(canonical)], "snapshot-of", "depends-on")

    records = display_records(brain.list()) if brain is not None else []
    used_actions=set()
    for record in records:
        if record['kind']=='agent':used_actions.update(record['data'].get('tools',[]))
        if record['kind']=='loop':used_actions.update(step.get('tool') for step in record['data'].get('steps',[]))
    if used_actions:
        action_area='area:available-actions'
        nodes[action_area]={'id':action_area,'label':'Available actions','kind':'area','layer':'apps','area':'actions','path':'','display_kind':'Work area','note':'Actions registered for team roles and workflows. Availability is not a claim that an action has run.'}
        connect('root',action_area,'area')
        for action in sorted(used_actions.intersection(ACTION_PURPOSES)):
            title,purpose=ACTION_PURPOSES[action];ident='action:'+action
            nodes[ident]={'id':ident,'label':title,'kind':'app','layer':'apps','area':'actions','path':'','display_kind':'Available action','note':purpose}
            connect(action_area,ident)
            if key(root/'app/brain.py') in files:connect(ident,files[key(root/'app/brain.py')],'implemented-by','depends-on')
    record_nodes = {}
    for record in records:
        path = root / "records" / record["kind"] / record["id"] / f"v{record['version']:04d}.json"
        ident = files.get(key(path))
        if ident:
            logical_id = record["kind"] + ":" + record["id"]
            record_nodes[logical_id] = ident
            node = nodes[ident]
            node.update(record_id=logical_id, version=record["version"], label=record['display_name'],original_name=record['data'].get('name',''),
                        note=record_purpose(record),display_kind=DISPLAY_KINDS.get(record['kind'],'Saved record'))
            if record["kind"] == "agent":
                node.update(kind="app", layer="apps")
            elif record["kind"] == "project":
                node.update(kind="project", layer="apps")
    for record in records:
        logical_id = record["kind"] + ":" + record["id"]
        source = record_nodes.get(logical_id)
        if not source:
            continue
        data = record["data"]
        refs = list(data.get("refs", []))
        if record["kind"] == "agent":
            for action in data.get('tools',[]):
                if 'action:'+action in nodes:connect(source,'action:'+action,'permitted-action','depends-on')
            for value in data.get('skills',[]):
                if 'skill:'+value in record_nodes:connect(source,record_nodes['skill:'+value],'uses-playbook','depends-on')
            if data.get('parent') and 'agent:'+data['parent'] in record_nodes:
                connect(source,record_nodes['agent:'+data['parent']],'reports-to','depends-on')
        if record["kind"] == "loop":
            for step in data.get("steps", []):
                if 'action:'+step.get('tool','') in nodes:connect(source,'action:'+step['tool'],'workflow-action','depends-on')
                if 'agent:'+step['agent'] in record_nodes:connect(source,record_nodes['agent:'+step['agent']],'assigned-role','depends-on')
                if step.get('skill') and 'skill:'+step['skill'] in record_nodes:connect(source,record_nodes['skill:'+step['skill']],'workflow-playbook','depends-on')
        for ref in set(refs):
            if ref in record_nodes:
                connect(source, record_nodes[ref], "declared-reference", "depends-on")
        for path,relationship in declared_sources(data):
            if Path(path).is_absolute() and key(path) in files:connect(source,files[key(path)],relationship,'depends-on')
        for value in data.get('source_links',[]):
            if isinstance(value,dict):
                match=re.fullmatch(r'/?#(agent|skill|memory|loop|stack|project)/([A-Za-z0-9_-]+)',value.get('url',''))
                if match and ':'.join(match.groups()) in record_nodes:connect(source,record_nodes[':'.join(match.groups())],'source-document','depends-on')
        if record["kind"] == "project" and data.get("path") and key(data["path"]) in files:
            connect(source, files[key(data["path"])], "project-root", "depends-on")
    runs = []
    if brain is not None:
        with brain.connect() as connection:
            runs = [dict(row) for row in connection.execute("SELECT id,loop_id,state,created FROM runs ORDER BY created DESC LIMIT 50")]
    if runs:
        area_id = "area:runtime-runs"
        nodes[area_id] = {"id": area_id, "label": "Results", "kind": "area", "layer": "runs", "area": "runs", "path": "", 'display_kind':'Work area', "note": "Recorded workflow outcomes and documents ready for review."}
        connect("root", area_id, "area")
        for run in runs:
            ident = "run:" + run["id"]
            workflow=next((r for r in records if r['kind']=='loop' and r['id']==run['loop_id']),None)
            title=workflow['data']['name'] if workflow else plain_name(run['loop_id'])
            state_label=RUN_STATES.get(run['state'],plain_name(run['state']))
            nodes[ident] = {"id": ident, "label": title + " · " + state_label, "kind": "run", "layer": "runs", "area": "runs",'display_kind':'Workflow result',
                            "path": "run/" + run["id"], "note": "Recorded outcome: "+state_label+". Open the result to inspect its documents and source checks.", "ts": run["created"], "day": run["created"][:10], "changed": False}
            connect(area_id, ident)
            loop = record_nodes.get("loop:" + run["loop_id"])
            if loop:
                connect(loop, ident, "execution", "run")
    unique_links = {(x["s"], x["t"], x["relationship"]): x for x in links if x["s"] in nodes and x["t"] in nodes}
    links = list(unique_links.values())
    degree = Counter(endpoint for link in links for endpoint in (link["s"], link["t"]))
    for node in nodes.values():
        node["deg"] = degree[node["id"]]
    values = list(nodes.values())
    primary={'root'} | {'action:'+a for a in used_actions if a in ACTION_PURPOSES}
    for record in records:
        logical_id=record['kind']+':'+record['id']
        if not record.get('archived') and logical_id in record_nodes:
            primary.add(record_nodes[logical_id])
            if record['kind']=='project' and record['data'].get('path'):
                folder=files.get(key(record['data']['path']))
                if folder:primary.add(folder)
    primary.update('run:'+run['id'] for run in runs[:10])
    for edge in links:
        if edge['t'] in primary and nodes[edge['s']]['kind']=='area':primary.add(edge['s'])
    for node in values:node['audit_only']=node['id'] not in primary
    counts = dict(Counter(node["kind"] for node in values))
    counts.update(nodes=len(values), links=len(links), run=len(runs))
    return {"generated": datetime.now(timezone.utc).isoformat(), "areas": sorted({node["area"] for node in values}),
            "counts": counts, "layers": dict(Counter(node["layer"] for node in values)), "nodes": values, "links": links,
            "source": "memory-map/MASTER.md and direct signpost targets", "source_roots": source_roots(root),
            "unmapped_current_records": sorted(r["kind"] + ":" + r["id"] for r in records if r["kind"] + ":" + r["id"] not in record_nodes)}


def publish_map(root):
    """Nightly backend operation: reject stale links, refresh the map, publish file graph.

    No Brain instance is created and no runtime database is opened. A UI publisher
    may overlay actual runtime relationships with build_graph(root, existing_brain).
    """
    root = Path(root).resolve()
    result = check(root)
    if not result["ok"]:
        raise ValueError("Memory map needs repair before regeneration: " + "; ".join(result["errors"]))
    rebuild(root)
    result = check(root)
    if not result["ok"]:
        raise ValueError("Rebuilt memory map failed validation: " + "; ".join(result["errors"]))
    graph = build_graph(root)
    destination = root / "data/map.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(graph, ensure_ascii=False, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, destination)
    return destination


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--publish", action="store_true", help="Check, rebuild and atomically publish data/map.json")
    args = parser.parse_args()
    if args.publish:
        print(publish_map(args.root))
    else:
        print(json.dumps(build_graph(args.root), ensure_ascii=False))
