"""Run on Linux AFTER starting Ollama and Qdrant. No skips or simulated success.

Creates and deletes only its uniquely named Qdrant test collection. Does not touch client books.
Tally is deliberately checked separately using docs/TALLY-TEST.md against a test company.
"""
import json
import platform
import sqlite3
import sys
import time
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from kiwi_litchi.common import http
from kiwi_litchi.intelligence import Ollama,pack
from kiwi_litchi.law import Qdrant

report={'platform':platform.platform(),'checks':[],'models':{}}
def check(name,func):
    started=time.monotonic()
    try:
        result=func()
        report['checks'].append({'name':name,'passed':True,'seconds':round(time.monotonic()-started,3),'details':result})
    except Exception as e:
        report['checks'].append({'name':name,'passed':False,'seconds':round(time.monotonic()-started,3),'error':str(e)})
def linux():
    if platform.system()!='Linux':raise RuntimeError('This release check must run on Linux')
    return platform.release()
def vec():
    import sqlite_vec
    con=sqlite3.connect(':memory:')
    try:
        con.enable_load_extension(True);sqlite_vec.load(con);con.enable_load_extension(False)
        value=con.execute('SELECT vec_distance_cosine(?,?)',(pack([1.,0.]),pack([1.,0.]))).fetchone()[0]
        if abs(value)>0.00001:raise AssertionError('Identical-vector distance is not zero')
        return con.execute('SELECT vec_version()').fetchone()[0]
    finally:con.close()
def embed():
    model=Ollama('nomic-embed-text');v=model.embed(['Mehta hardware payment','office rent'])
    if len(v)!=2 or not v[0]:raise AssertionError('Invalid embedding response')
    report['models']['embedding']=model.stamp
    model.unload()
    return {'dimensions':len(v[0]),'texts':len(v)}
def intent():
    model=Ollama('llama3.2:1b-instruct-q4_K_M')
    schema={'type':'object','properties':{'ledger':{'type':'string'},'measure':{'type':'string'},'start':{'type':'string'},'end':{'type':'string'}},'required':['ledger','measure','start','end'],'additionalProperties':False}
    answer=model.structured('Extract the intent from "payments to Mehta Hardware in FY 2026-27". ledger must be Mehta Hardware. measure must be payments. Indian FY 2026-27 begins 2026-04-01 and ends 2027-03-31.',schema)
    expected={'ledger':'Mehta Hardware','measure':'payments','start':'2026-04-01','end':'2027-03-31'}
    if answer!=expected:raise AssertionError('Incorrect intent: '+json.dumps(answer))
    report['models']['intent']=model.stamp
    model.unload()
    return answer
def qdrant():
    q=Qdrant();name='kiwi_test_'+uuid.uuid4().hex;created=False
    try:
        q.create(name,3);created=True
        point=str(uuid.uuid4())
        q.upsert(name,[{'id':point,'vector':[1.,0.,0.],'payload':{'demo':True,'valid_from_ord':1,'valid_to_ord':3652059,'as_of_ord':1,'act':'Test'}}])
        result=q.query(name,[1.,0.,0.],'2026-10-26','Test',True)
        if len(result)!=1 or result[0]['id']!=point:raise AssertionError('Vector or payload-filter query failed')
        if q.query(name,[1.,0.,0.],'2026-10-26','Other',True):raise AssertionError('Act filter did not isolate results')
        return {'query':'passed','filter':'passed','version':http(q.url).get('version')}
    finally:
        if created:http(q.url+'/collections/'+name,method='DELETE')

for name,func in [('Linux runtime',linux),('Native sqlite-vec',vec),('Real Ollama embeddings',embed),('Real Ollama structured intent',intent),('Real Qdrant roundtrip',qdrant)]:check(name,func)
report['passed']=all(x['passed'] for x in report['checks'])
out=Path(sys.argv[1]) if len(sys.argv)>1 else Path('live-stack-results.json')
out.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
raise SystemExit(0 if report['passed'] else 1)
