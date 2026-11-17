"""In-memory test double only. It does not validate real TallyPrime compatibility."""
from http.server import BaseHTTPRequestHandler,HTTPServer
from .demo import demo_xml
from .tally import parse_xml


def serve(port=9000):
    seen=set()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            size=int(self.headers.get('Content-Length','0'))
            if size>25*1024*1024:
                self.send_error(413); return
            try:
                root=parse_xml(self.rfile.read(size))
                if root.findtext('.//TALLYREQUEST','').startswith('Export'):
                    output=demo_xml()
                else:
                    created,ignored,deleted=0,0,0
                    for v in root.findall('.//VOUCHER'):
                        guid=v.findtext('GUID')
                        if not guid: raise ValueError('Missing GUID')
                        if v.get('ACTION')=='Delete':
                            if guid in seen: seen.remove(guid); deleted+=1
                        elif guid in seen: ignored+=1
                        else: seen.add(guid); created+=1
                    output=f'<RESPONSE><CREATED>{created}</CREATED><IGNORED>{ignored}</IGNORED><DELETED>{deleted}</DELETED><ERRORS>0</ERRORS></RESPONSE>'.encode()
                self.send_response(200); self.send_header('Content-Type','application/xml'); self.end_headers(); self.wfile.write(output)
            except Exception:
                self.send_error(400,'Invalid simulator request')
    print(f'DEMO Tally simulator at 127.0.0.1:{port}; not real TallyPrime',flush=True)
    HTTPServer(('127.0.0.1',port),Handler).serve_forever()
