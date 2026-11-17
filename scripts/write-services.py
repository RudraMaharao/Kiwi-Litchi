import os
import platform
import sys
from pathlib import Path

if platform.system() != 'Linux': raise SystemExit('Linux only')
root=Path(__file__).resolve().parents[1]
python=root/'.venv/bin/python'
data=Path(os.environ.get('KIWI_DATA_DIR',str(Path.home()/'.local/share/kiwi-litchi'))).resolve()
if not (data/'auth.json').exists(): raise SystemExit('Run install-linux.sh and set a password first')
def quote(s):
    return '"'+str(s).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
units=Path.home()/'.config/systemd/user'
units.mkdir(parents=True,exist_ok=True)
def service(name,description,command,oneshot=False,module='kiwi_litchi'):
    text=f'''[Unit]
Description={description}
After=network.target

[Service]
Type={'oneshot' if oneshot else 'simple'}
WorkingDirectory={str(root).replace('%','%%')}
Environment={quote('KIWI_DATA_DIR='+str(data))}
ExecStart={quote(python)} -m {module} {command}
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
MemoryMax=2G
Nice=10
'''
    if not oneshot: text+='Restart=on-failure\nRestartSec=5\n'
    else: text+='TimeoutStartSec=5h\n'
    text+='\n[Install]\nWantedBy=default.target\n'
    (units/(name+'.service')).write_text(text)
def timer(name,schedule):
    (units/(name+'.timer')).write_text(f'''[Unit]
Description={name} schedule

[Timer]
{schedule}
Persistent=false

[Install]
WantedBy=timers.target
''')
service('kiwi-web','Kiwi and Litchi local web app','serve')
service('kiwi-backup','Consistent Kiwi backups','backup',True)
service('litchi-batch','Litchi nightly report','batch'+(' --embeddings' if '--embeddings' in sys.argv else ''),True)
service('kiwi-watch','Kiwi watch folder import','watch-once',True)
service('kiwi-lab','Kiwi statement regression check','lab',True,module='kiwi_litchi.launcher')
timer('kiwi-backup','OnCalendar=*-*-* 00:30:00')
timer('litchi-batch','OnCalendar=*-*-* 01:00:00')
timer('kiwi-watch','OnBootSec=2min\nOnUnitActiveSec=60s')
timer('kiwi-lab','OnCalendar=*-*-* 00:45:00')
print('Wrote user services to',units)
print('Nightly embeddings:', '--embeddings' in sys.argv)
