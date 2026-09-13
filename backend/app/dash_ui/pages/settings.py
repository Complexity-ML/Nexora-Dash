from dash import html, dcc
from app.business import workspace_service as service, portfolio_service as portfolio, settings_service as settings
from app.dash_ui.components import header, card, field, action, table, link
from app.dash_ui.pages.software import products

ROLES=[{'label':'Lecteur','value':'reader'},{'label':'Analyste','value':'analyst'},{'label':'Administrateur','value':'admin'}]


def layout(ctx,query):
    members=ctx.call(service.members,ctx.wid)
    prefs=ctx.call(settings.get)
    admin=ctx.workspace['role']=='admin'
    rows=[]
    for m in members:
        rows.append({'name':html.Div([html.Strong(m['name']),html.Small(m['email'])]),
            'role':field('member-role:'+m['id'],'Rôle',m['role'],options=ROLES,disabled=not admin),
            'action':html.Div([field('member-email:'+m['id'],'E-mail',m['email'],kind='hidden'),
                field('member-original:'+m['id'],'Rôle',m['role'],kind='hidden'),
                action('Enregistrer','member-save:'+m['id'],disabled=not admin),
                action('Retirer','member-remove:'+m['id'],disabled=not admin,danger=True)],className='actions')})
    return html.Div([header('Paramètres','Votre profil, votre espace et ses accès.'),
        html.Div([card(html.H2('Votre profil'),field('profile-name','Nom affiché',ctx.user['name']),action('Enregistrer','profile-save')),
                  card(html.H2('Espace de travail'),field('workspace-name','Nom',ctx.workspace['name']),action('Renommer','workspace-save',disabled=not admin))],className='settings-profile'),
        card(html.H2('Membres'),table([('name','Membre'),('role','Rôle'),('action','')],rows),
            html.Details([html.Summary('Ajouter un membre'),html.Div([field('member-email','Adresse e-mail',''),
                field('member-role','Rôle','reader',options=ROLES),action('Ajouter un compte existant','member-add',disabled=not admin),
                field('account-name','Nom du nouveau compte',''),field('account-password','Mot de passe initial','',kind='password'),
                action('Créer et ajouter le compte','account-create',disabled=not admin)],className='form-grid')]),className='members-card'),
        card(html.H2('Seuils d’analyse'),html.P('Les nouvelles valeurs seront utilisées lors du prochain traitement du lac.'),
            html.Div([field('threshold','Sous-utilisation (%)',prefs['threshold']*100,kind='number',min=.1,max=100),
                field('reserve','Réserve (%)',prefs['buffer']*100,kind='number',min=0,max=100),
                field('settings-version','Version',prefs['version'],kind='hidden'),
                action('Enregistrer les seuils','settings-save',disabled=not prefs['can_edit'])],className='form-grid')),
        card(html.H2('Créer un espace'),html.Div([field('new-workspace','Nom de l’espace',''),action('Créer','workspace-create')],className='toolbar')),
        link('Modifier le périmètre logiciel →','portfolio')],className='stack')


def portfolio_page(ctx,query):
    value=ctx.call(portfolio.portfolio,ctx.wid)
    items=ctx.call(portfolio.catalog,lake=True)
    choices=[{'label':p['name'],'value':p['pool_id']} for p in items]
    return html.Div([header('Mon périmètre','Les logiciels dont votre équipe SAM a la charge.'),
        card(field('portfolio-mode','Périmètre','all' if value['all_catalog'] else 'selected',options=[{'label':'Tout le catalogue, y compris les prochains produits','value':'all'},{'label':'Sélection de produits','value':'selected'}]),
            field('portfolio-products','Logiciels',value['pool_ids'],options=choices,multi=True),
            field('portfolio-version','Version',value['version'],kind='hidden'),
            action('Enregistrer le périmètre','portfolio-save',disabled=not value['can_edit']))],className='stack')
