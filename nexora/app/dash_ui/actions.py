"""Explicit callback commands. No URL dispatch and no HTTP client to the backend."""
from decimal import Decimal, InvalidOperation
from flask import session
from app.business import workspace_service as business, portfolio_service as portfolio, settings_service as settings
from app.business.errors import BusinessError
from app.dash_ui.context import current_context, business_store, authenticated_user
from app.dash_ui.components import route


def cents(value):
    if value is None or value=='': return None
    result=Decimal(str(value))*100
    if not result.is_finite() or result<0 or result!=result.to_integral_value():
        raise BusinessError(422,'Saisissez un montant positif avec au plus deux décimales.')
    return int(result)


def execute(name, values):
    if name=='login':
        store=business_store()
        result=business.login(business.Login(email=values.get('email') or '',password=values.get('password') or ''),store)
        session.clear()
        session['token']=result['token']
        return 'Connexion établie.',route('overview')
    if name in ('logout','workspace-create'):
        user,store=authenticated_user()
        if name=='logout':
            business.logout(session['token'],user,store)
            session.clear()
            return 'Déconnecté.',route('overview')
        result=business.create_workspace(business.Name(name=values['new-workspace']),user,store)
        session['workspace']=result['id']
        return 'Espace créé. Sélectionnez son périmètre.',route('portfolio')
    ctx=current_context()
    if name=='refresh': return 'Résultats actualisés.',None
    if name=='workspace-save':
        ctx.call(business.rename_workspace,ctx.wid,business.Name(name=values['workspace-name']))
    elif name=='profile-save': ctx.call(business.rename_user,business.Name(name=values['profile-name']))
    elif name in ('member-add','account-create') or name.startswith('member-save:'):
        suffix=':'+name.split(':',1)[1] if name.startswith('member-save:') else ''
        prefix='account' if name=='account-create' else 'member'
        data=dict(email=values[prefix+'-email'+suffix],role=values[prefix+'-role'+suffix])
        if name=='account-create':
            ctx.call(business.create_account,ctx.wid,business.AccountCreate(**data,name=values['account-name'],password=values['account-password']))
        else: ctx.call(business.set_member,ctx.wid,business.Member(**data))
    elif name.startswith('member-remove:'):
        uid=name.split(':',1)[1]
        ctx.call(business.remove_member,ctx.wid,uid,business.MemberRemoval(expected_role=values['member-original:'+uid]))
    elif name=='settings-save':
        ctx.call(settings.update,settings.Update(threshold=Decimal(str(values['threshold']))/100,buffer=Decimal(str(values['reserve']))/100,version=values['settings-version']))
        return 'Seuils enregistrés pour le prochain traitement.',None
    elif name=='portfolio-save':
        all_catalog=values['portfolio-mode']=='all'
        ctx.call(portfolio.update_portfolio,ctx.wid,portfolio.PortfolioUpdate(all_catalog=all_catalog,pool_ids=[] if all_catalog else (values.get('portfolio-products') or []),version=values['portfolio-version']),lake=True)
    elif name.startswith('cost:'):
        key=name.split(':',1)[1]
        ctx.call(business.save_cost,ctx.wid,key,business.CostUpdate(version=values['cost-version:'+key],annual_unit_cents=cents(values['cost:'+key])))
    elif name=='case-create':
        from app.dash_ui.pages.software import products
        product=next((p for p in products(ctx,False) if (p.get('license_pool_id') or p['software_id'])==values['case-product']),None)
        if not product: raise BusinessError(422,'Sélectionnez un produit de votre périmètre.')
        result=ctx.call(business.create_case,ctx.wid,business.CaseCreate(pool_id=values['case-product'],title=values.get('case-title') or 'Examen '+product['name'],quantity=values['case-quantity'],evidence=values['case-evidence']))
        return 'Dossier créé.',route('cases',id=result['id'])
    elif name=='case-update':
        ctx.call(business.update_case,ctx.wid,values['case-id'],business.CaseUpdate(version=values['case-version'],assignee_id=values.get('case-assignee') or None,quantity=values['case-quantity'],annual_unit_cents=cents(values['case-cost']) or 0))
    elif name=='case-progress':
        closing=values['case-status']=='completed'
        outcome=values.get('case-outcome') if closing else None
        ctx.call(business.progress,ctx.wid,values['case-id'],business.Progress(version=values['case-version'],status=values['case-status'],reason=values['case-reason'],outcome=outcome,actual_quantity=values.get('case-actual') if outcome=='recovered' else None))
    elif name=='case-delete':
        ctx.call(business.delete_case,ctx.wid,values['case-id'],business.CaseDelete(version=values['case-version']))
        return 'Dossier supprimé.',route('cases')
    elif name=='note-create':
        ctx.call(business.comment,ctx.wid,values['case-id'],business.Comment(text=values['new-note']))
    elif name.startswith('note-edit:') or name.startswith('note-delete:'):
        eid=name.split(':',1)[1]
        if name.startswith('note-edit:'):
            ctx.call(business.edit_comment,ctx.wid,values['case-id'],int(eid),business.CommentEdit(version=values['note-version:'+eid],text=values['note-text:'+eid]))
        else: ctx.call(business.delete_comment,ctx.wid,values['case-id'],int(eid),business.CommentRevision(version=values['note-version:'+eid]))
    else: raise BusinessError(400,'Action inconnue.')
    return 'Enregistré.',None
