"""Real file round trips on synthetic fixtures; no model/service mocks in this file."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from kiwi_litchi.ingest import read_tables, parse_tables
from kiwi_litchi.common import UserError


class AdapterTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def check_file(self,p):
        tables,kind=read_tables(p)
        rows,issues=parse_tables(tables,10000,9000,kind)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['debit'],1000)
        self.assertFalse(issues);self.assertFalse(any(x.startswith('BLOCK') for x in rows[0]['issues']))
        return kind
    def test_xlsx_dates_and_values(self):
        from openpyxl import Workbook
        wb=Workbook();s=wb.active
        s.append(['Date','Narration','Debit','Credit','Balance'])
        s.append([datetime(2026,10,1),'Mehta',10,None,90])
        p=self.root/'test.xlsx';wb.save(p);wb.close();self.check_file(p)
    def test_html_disguised_as_xls(self):
        p=self.root/'bank.xls';p.write_text('<html><table><tr><th>Date</th><th>Narration</th><th>Debit</th><th>Credit</th><th>Balance</th></tr><tr><td>01/10/2026</td><td>Mehta</td><td>10</td><td></td><td>90</td></tr></table></html>')
        self.check_file(p)
    def test_tsv(self):
        p=self.root/'bank.tsv';p.write_text('Date\tNarration\tDebit\tCredit\tBalance\n01/10/2026\tMehta\t10\t\t90\n')
        self.check_file(p)
    def test_two_line_header(self):
        rows,issues=parse_tables([[['Date','Narration','Withdrawal','Deposit','Closing'],['','','Amount','Amount','Balance'],['01/10/2026','Mehta','10','','90']]],10000,9000)
        self.assertEqual(len(rows),1);self.assertFalse(issues)
    def pdf(self):
        from reportlab.pdfgen import canvas
        p=self.root/'bank.pdf';c=canvas.Canvas(str(p))
        for y,cells in [(750,['Date','Narration','Debit','Credit','Balance']),(720,['01/10/2026','Mehta','10.00','0.00','90.00'])]:
            for x,text in zip([30,160,300,390,480],cells):c.drawString(x,y,text)
        c.save();return p
    def test_text_pdf(self):self.assertEqual(self.check_file(self.pdf()),'pdf')
    def test_password_protected_pdf(self):
        from pypdf import PdfReader,PdfWriter
        writer=PdfWriter();reader=PdfReader(self.pdf())
        for page in reader.pages:writer.add_page(page)
        writer.encrypt('synthetic-password',algorithm='RC4-128')
        p=self.root/'locked.pdf'
        with p.open('wb') as f:writer.write(f)
        tables,kind=read_tables(p,'synthetic-password');rows,issues=parse_tables(tables,10000,9000,kind)
        self.assertEqual(rows[0]['debit'],1000);self.assertFalse(issues)
    def image(self):
        from PIL import Image,ImageDraw,ImageFont
        im=Image.new('RGB',(1250,250),'white');d=ImageDraw.Draw(im)
        font=ImageFont.load_default(size=29)
        for y,cells in [(35,['Date','Narration','Debit','Credit','Balance']),(120,['01/10/2026','Mehta','10.00','0.00','90.00'])]:
            for x,text in zip([20,320,620,820,1020],cells):d.text((x,y),text,font=font,fill='black')
        return im
    def test_actual_ocr_png(self):
        p=self.root/'scan.png';self.image().save(p)
        self.assertEqual(self.check_file(p),'ocr')
    def test_unsupported_image_is_not_guessed(self):
        from PIL import Image
        p=self.root/'blank.png';Image.new('RGB',(200,200),'white').save(p)
        with self.assertRaises(UserError):read_tables(p)


if __name__=='__main__':unittest.main()
