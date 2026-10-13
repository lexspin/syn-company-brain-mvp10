"""Append-only transaction files; SQLite is a recoverable query projection.

An entry is durable before its SQL projection commits. Never truncate a torn tail:
record its digest in a chained recovery entry before accepting further writes.
"""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time

META='_file_ledger_state'
_locks={}
_locks_guard=threading.Lock()

def encoded(value):
    if isinstance(value,(bytes,bytearray,memoryview)):return {'$bytes':base64.b64encode(value).decode('ascii')}
    return value

def decoded(value):
    if isinstance(value,dict) and set(value)=={'$bytes'}:return base64.b64decode(value['$bytes'])
    return value

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
def quote(name):return '"'+name.replace('"','""')+'"'

class Store:
    def __init__(self,root,db):
        self.folder=Path(root)/'store';self.folder.mkdir(parents=True,exist_ok=True)
        self.path=self.folder/'ledger.jsonl';self.db=Path(db)
        with _locks_guard:self._lock,self._local=_locks.setdefault(str(self.folder.resolve()),(threading.RLock(),threading.local()))
        self.signature=None;self.entries=[];self.tail=b'';self.needs_separator=False

    @contextmanager
    def locked(self):
        with self._lock:
            depth=getattr(self._local,'depth',0);handle=None
            if not depth:
                handle=(self.folder/'writer.lock').open('a+b')
                if handle.tell()==0:handle.write(b'0');handle.flush()
                handle.seek(0)
                if os.name=='nt':
                    import msvcrt
                    deadline=time.monotonic()+30
                    while True:
                        try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1);break
                        except OSError:
                            if time.monotonic()>deadline:handle.close();raise RuntimeError('The file store is busy with another writer.')
                            time.sleep(.05)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
            self._local.depth=depth+1
            try:yield
            finally:
                self._local.depth=depth
                if handle:
                    if os.name=='nt':
                        import msvcrt
                        handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
                    handle.close()

    def read(self):
        stat=self.path.stat() if self.path.exists() else None
        signature=(stat.st_size,stat.st_mtime_ns) if stat else None
        if signature==self.signature and self.entries:return
        raw=self.path.read_bytes() if stat else b'';entries=[];tail=b'';previous='0'*64
        lines=raw.splitlines(keepends=True)
        for index,line in enumerate(lines):
            payload=line.rstrip(b'\r\n')
            if not payload:continue
            try:entry=json.loads(payload)
            except (ValueError,UnicodeDecodeError):
                if tail:raise ValueError('Multiple damaged ledger lines; preserve the store and inspect it.')
                tail=payload
                if index==len(lines)-1:break
                continue
            if not isinstance(entry,dict):raise ValueError('Invalid ledger entry.')
            unsigned={k:v for k,v in entry.items() if k!='hash'}
            expected=hashlib.sha256(canonical(unsigned)).hexdigest()
            if entry.get('seq')!=len(entries)+1 or entry.get('previous')!=previous or entry.get('hash')!=expected:raise ValueError('Ledger sequence or hash mismatch; no projection writes were made.')
            if tail:
                if entry.get('kind')!='tail-recovery' or entry.get('tail_sha256')!=hashlib.sha256(tail).hexdigest():raise ValueError('Damaged ledger line has no matching recovery record.')
                tail=b''
            elif entry.get('kind')=='tail-recovery':raise ValueError('Unexpected ledger recovery record.')
            if not isinstance(entry.get('operations'),list):raise ValueError('Invalid ledger operations.')
            entries.append(entry);previous=entry['hash']
        self.entries=entries;self.tail=tail;self.signature=signature;self.needs_separator=bool(raw and not raw.endswith(b'\n'))

    def append(self,operations,kind='transaction',**extra):
        entry={'seq':len(self.entries)+1,'previous':self.entries[-1]['hash'] if self.entries else '0'*64,
               'kind':kind,'time_ns':time.time_ns(),'operations':operations,**extra}
        entry['hash']=hashlib.sha256(canonical(entry)).hexdigest()
        # One append, followed by fsync, is the commit point of the source of truth.
        with self.path.open('ab') as handle:
            if self.path.stat().st_size and (self.tail or self.needs_separator):handle.write(b'\n')
            handle.write(canonical(entry)+b'\n');handle.flush();os.fsync(handle.fileno())
        self.entries.append(entry);self.tail=b'';self.needs_separator=False
        stat=self.path.stat();self.signature=(stat.st_size,stat.st_mtime_ns)
        return entry

    def baseline(self,c):
        operations=[]
        schema=c.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' AND name<>? ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END,name",(META,)).fetchall()
        for kind,name,sql in schema:
            if kind=='table':
                operations.append({'sql':sql,'parameters':[]})
                columns=[r[1] for r in c.execute('PRAGMA table_info('+quote(name)+')')]
                insert='INSERT INTO '+quote(name)+' ('+','.join(map(quote,columns))+') VALUES ('+','.join('?' for _ in columns)+')'
                for row in c.execute('SELECT '+','.join(map(quote,columns))+' FROM '+quote(name)):
                    operations.append({'sql':insert,'parameters':[encoded(v) for v in row]})
            else:operations.append({'sql':sql,'parameters':[]})
        return operations

    def meta(self,c):
        c.execute('CREATE TABLE IF NOT EXISTS '+META+' (id INTEGER PRIMARY KEY CHECK(id=1),seq INTEGER,hash TEXT)')

    def apply(self,c,entry):
        c.execute('BEGIN IMMEDIATE')
        try:
            for op in entry['operations']:
                params=op.get('parameters',[])
                params={k:decoded(v) for k,v in params.items()} if isinstance(params,dict) else [decoded(v) for v in params]
                c.execute(op['sql'],params)
            c.execute('INSERT OR REPLACE INTO '+META+' VALUES(1,?,?)',(entry['seq'],entry['hash']))
            c.commit()
        except BaseException:c.rollback();raise

    def recover(self):
        """Caller holds locked(); ordinary external SQLite writes are unsupported."""
        self.read()
        c=sqlite3.connect(self.db,timeout=20)
        try:
            self.meta(c);c.commit()
            mark=c.execute('SELECT seq,hash FROM '+META+' WHERE id=1').fetchone()
            if not any(entry['kind']=='baseline' for entry in self.entries):
                if mark:raise ValueError('Authoritative file ledger is missing; preserve the projection and restore the store.')
                if self.tail:self.append([],'tail-recovery',tail_sha256=hashlib.sha256(self.tail).hexdigest())
                entry=self.append(self.baseline(c),'baseline')
                c.execute('INSERT INTO '+META+' VALUES(1,?,?)',(entry['seq'],entry['hash']));c.commit()
                mark=(entry['seq'],entry['hash'])
            elif not mark:
                baseline=next(entry for entry in self.entries if entry['kind']=='baseline')
                existing=self.baseline(c)
                if existing and existing==baseline['operations']:
                    c.execute('INSERT INTO '+META+' VALUES(1,?,?)',(baseline['seq'],baseline['hash']));c.commit()
                    mark=(baseline['seq'],baseline['hash'])
            if self.tail:self.append([],'tail-recovery',tail_sha256=hashlib.sha256(self.tail).hexdigest())
            seq=mark[0] if mark else 0
            if seq>len(self.entries) or (mark and self.entries[seq-1]['hash']!=mark[1]):raise ValueError('Projection does not match the authoritative file ledger.')
            for entry in self.entries[seq:]:self.apply(c,entry)
        finally:c.close()

    def finish(self,c):
        if c.operations:
            entry=self.append(c.operations)
            sqlite3.Connection.execute(c,'INSERT OR REPLACE INTO '+META+' VALUES(1,?,?)',(entry['seq'],entry['hash']))
        sqlite3.Connection.commit(c)

    def rebuild(self,destination):
        """Verify and replay to a NEW file; never replace a caller's existing DB."""
        destination=Path(destination)
        if destination.exists():raise ValueError('Recovery destination already exists.')
        with self.locked():
            self.read()
            if self.tail:raise ValueError('Recover the interrupted store append before rebuilding.')
            c=sqlite3.connect(destination)
            try:
                self.meta(c);c.commit()
                for entry in self.entries:self.apply(c,entry)
            finally:c.close()
        return {'path':str(destination),'transactions':len(self.entries)}

