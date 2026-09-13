import json
from dash import html
from app.business import workspace_service as business, inventory_service as inventory
from app.dash_ui.components import header, card, table, number, stats, empty


def layout(ctx,query):
    ctx.call(business.source_operator)
    lake=ctx.lake().store
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
