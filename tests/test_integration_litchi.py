import io
import json
from pathlib import Path
import pytest
from werkzeug.test import Client
from werkzeug.wrappers import Response
from bahi import db,service
from kiwi_litchi.db import Store
from kiwi_litchi.bridge import init_kiwi,kiwi_config,kiwi_db,sync_clients,queue,apply_suggestion,create_combined_app
from kiwi_litchi.web import set_password
from kiwi_litchi.operations import backup,restore
from kiwi_litchi.tally import import_books
from kiwi_litchi.intelligence import book_answer


@pytest.fixture
def linked(tmp_path):
    store=Store(tmp_path/'data');init_kiwi(store,demo=True);return store


def test_demo_has_original_47_transactions(linked):
    with kiwi_db(linked) as con:assert con.execute('SELECT COUNT(*) FROM txns').fetchone()[0]==47
    assert linked.config('kiwi-1')['name']=='Sharma Traders (Demo)'


def test_unposted_bank_rows_do_not_become_book_totals(linked):
    with linked.connect('kiwi-1') as con:assert con.execute('SELECT COUNT(*) FROM vouchers').fetchone()[0]==0


def test_bridge_sync_idempotent(linked):
    sync_clients(linked);sync_clients(linked)
    assert len(linked.clients())==1


def test_rules_and_memory_keep_priority(linked):
    rows=queue(linked,'kiwi-1')
    assert rows
    assert all(r['map_source'] in ('suspense','match','litchi') for r in rows)
    with kiwi_db(linked) as con:
        r=rows[0];db.add_rule(con,1,r['narration'],'Office Expenses');service.remap(con,1)
    assert r['id'] not in [x['id'] for x in queue(linked,'kiwi-1')]


def test_applying_prediction_uses_kiwi_learning(linked):
    row=queue(linked,'kiwi-1')[0]
    with linked.connect('kiwi-1') as con:con.execute("INSERT OR REPLACE INTO ledgers VALUES('My Reviewed Ledger','Indirect Expenses')")
    result=apply_suggestion(linked,'kiwi-1',row['id'],'My Reviewed Ledger')
    assert result['changed']==1
    with kiwi_db(linked) as con:
        r=con.execute('SELECT * FROM txns WHERE id=?',(row['id'],)).fetchone()
        assert r['map_source']=='manual' and r['ledger']=='My Reviewed Ledger'
        assert con.execute("SELECT COUNT(*) FROM memory WHERE ledger='My Reviewed Ledger'").fetchone()[0]>0


def test_combined_login_and_navigation(linked):
    set_password(linked,'test-password-12345')
    client=Client(create_combined_app(linked),Response)
    assert client.get('/',base_url='http://localhost:8765').status_code==302
    page=client.get('/litchi/',base_url='http://localhost:8765')
    assert b'/litchi/app.js' in page.data
    r=client.post('/litchi/api/login',json={'password':'test-password-12345'},base_url='http://localhost:8765')
    assert r.status_code==200
    home=client.get('/',base_url='http://localhost:8765')
    assert home.status_code==200 and b'Kiwi' in home.data and b'Litchi assistant' in home.data
    assert client.get('/c/1/review',base_url='http://localhost:8765').status_code==200
    assert client.get('/litchi/api/c/kiwi-1/summary',base_url='http://localhost:8765').json['kiwi']['entries']==47


def test_combined_host_protection(linked):
    set_password(linked,'test-password-12345')
    client=Client(create_combined_app(linked),Response)
    assert client.get('/',base_url='http://evil.example:8765').status_code==400


def test_combined_backup_restore(linked,tmp_path):
    folder=backup(linked);new=Store(tmp_path/'restore')
    restore(new,folder)
    with kiwi_db(new) as con:assert con.execute('SELECT COUNT(*) FROM txns').fetchone()[0]==47
    assert (new.root/'kiwi/data/uploads').exists()


def test_client_queue_isolated(linked):
    with kiwi_db(linked) as con:db.add_client(con,'Other Client')
    sync_clients(linked)
    assert queue(linked,'kiwi-2')==[]


def test_selected_quantized_model(linked):
    assert linked.config('kiwi-1')['intent_model']=='llama3.2:1b-instruct-q4_K_M'


def test_shared_ledger_edit_updates_kiwi(linked):
    from kiwi_litchi.bridge import save_ledger
    save_ledger(linked,'kiwi-1','Shared Expense','Indirect Expenses')
    with kiwi_db(linked) as con:
        ledger=con.execute("SELECT * FROM ledgers WHERE name='Shared Expense'").fetchone()
        assert ledger['parent']=='Indirect Expenses' and ledger['kind']=='expense'


def test_shared_rule_edits_remap_kiwi(linked):
    from kiwi_litchi.bridge import save_rule,linked_rules
    row=queue(linked,'kiwi-1')[0]
    save_rule(linked,'kiwi-1',row['narration'],'Bank Charges')
    with kiwi_db(linked) as con:
        updated=con.execute('SELECT * FROM txns WHERE id=?',(row['id'],)).fetchone()
        assert updated['ledger']=='Bank Charges' and updated['map_source']=='rule'
    assert any(r['pattern']==row['narration'] for r in linked_rules(linked,'kiwi-1'))


def test_approval_cannot_bypass_balance_failure(linked):
    with kiwi_db(linked) as con:
        row=con.execute("SELECT * FROM txns WHERE status='ready' LIMIT 1").fetchone()
        con.execute("UPDATE txns SET check_status='mismatch',status='review' WHERE id=?",(row['id'],));con.commit()
        service.set_status(con,1,[row['id']],'approve')
        assert con.execute('SELECT status FROM txns WHERE id=?',(row['id'],)).fetchone()[0]=='review'


def test_export_planner_blocks_stale_ready_balance_failure(linked):
    with kiwi_db(linked) as con:
        row=con.execute("SELECT * FROM txns WHERE status='ready' LIMIT 1").fetchone()
        con.execute("UPDATE txns SET check_status='mismatch' WHERE id=?",(row['id'],));con.commit()
        plan=service.plan_vouchers(con,kiwi_config(linked),1,[row['id']])
        assert not plan.specs and 'balance' in plan.problems[0]
