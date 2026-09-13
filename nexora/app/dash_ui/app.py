"""Dash web entry point. Calls Python services, never Nexora REST endpoints."""
import logging
import os
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from dash import Dash, html, dcc, Input, Output, State, ALL, ctx as trigger, no_update
from dash.exceptions import PreventUpdate
from flask import Flask, request, session, abort
from pydantic import ValidationError
from app.business.errors import BusinessError
from app.dash_ui.context import current_context
from app.dash_ui.components import action, field, empty, route
from app.dash_ui.actions import execute
from app.dash_ui.pages import overview, inventory, software, analysis, cases, settings, lake, explore

PAGES={'explore':('Exploration',explore.layout),'quality':('Qualité',explore.quality),'overview':('Vue d’ensemble',overview.layout),'inventory':('Inventaire',inventory.layout),
    'software':('Parc logiciel',software.layout),'licenses':('Licences',software.licenses),
    'annual':('Analyse annuelle',analysis.annual),'flexlm':('Pools',analysis.pools),
    'savings':('Coûts & économies',analysis.savings),'cases':('Dossiers',cases.layout),
    'portfolio':('Mon périmètre',settings.portfolio_page),'lake':('Data Lake',lake.layout),
    'settings':('Paramètres',settings.layout),'help':('Guide',lake.help_page)}


def secret_key():
    configured=os.environ.get('DASH_SECRET_KEY')
    if configured:
        if len(configured)<32: raise RuntimeError('DASH_SECRET_KEY requires at least 32 characters')
        return configured
    path=Path(os.environ.get('DASH_SECRET_FILE','/var/lib/nexora/session.key'))
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        temporary=path.with_name('.session-'+secrets.token_hex(12))
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'w') as output:
                output.write(secrets.token_urlsafe(48)); output.flush(); os.fsync(output.fileno())
            try: os.link(temporary,path)
            except FileExistsError: pass
        finally: temporary.unlink()
    value=path.read_text().strip()
    if len(value)<32: raise RuntimeError('Invalid Dash session key')
    return value


def parse_location(location):
    parsed=urlsplit((location or '#/overview').removeprefix('#'))
    page=parsed.path.strip('/') or 'overview'
    return page,{k:v[-1] for k,v in parse_qs(parsed.query).items()}


def login_layout():
    return html.Div([html.Div('nexora',className='login-brand'),html.H1('Votre espace d’analyse'),
        html.P('Explorez le parc et ses usages dans la durée.'),
        field('email','Adresse e-mail','',kind='email'),field('password','Mot de passe','',kind='password'),
        action('Se connecter','login')],className='login card')