class RecordingConnection(sqlite3.Connection):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.operations=[]

    def execute(self,sql,parameters=()):
        return self._execute(sql,parameters)

    def _execute(self,sql,parameters=(),cursor=None):
        keyword=sql.lstrip().split(None,1)[0].upper() if sql.strip() else ''
        if keyword in ('COMMIT','END','ROLLBACK','SAVEPOINT','RELEASE'):raise ValueError('Transaction boundaries belong to the file store.')
        read=keyword in ('SELECT','PRAGMA','EXPLAIN','BEGIN')
        if not read and not self.in_transaction:super().execute('BEGIN IMMEDIATE')
        result=sqlite3.Cursor.execute(cursor,sql,parameters) if cursor is not None else super().execute(sql,parameters)
        if not read:
            parameters={k:encoded(v) for k,v in parameters.items()} if isinstance(parameters,dict) else [encoded(v) for v in parameters]
            self.operations.append({'sql':sql,'parameters':parameters})
        return result

    def cursor(self,*args,**kwargs):
        if args or kwargs:raise ValueError('Custom cursor factories are not supported by the file store.')
        return super().cursor(factory=RecordingCursor)

    def commit(self):raise ValueError('Commit through Brain.connect so the source file is durable first.')

    def executemany(self,sql,parameters):
        result=None
        for values in parameters:result=self.execute(sql,values)
        return result

    def executescript(self,script):
        pending='';result=None
        for character in script:
            pending+=character
            if character==';' and sqlite3.complete_statement(pending):result=self.execute(pending);pending=''
        if pending.strip():result=self.execute(pending)
        return result

class RecordingCursor(sqlite3.Cursor):
    def execute(self,sql,parameters=()):return self.connection._execute(sql,parameters,self)
    def executemany(self,sql,parameters):
        for values in parameters:self.execute(sql,values)
        return self
    def executescript(self,script):raise ValueError('Use the ledger connection executescript method.')

