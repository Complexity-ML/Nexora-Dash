import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import plotly.graph_objects as go
from app.config import get_settings
from app.collection.status import collection_status
from dash import html
from app.business import workspace_service as business, inventory_service as inventory
from app.dash_ui.components import header, card, table, number, stats, empty, plot


def layout(ctx,query):
    ctx.call(business.source_operator)
    pipeline=ctx.lake()
    lake=pipeline.store
    with ctx.store.connect() as db:
        head=inventory.inventory_head(db,lake)
    manifest=json.loads(lake.get_bytes(head['manifest_key'])) if head else {}
    dimensions=manifest.get('dimensions',{})
    rows=[]
    for name,ref in dimensions.items():
        if isinstance(ref,dict) and ref.get('format')=='delta':
            from app.storage.delta_tables import DeltaReference
            reference=DeltaReference(path=ref['path'],version=ref['version'],observation_date=ref.get('observation_date'))
            table_ref=lake.delta.open(reference)
            schema=table_ref.schema().to_arrow()
            fields=[{'name':f.name,'type':str(f.type)} for f in schema]
            rows.append({'name':name,'format':'Delta','version':str(ref['version']),
                'schema':html.Details([html.Summary(f'{len(fields)} colonnes'),table([('name','Colonne'),('type','Type')],fields)])})
    return html.Div([header('Data Lake','Tables et schémas de la publication active.'),
        *collection_panel(pipeline),
        stats([('Tables de dimensions',number(len(dimensions)),'Références du manifeste'),('Historique',number(len(manifest.get('daily',[]))),'Relevés du manifeste')]),
        card(table([('name','Table'),('format','Format'),('version','Version publiée'),('schema','Schéma')],rows)),
        html.P('DIGIMON → Collecteur Python → Delta Lake → Spark → Résultats publiés',className='flow'),
        html.Small('La détection automatique des données personnelles n’est pas encore disponible.',className='muted')],className='stack')


def help_page(ctx,query):
    return html.Div([header('Comprendre Nexora','De la remontée quotidienne à l’analyse.'),
        card(html.H2('Explorer'),html.P('Choisissez votre espace, puis un produit, une machine ou un utilisateur. Le périmètre logiciel est partagé par les membres de votre espace.')),
        card(html.H2('Analyser'),html.P('Les résultats proviennent des traitements publiés dans le lac. Changer un filtre n’exécute pas une nouvelle collecte ni un traitement Spark.')),
        card(html.H2('Décider'),html.P('Les coûts renseignés servent aux simulations. Les notes et dossiers permettent de partager un examen et son résultat.')),
        card(html.H2('Source'),html.P('Nexora consomme DIGIMON. Les agents et le beacon restent en amont de DIGIMON. Le jeu local est fictif.'))],className='stack')


def collection_panel(pipeline):
    journal=getattr(pipeline,'collection_journal',None)
    if journal is None:
        return [card(html.H2('Collecte quotidienne'),html.P('Collecte automatique non activée. Les tables ci-dessous restent consultables.'))]
    settings=get_settings()
    end=datetime.now(ZoneInfo(settings.business_timezone)).date()-timedelta(days=1)
    start=end-timedelta(days=29)
    report=collection_status(pipeline.store,journal,source=pipeline.collection_source,scope=pipeline.collection_scope,
        start=start,end=end,limit=30,quality_limit=10,require_daily_worker=True,require_worker=True)
    return collection_report_cards(report)


def collection_report_cards(report):
    start=datetime.fromisoformat(report['window']['from']).date()
    end=datetime.fromisoformat(report['window']['through']).date()
    days=[(start+timedelta(days=i)).isoformat() for i in range((end-start).days+1)]
    missing=set(report['missing_days'])
    timeline=go.Figure(go.Heatmap(x=days,y=['Publication'],z=[[0 if d in missing else 1 for d in days]],
        text=[['Non publiée' if d in missing else 'Publiée' for d in days]],zmin=0,zmax=1,
        colorscale=[[0,'#596776'],[.49,'#596776'],[.5,'#64d5b2'],[1,'#64d5b2']],showscale=False,
        hovertemplate='%{x}<br>%{text}<extra></extra>'))
    timeline.update_layout(height=180)
    labels={'published':'Publiées','running':'En traitement','retryable':'À reprendre','rejected':'Rejetées','received':'Reçues'}
    states=report['runs_by_state']
    counts=go.Figure(go.Bar(x=[labels.get(k,k) for k in states],y=list(states.values()),marker_color='#68b4ec'))
    counts.update_yaxes(title='Exécutions',rangemode='tozero',dtick=1)
    workers=[]
    for key,label in [('daily','Collecte quotidienne'),('recovery','Reprise des échecs')]:
        state=report[key+'_workers']
        latest=report.get(key+'_worker')
        health='Actif' if state['responsive'] else 'À vérifier' if latest else 'Non démarré'
        workers.append((label,health,f"{state['responsive']} processus répondant(s)"))
    return [stats(workers),card(html.H2('Publication des 30 dernières journées terminées'),
        html.Small(f"{report['observed_days']} / {report['expected_days']} journées publiées · une journée absente n’est pas une mesure à zéro."),plot(timeline)),
        card(html.H2('État des exécutions de collecte'),html.Small('Ensemble des exécutions du flux configuré, toutes périodes.'),plot(counts)),
        html.Details([html.Summary(f"Points à examiner : {report['issues_total']}"),
            table([('state','État'),('error_code','Code'),('lease_expired','Bail expiré')],report['issues'])],className='card')]
