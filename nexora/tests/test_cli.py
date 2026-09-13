from app import cli


def test_production_help_excludes_dev_and_never_loads_a_command(monkeypatch,capsys):
    monkeypatch.setattr(cli,'find_spec',lambda name:None)
    monkeypatch.setattr(cli.runpy,'run_module',lambda *a,**k: (_ for _ in ()).throw(AssertionError('Command executed')))
    assert cli.main(['--help'])==0
    text=capsys.readouterr().out
    assert 'collect run' in text and 'dev demo' not in text
    assert cli.main(['dev','demo','initialize'])==2


def test_cli_preserves_command_arguments_and_exit_status(monkeypatch):
    import sys
    seen=[]
    def execute(module,run_name):
        seen.append((module,list(sys.argv)))
        raise SystemExit(7)
    monkeypatch.setattr(cli.runpy,'run_module',execute)
    import pytest
    with pytest.raises(SystemExit) as exc:
        cli.main(['collect','status','--from','2026-01-01','--through','2026-01-02'])
    assert exc.value.code==7
    assert seen==[('app.commands.collection_status',['nexora collect status','--from','2026-01-01','--through','2026-01-02'])]


def test_help_on_generator_never_generates_data(monkeypatch,capsys):
    monkeypatch.setattr(cli,'find_spec',lambda name:object())
    monkeypatch.setattr(cli.runpy,'run_module',lambda *a,**k: (_ for _ in ()).throw(AssertionError('Generator executed')))
    assert cli.main(['dev','demo','initialize','--help'])==0
    assert 'dev demo initialize' in capsys.readouterr().out
    assert cli.main(['dev','demo','initialize','--typo'])==2
