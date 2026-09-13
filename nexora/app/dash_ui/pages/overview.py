from dash import html
import json
import plotly.graph_objects as go
from app.business import exploration
from app.dash_ui.components import header, stats, card, link, table, number, plot, daily_figure, empty, route
from app.business import inventory_service as inventory


def layout(ctx, query):
    summary=ctx.summary()
    estate=ctx.call(inventory.inventory,ctx.wid,limit=1,lake=True)
    counts=estate.get('counts',{})
    opportunities=sorted(summary.inactive,key=lambda row:row.recovery_potential,reverse=True)
    distributions=[]
    for dimension,title in [('subsidiary','Le parc par filiale'),('os','Systèmes du parc')]:
        data=ctx.call(exploration.aggregate,ctx.wid,entity='machines',dimension=dimension,measure='count',limit=12,lake=True)
        rows=data['rows']
        fig=go.Figure(go.Bar(x=[r['value'] for r in rows],y=[r['label0'] or 'Non remonté' for r in rows],orientation='h',
            customdata=[route('explore',entity='machines',dimension=dimension,selection=json.dumps({dimension:r['key0']}),view='records') for r in rows]))
        fig.update_yaxes(autorange='reversed',automargin=True)
        distributions.append(card(html.H2(title),html.Small('Cliquez sur une barre pour explorer les machines. 12 groupes au maximum.'),plot(fig,{'type':'insight-chart','key':dimension})))
    return html.Div([
        header('Votre parc, dans la durée.', 'Explorez les usages et identifiez les sujets à examiner.', [link('Explorer les données →','explore')]),
        stats([('Machines et VM',number(counts.get('machines')),'Dans votre périmètre'),
               ('Utilisateurs',number(counts.get('users')),'Salariés et prestataires'),
               ('Sites',number(counts.get('sites')),'Implantations observées'),
               ('Pools analysés',number(summary.pools_total),'Avec historique de capacité')]),
        html.Div(distributions,className='settings-profile'),
        html.Div([
            card(html.H2('Comparer les filiales'),html.P('Répartition du parc, systèmes et environnements.'),link('Explorer →','explore',dimension='subsidiary',split='kind')),
            card(html.H2('Comprendre les usages'),html.P('Installations actives, observations et sujets à examiner.'),link('Analyser →','savings')),
            card(html.H2('Contrôler les remontées'),html.P('Présence des dimensions et champs manquants.'),link('Voir la qualité →','quality'))
        ],className='product-grid'),
        html.Div([
            card(html.Div([html.H2('Usage des capacités'),link('Comparer les périodes →','annual')],className='section-heading'),
                 plot(daily_figure(summary.trends))),
            card(html.H2('À examiner'),html.Strong(number(summary.recovery_potential),className='metric'),
                 html.P('Unités de capacité potentiellement récupérables'),
                 html.P(f'{len(opportunities)} pools sous-utilisés · {summary.pools_at_risk} pools en tension'),
                 link('Ouvrir les analyses →','savings'), className='insight')
        ],className='split'),
        card(html.Div([html.H2('Opportunités sur les pools'),link('Toutes les analyses →','savings')],className='section-heading'),
             table([('name','Logiciel'),('usage','Utilisation moyenne'),('quantity','Capacité à examiner'),('action','')],
             [{'name':x.software_name,'usage':f'{x.utilization_rate:.1%}', 'quantity':number(x.recovery_potential),
               'action':link('Examiner →','software',pool=x.license_pool_id)} for x in opportunities])),
        html.Small('Analyses des pools avec historique. Les installations et les unités de licence restent distinctes.',className='muted')
    ],className='stack')
