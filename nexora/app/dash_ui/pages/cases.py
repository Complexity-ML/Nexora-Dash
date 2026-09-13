from dash import html
from app.business import workspace_service as service
from app.dash_ui.components import header, card, link, table, money, field, action, empty, stats, number
from app.dash_ui.pages.software import products

STATUS={'preparing':'À examiner','in_progress':'En cours','completed':'Terminé','sent':'Transmis','response_received':'Retour reçu'}


def layout(ctx,query):
    if query.get('id'): return detail(ctx,query['id'])
    rows=ctx.call(service.cases,ctx.wid)
    if query.get('pool'): rows=[r for r in rows if r['pool_id']==query['pool']]
    catalog=products(ctx,False)
    opts=[{'label':p['name'],'value':p.get('license_pool_id') or p['software_id']} for p in catalog]
    selected=query.get('pool') or (opts[0]['value'] if opts else None)
    return html.Div([header('Dossiers','Partagez vos analyses et suivez les actions décidées.',[html.Button('Exporter CSV',id='export-table',n_clicks=0,className='button')]),
        stats([('Dossiers',number(len(rows)),'Dans cet espace'),('En cours',number(sum(r['status']=='in_progress' for r in rows)),'Examens engagés')]),
        card(table([('title','Dossier'),('status','État'),('amount','Hypothèse annuelle')],[{
            'title':link(r['title'],'cases',id=r['id']),'status':STATUS.get(r['status'],r['status']),
            'amount':money(r['quantity']*r['annual_unit_cents'])} for r in rows])),
        card(html.H2('Ouvrir un dossier'),html.Div([
            field('case-product','Produit',selected,options=opts),field('case-title','Titre',''),
            field('case-quantity','Quantité à examiner',0,kind='number',min=0,max=10000000),
            field('case-evidence','Motif et observations','',kind='textarea'),
            action('Créer le dossier','case-create',disabled=not ctx.writable)],className='form-grid'))],className='stack')


def detail(ctx,cid):
    value=ctx.call(service.detail,ctx.wid,cid)
    members=ctx.call(service.members,ctx.wid)
    notes=[e for e in value['events'] if e.get('comment') and not e['comment']['deleted']]
    cards=[]
    for note in notes:
        edit=note['actor_id']==ctx.user['id'] and ctx.writable
        remove=edit or ctx.workspace['role']=='admin'
        cards.append(card(html.Div([html.Strong(note['actor_name']),
            html.Div([action('✎','note-edit:'+str(note['id']),disabled=not edit),action('×','note-delete:'+str(note['id']),disabled=not remove,danger=True)],className='actions')],className='section-heading'),
            field('note-text:'+str(note['id']),'Note',note['comment']['text'],kind='textarea',disabled=not edit),
            field('note-version:'+str(note['id']),'Version',note['comment']['version'],kind='hidden')))
    allowed={'preparing':['in_progress'],'in_progress':['preparing','completed'],'completed':['preparing'],
             'sent':['preparing','completed'],'response_received':['preparing','completed']}.get(value['status'],[])
    return html.Div([link('← Dossiers','cases'),header(value['title'],STATUS.get(value['status'],value['status']),[html.Button('Exporter le dossier',id={'type':'export-case','id':cid},n_clicks=0,className='button')]),
        field('case-id','Dossier',cid,kind='hidden'),field('case-version','Version',value['version'],kind='hidden'),
        stats([('Quantité examinée',number(value['quantity']),'Hypothèse du dossier'),('Valeur annuelle',money(value['quantity']*value['annual_unit_cents']),'Simulation')]),
        card(html.H2('Hypothèses'),html.P(value['evidence']),html.Div([
            field('case-assignee','Responsable',value['assignee_id'] or '',options=[{'label':'Non assigné','value':''}]+[{'label':m['name'],'value':m['id']} for m in members if m['role']!='reader']),
            field('case-quantity','Quantité',value['quantity'],kind='number',min=0,max=10000000),
            field('case-cost','Coût annuel par unité (€)',value['annual_unit_cents']/100,kind='number',min=0,max=10000000),
            action('Enregistrer les hypothèses','case-update',disabled=not ctx.writable or value['status'] not in ('preparing','in_progress'))],className='form-grid')),
        card(html.H2('Avancement'),html.Div([
            field('case-status','Prochain état',allowed[0] if allowed else None,options=[{'label':STATUS[k],'value':k} for k in allowed]),
            field('case-reason','Note de décision','',kind='textarea'),
            field('case-outcome','Résultat à la clôture','no_action',options=[{'label':'Sans suite','value':'no_action'},{'label':'Capacité récupérée','value':'recovered'}]),
            field('case-actual','Quantité récupérée',None,kind='number',min=1,max=10000000),
            action('Mettre à jour','case-progress',disabled=not ctx.writable)],className='form-grid')),
        html.H2('Notes'),*cards,
        card(field('new-note','Ajouter une note','',kind='textarea'),action('Ajouter la note','note-create',disabled=not ctx.writable)),
        html.Details([html.Summary('Supprimer ce dossier'),html.P('Le dossier et ses notes seront supprimés.'),
            action('Supprimer définitivement','case-delete',disabled=not ctx.writable,danger=True)])],className='stack')
