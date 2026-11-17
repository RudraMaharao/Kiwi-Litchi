"""Public kiwi CLI. Original bahi commands remain compatible."""
import sys
from .db import Store
from .bridge import kiwi_config,init_kiwi


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if not args:args=['serve']
    if args[0] in ('serve','password'):
        from .cli import main as litchi
        return litchi(args)
    store=Store()
    if args[0]=='init':
        print('Data directory:',store.root);init_kiwi(store);return 0
    if args[0]=='demo':
        print('Linked clients:',init_kiwi(store,demo=True));return 0
    from bahi.cli import main as bahi
    return bahi(['--home',str(kiwi_config(store).home),*args])


if __name__=='__main__':raise SystemExit(main())
