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
            'role':field('member-role:'+m['id'],'Rôle',m['role'],options=ROLES,searchable=False,maxHeight=240,optionHeight=42,disabled=not admin),
            'action':html.Div([field('member-email:'+m['id'],'E-mail',m['email'],kind='hidden'),
                field('member-original:'+m['id'],'Rôle',m['role'],kind='hidden'),
                action('Enregistrer','member-save:'+m['id'],disabled=not admin),
                action('Retirer','member-remove:'+m['id'],disabled=not admin,danger=True)],className='actions')})
    return html.Div([header('Paramètres','Votre profil, votre espace et ses accès.'),
        html.Div([card(html.H2('Votre profil'),field('profile-name','Nom affiché',ctx.user['name']),action('Enregistrer','profile-save')),
                  card(html.H2('Espace de travail'),field('workspace-name','Nom',ctx.workspace['name']),action('Renommer','workspace-save',disabled=not admin))],className='settings-profile'),
        card(html.H2('Membres'),table([('name','Membre'),('role','Rôle'),('action','')],rows),
            html.Details([html.Summary('Ajouter un membre'),
                html.Div([
                    html.Section([html.H3('Compte existant'),
                        field('member-email','Adresse e-mail','',kind='email'),
                        field('member-role','Rôle','reader',options=ROLES,searchable=False,maxHeight=240,optionHeight=42),
                        action('Ajouter à l’espace','member-add',disabled=not admin)],className='member-form'),
                    html.Section([html.H3('Nouveau compte'),
                        field('account-name','Nom affiché','',autoComplete='off'),
                        field('account-email','Adresse e-mail','',kind='email',autoComplete='off'),
                        field('account-role','Rôle','reader',options=ROLES,searchable=False,maxHeight=240,optionHeight=42),
                        field('account-password','Mot de passe initial','',kind='password',autoComplete='new-password'),
                        action('Créer et ajouter','account-create',disabled=not admin)],className='member-form')
                ],className='member-forms')]),className='members-card'),
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
    choices=[{'label':p['name'],'value':p['pool_id'],'disabled':not value['can_edit']} for p in items]
    return html.Div([header('Mon périmètre','Choisissez les logiciels suivis par votre équipe SAM.'),
        dcc.Store(id='portfolio-catalog',data=choices),
        dcc.RadioItems(id={'type':'field','key':'portfolio-mode'},value='all' if value['all_catalog'] else 'selected',
            options=[{'label':html.Div([html.Strong('Tout le catalogue'),html.Small('Inclut automatiquement les prochains produits remontés.')]),'value':'all','disabled':not value['can_edit']},
                     {'label':html.Div([html.Strong('Choisir mes logiciels'),html.Small('Une sélection commune aux membres de cet espace.')]),'value':'selected','disabled':not value['can_edit']}],className='portfolio-modes'),
        html.Div(id='portfolio-all-note',children=html.P(f'{len(choices)} produits actuellement disponibles. Les nouveaux produits seront inclus automatiquement.')),
        html.Section([
            html.Div([html.H2('Les logiciels de votre équipe'),html.Strong(id='portfolio-count',role='status')],className='section-heading'),
            html.Div([dcc.Input(id='portfolio-search',type='search',placeholder='Rechercher un produit…',debounce=True),
                html.Button('Tout sélectionner',id='portfolio-select',n_clicks=0,className='button',disabled=not value['can_edit']),
                html.Button('Tout désélectionner',id='portfolio-clear',n_clicks=0,className='button',disabled=not value['can_edit'])],className='portfolio-toolbar'),
            html.Small(id='portfolio-search-count',role='status'),
            dcc.Checklist(id={'type':'field','key':'portfolio-products'},options=choices,value=value['pool_ids'],className='portfolio-products')
        ],id='portfolio-selection',className='card'),
        field('portfolio-version','Version',value['version'],kind='hidden'),
        html.Div([html.Small('Les changements s’appliquent après enregistrement. Les dossiers existants sont conservés.'),
            action('Enregistrer le périmètre','portfolio-save',disabled=not value['can_edit'])],className='portfolio-footer')],className='stack')