def create_app(*, testing=False, store=None):
    server=Flask(__name__)
    server.config.update(SECRET_KEY='isolated-dash-test-key-not-for-deployment' if testing else secret_key(),
        TESTING=testing,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('DASH_COOKIE_SECURE','false').lower()=='true',
        MAX_CONTENT_LENGTH=1024*1024)
    if store is not None:
        if not testing: raise ValueError('Store injection is reserved for tests')
        server.config['NEXORA_BUSINESS_STORE']=store
    app=Dash(__name__,server=server,assets_folder=str(Path(__file__).parent/'assets'),
        suppress_callback_exceptions=True,title='Nexora — Analyse du parc',update_title=None)

    @server.before_request
    def protect_callbacks():
        # Dash uses cookies. Reject cross-origin commands, including login CSRF.
        if request.method=='POST':
            origin=request.headers.get('Origin','')
            if origin.rstrip('/') != request.host_url.rstrip('/'):
                abort(403)

    @server.after_request
    def response_headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        if not request.path.startswith('/assets/'):
            response.headers['Cache-Control']='no-store'
        return response

    app.layout=html.Div([dcc.Location(id='location',refresh=False),dcc.Store(id='revision',data=0),
        dcc.Download(id='download'),html.Div(id='shell'),html.Div(id='message',role='status',className='toast')])

    @app.callback(Output('shell','children'),Input('location','hash'),Input('revision','data'))
    def render(location,revision):
        try: context=current_context()
        except BusinessError as exc:
            if exc.status_code==401: return login_layout()
            # Access may have been revoked since the last request; choose an accessible space.
            session.pop('workspace',None)
            try:context=current_context()
            except BusinessError as retry:
                if retry.status_code==401:return login_layout()
                if retry.status_code!=404:raise
                return html.Div([html.H1('Votre espace d’analyse'),
                    html.P('Vous n’avez pas encore d’espace accessible. Créez-en un ou demandez à votre équipe de vous ajouter.'),
                    field('new-workspace','Nom de l’espace',''),action('Créer mon espace','workspace-create'),
                    action('Se déconnecter','logout')],className='login card')
        page,query=parse_location(location)
        if page not in PAGES: page='overview'
        try: content=PAGES[page][1](context,query)
        except BusinessError as exc: content=empty(exc.detail)
        except Exception:
            logging.exception('Dash page failed: %s',page)
            content=empty('Lecture indisponible. Réessayez avec Actualiser ; aucune donnée n’a été modifiée.')
        nav=[]
        for key,(label,_) in PAGES.items():
            nav.append(dcc.Link(label,href=route(key),className='nav-item active' if key==page else 'nav-item'))
        return html.Div([
            html.Aside([html.Div([html.Strong('nexora'),html.Span('SAM',className='badge')],className='brand'),
                html.Label('ESPACE DE TRAVAIL',className='eyebrow'),
                dcc.Dropdown(id='workspace-picker',options=[{'label':w['name'],'value':w['id']} for w in context.spaces],value=context.wid,clearable=False),
                html.Nav(nav),html.Div([html.Strong(context.user['name']),action('Se déconnecter','logout')],className='sidebar-footer')],className='sidebar'),
            html.Main([html.Div([html.Span('DÉMONSTRATION · Données fictives' if os.environ.get('SAM_DATA_SOURCE','mock')=='mock' else 'Source : DIGIMON'),
                                 action('Actualiser','refresh')],className='topbar'),
                dcc.Loading(html.Div(content,id='page-content'),delay_show=350,type='dot',overlay_style={'visibility':'visible','opacity':.65})],className='main')],className='app-shell')

    @app.callback(Output('download','data'),Output('message','children',allow_duplicate=True),
        Input({'type':'export-case','id':ALL},'n_clicks'),State({'type':'export-case','id':ALL},'id'),prevent_initial_call=True)
    def download_case(clicks,identifiers):
        identifier=trigger.triggered_id
        if identifier not in identifiers or not clicks[identifiers.index(identifier)]:raise PreventUpdate
        try:
            from app.business import workspace_service
            context=current_context()
            exported=context.call(workspace_service.export_case,context.wid,identifier['id'])
            return {'content':exported['content'],'filename':exported['filename'],'type':'text/html','base64':False},'Dossier exporté.'
        except BusinessError as exc:return no_update,exc.detail

    @app.callback(Output('revision','data',allow_duplicate=True),Input('workspace-picker','value'),State('revision','data'),prevent_initial_call=True)
    def choose_workspace(value,revision):
        context=current_context(value)
        if session.get('workspace')==context.wid: raise PreventUpdate
        session['workspace']=context.wid
        return (revision or 0)+1

    @app.callback(Output('message','children'),Output('revision','data'),Output('location','hash',allow_duplicate=True),
        Input({'type':'action','name':ALL},'n_clicks'),State({'type':'action','name':ALL},'id'),
        State({'type':'field','key':ALL},'value'),State({'type':'field','key':ALL},'id'),State('revision','data'),prevent_initial_call=True)
    def command(clicks,ids,values,keys,revision):
        identifier=trigger.triggered_id
        if not identifier or identifier not in ids or not clicks[ids.index(identifier)]: raise PreventUpdate
        try:
            message,location=execute(identifier['name'],{key['key']:value for key,value in zip(keys,values)})
            return message,(revision or 0)+1,location or no_update
        except BusinessError as exc: return exc.detail,no_update,no_update
        except (ValidationError,ValueError,TypeError,KeyError): return 'Vérifiez les champs du formulaire.',no_update,no_update
        except Exception:
            logging.exception('Dash command failed: %s',identifier['name'])
            return 'Action non confirmée. Actualisez avant de réessayer.',no_update,no_update

    @app.callback(Output('location','hash',allow_duplicate=True),Input({'type':'filter','key':ALL},'value'),
        State({'type':'filter','key':ALL},'id'),State('location','hash'),prevent_initial_call=True)
    def filters(values,keys,location):
        page,query=parse_location(location)
        updates={key['key']:value for key,value in zip(keys,values)}
        if all(str(query.get(k,''))==str(v or '') for k,v in updates.items()): raise PreventUpdate
        query.update(updates); query.pop('offset',None)
        return route(page,**query)
    @app.callback(Output('location','hash',allow_duplicate=True),Input('exploration-chart','clickData'),State('location','hash'),prevent_initial_call=True)
    def drilldown(click,location):
        if not click or not click.get('points'): raise PreventUpdate
        page,query=parse_location(location)
        if page!='explore': raise PreventUpdate
        chosen=click['points'][0].get('customdata')
        if not isinstance(chosen,str): raise PreventUpdate
        query.update(selection=chosen,view='records'); query.pop('offset',None)
        return route('explore',**query)
    @app.callback(Output('location','hash',allow_duplicate=True),Input({'type':'insight-chart','key':ALL},'clickData'),State({'type':'insight-chart','key':ALL},'id'),prevent_initial_call=True)
    def open_chart_selection(clicks,ids):
        selected=next((value for value,identifier in zip(clicks,ids) if identifier==trigger.triggered_id),None)
        if not isinstance(selected,dict) or not selected.get('points'):raise PreventUpdate
        target=selected['points'][0].get('customdata')
        if not isinstance(target,str) or not target.startswith('#/'):raise PreventUpdate
        page,_=parse_location(target)
        if page not in ('software','savings','licenses','explore'):raise PreventUpdate
        return target
    return app


def main():
    create_app().run(host='0.0.0.0',port=int(os.environ.get('PORT',8050)),debug=False)


if __name__=='__main__': main()
