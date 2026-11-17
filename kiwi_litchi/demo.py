import xml.etree.ElementTree as ET
from .tally import envelope, tag, import_books


def demo_xml():
    root, data = envelope('Demo Trading Company')
    ledgers = [('Demo Bank','Bank Accounts'),('Mehta Hardware','Sundry Creditors'),('Office Rent','Indirect Expenses'),
               ('Bank Charges','Indirect Expenses'),('Asha Stores','Sundry Debtors'),('Cash','Cash-in-Hand')]
    for name, parent in ledgers:
        l = ET.SubElement(ET.SubElement(data,'TALLYMESSAGE'),'LEDGER',NAME=name)
        tag(l,'PARENT',parent)
    for m in range(13):
        y, mo = divmod(2025*12+9+m,12)
        day = f'{y}{mo+1:02d}10'
        for j,(ledger,amount,kind,narration) in enumerate([
            ('Mehta Hardware',250000,'Payment','UPI/Mehta Hardware/mehta@ybl/123456789012'),
            ('Office Rent',1200000,'Payment','NEFT office rent monthly'),
            ('Asha Stores',-1000000,'Receipt','NEFT/Asha Stores/customer settlement')]):
            v = ET.SubElement(ET.SubElement(data,'TALLYMESSAGE'),'VOUCHER',VCHTYPE=kind)
            for k,val in [('GUID',f'demo-{m}-{j}'),('DATE',day),('VOUCHERTYPENAME',kind),('NARRATION',narration),('PARTYLEDGERNAME',ledger)]: tag(v,k,val)
            from .common import rupees
            for name,a in [(ledger,-amount),('Demo Bank',amount)]:
                entry = ET.SubElement(v,'ALLLEDGERENTRIES.LIST')
                tag(entry,'LEDGERNAME',name)
                tag(entry,'AMOUNT',rupees(a))
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)


def seed(store):
    if any(c['id']=='demo' for c in store.clients()): return {'note':'Demo client already exists; left unchanged'}
    store.create_client('demo','Demo Trading Company')
    result = import_books(store,'demo',demo_xml())
    with store.connect('demo') as con:
        for pattern,ledger in [('Mehta','Mehta Hardware'),('Asha','Asha Stores'),('bank charges','Bank Charges')]:
            con.execute('INSERT INTO rules(pattern,ledger) VALUES(?,?)',(pattern,ledger))
    return {'client':'demo','synthetic':True,**result}
