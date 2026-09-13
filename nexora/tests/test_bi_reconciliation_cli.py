from types import SimpleNamespace
import pytest
from scripts import revoke_restored_bi_readers as cli


def test_root_must_be_selected_explicitly(monkeypatch,capsys):
    monkeypatch.setattr('sys.argv',['reconcile','--root'])
    monkeypatch.setattr(cli,'get_settings',lambda:SimpleNamespace(database_url='test'))
    monkeypatch.setattr(cli,'BusinessStore',lambda _:None)
    calls=[]
    def invoke(store,**args):
        calls.append(args)
        return {'readers':0,'applied':args['apply']}
    monkeypatch.setattr(cli,'revoke_namespace_readers',invoke)
    assert cli.main() == 0
    assert calls == [{'namespace':'','apply':False}]
    monkeypatch.setattr('sys.argv',['reconcile','--root','--namespace','demo'])
    with pytest.raises(SystemExit):
        cli.main()
    assert len(calls) == 1
