"""Native Tally 7.2 response shapes absent from the synthetic exporter."""
import pytest

from kiwi_litchi.common import UserError
from kiwi_litchi.db import Store
from kiwi_litchi.tally import import_books, parse_xml


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16'])
def test_native_controls_and_summary_count_import(tmp_path, encoding):
    raw = '''<ENVELOPE><BODY><DESC><CMPINFO><VOUCHER>2</VOUCHER></CMPINFO></DESC>
    <DATA><COLLECTION><VOUCHER><GUID>native-1</GUID><DATE>20261101</DATE>
    <VOUCHERTYPENAME>Payment</VOUCHERTYPENAME>
    <NARRATION>A&amp;B &#x20B9; &#4; &#x04; \x04</NARRATION>
    <ALLLEDGERENTRIES.LIST><LEDGERNAME>Expense</LEDGERNAME><AMOUNT>-1.25</AMOUNT></ALLLEDGERENTRIES.LIST>
    <ALLLEDGERENTRIES.LIST><LEDGERNAME>Bank</LEDGERNAME><AMOUNT>1.25</AMOUNT></ALLLEDGERENTRIES.LIST>
    </VOUCHER></COLLECTION></DATA></BODY></ENVELOPE>'''.encode(encoding)
    store = Store(tmp_path)
    store.create_client('test', 'Test')
    assert import_books(store, 'test', raw)['vouchers'] == 1
    with store.connect('test') as con:
        assert con.execute('SELECT narration FROM vouchers').fetchone()[0] == 'A&B ₹   '
        assert con.execute('SELECT SUM(amount) FROM lines').fetchone()[0] == 0
        assert con.execute('SELECT amount FROM lines WHERE ledger=?', ('Expense',)).fetchone()[0] == 125
    assert import_books(store, 'test', raw)['vouchers'] == 1
    with store.connect('test') as con:
        assert con.execute('SELECT COUNT(*) FROM vouchers').fetchone()[0] == 1


def test_malformed_accounting_object_still_rejected(tmp_path):
    store = Store(tmp_path)
    store.create_client('test', 'Test')
    with pytest.raises(UserError, match='stable GUID'):
        import_books(store, 'test', b'<ENVELOPE><VOUCHER><DATE>20261101</DATE></VOUCHER></ENVELOPE>')


def test_control_cleanup_does_not_allow_entities():
    with pytest.raises(UserError, match='DTD and entity'):
        parse_xml(b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>')
