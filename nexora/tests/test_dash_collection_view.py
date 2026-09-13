from types import SimpleNamespace
from app.dash_ui.pages.lake import collection_panel, collection_report_cards


def test_disabled_collector_is_explicit_without_querying_lake():
    cards=collection_panel(SimpleNamespace())
    assert 'non activée' in str(cards)


def test_collection_plot_uses_publication_gaps_not_zero_usage():
    report={'window':{'from':'2026-01-01','through':'2026-01-03'},'missing_days':['2026-01-02'],
        'observed_days':2,'expected_days':3,'runs_by_state':{'published':2,'retryable':1},'issues_total':0,'issues':[],
        'daily_workers':{'responsive':0},'daily_worker':None,'recovery_workers':{'responsive':1},'recovery_worker':{'state':'waiting'}}
    cards=collection_report_cards(report)
    figure=cards[1].children[2].figure
    assert list(figure.data[0].z[0])==[1,0,1]
    assert list(figure.data[0].text[0])==['Publiée','Non publiée','Publiée']
    assert 'Non démarré' in str(cards[0])
