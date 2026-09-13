from app.business.errors import BusinessError
"""Stage, validate and activate a reference demo; retain the old generation."""
import json
import asyncio
from datetime import date, timedelta
from uuid import uuid4
from pydantic import Field
from app.business.workspace_service import Input, current_user, source_operator, get_business_store, member
from app.business.store import now
from app.config import get_settings
from app.storage import S3ParquetStore
from app.services.pipeline import SamPipeline
from app.connectors.digimon import MockDigimonConnector
from app.analytics import SparkAnalytics

REFERENCE_END=date(2026,9,11)

def check_mode():
    if not get_settings().demo_tools_enabled or get_settings().sam_data_source!='mock':
        raise BusinessError(409,'La réinitialisation est réservée au lac fictif.')

def generation(store):
    with store.connect() as db:
        return dict(db.execute('SELECT prefix,version FROM demo_generation WHERE id=1').fetchone())

def verify_reference(summary):
    trends={t.license_pool_id:t for t in summary.trends}
    failures=[]
    expected_dates={str(REFERENCE_END-timedelta(days=i)) for i in range(365)}
    if any({p['date'] for p in t.daily}!=expected_dates for t in summary.trends): failures.append('Dates manquantes ou dupliquées')
    from app.connectors.demo import CATALOG
    if set(trends)!={item[0] for item in CATALOG}: failures.append('Les 12 pools de référence sont attendus')
    if sum(len(t.daily) for t in summary.trends)!=4380: failures.append('4 380 relevés journaliers attendus')
    if any(len(t.daily)!=365 or t.daily[0]['date']!='2025-09-12' or t.daily[-1]['date']!='2026-09-11' for t in summary.trends): failures.append('Période annuelle incomplète')
    for pool in ('flex-cad','flex-catia','flex-maple'):
        if pool not in trends or trends[pool].utilization_rate>=.35: failures.append(pool+' doit être sous-utilisé')
    if trends.get('flex-abaqus') and [trends['flex-abaqus'].daily[i]['capacity'] for i in (0,-1)]!=[350,192]: failures.append('Baisse de capacité Abaqus incorrecte')
    if trends.get('flex-nx') and [trends['flex-nx'].daily[i]['capacity'] for i in (0,-1)]!=[120,192]: failures.append('Hausse de capacité NX incorrecte')
    if not any(r.license_pool_id=='flex-ansys' and r.level=='high' for r in summary.risks): failures.append('Ansys doit être en risque élevé')
    if summary.total_capacity!=6124: failures.append('Capacité totale attendue : 6 124')
    for pool in ('flex-adobe','flex-creo'):
        if pool in trends:
            daily=trends[pool].daily
            early=sum(p['used']/p['capacity'] for p in daily[:30])/30
            late=sum(p['used']/p['capacity'] for p in daily[-30:])/30
            if late-early<.3: failures.append(pool+' : croissance attendue absente')
    for pool in ('flex-solidworks','flex-arcgis','flex-matlab','flex-comsol'):
        if pool in trends:
            groups={}
            for p in trends[pool].daily: groups.setdefault(p['date'][:7],[]).append(p['used']/p['capacity'])
            means=[sum(v)/len(v) for v in groups.values() if len(v)>=28]
            spread=max(means)-min(means)
            if pool in ('flex-solidworks','flex-arcgis') and spread<.25: failures.append(pool+' : variation saisonnière attendue absente')
            if pool in ('flex-matlab','flex-comsol') and spread>.2: failures.append(pool+' : profil stable attendu')
    if failures: raise ValueError('; '.join(failures))
    return {'pools':12,'daily_rows':4380,'capacity':6124,'first_date':'2025-09-12','last_date':'2026-09-11','checks':'passed'}

def preview(user=None,store=None):
    check_mode()
    with store.connect() as db:
        role=db.execute("SELECT role FROM members WHERE workspace_id='demo' AND user_id=%s",(user['id'],)).fetchone()
    return {**generation(store),'can_reset':bool(role and role['role']=='admin'),'days':365,'end_date':str(REFERENCE_END),'pools':12,
            'preserves':['Comptes et membres','Coûts et dossiers','Périmètres des espaces','Anciennes données archivées']}

class Reset(Input):
    version:int=Field(ge=0)
    confirmation:str

def reset(body:Reset,user=None,store=None):
    check_mode()
    if body.confirmation!='REINITIALISER LA DEMO': raise BusinessError(422,'Confirmation explicite requise.')
    previous=generation(store)
    if body.version!=previous['version']: raise BusinessError(409,'La génération active a changé. Rechargez la prévisualisation.')
    settings=get_settings()
    prefix='demo-generations/'+str(uuid4())+'/'
    objects=S3ParquetStore(settings.s3_endpoint_url,settings.s3_access_key,settings.s3_secret_key,settings.s3_bucket,settings.s3_region,prefix)
    # Fixed reference thresholds validate the scenarios, independent of the user's settings.
    staged=SamPipeline(MockDigimonConnector(),objects,SparkAnalytics(settings.spark_master,.35,.1))
    asyncio.run(staged.generate_demo_history(365,REFERENCE_END))
    try:
        report=verify_reference(staged.run_analytics())
    except ValueError as exc:
        raise BusinessError(409,'Validation refusée ; ancien jeu conservé. '+str(exc)) from exc
    # Publish only after validation; a concurrent reset never silently wins.
    with store.connect() as db:
        member(db,'demo',user,admin=True)
        current=db.execute('SELECT prefix,version FROM demo_generation WHERE id=1 FOR UPDATE').fetchone()
        if current['version']!=body.version: raise BusinessError(409,'Une autre réinitialisation a abouti ; rechargez la prévisualisation.')
        db.execute('UPDATE demo_generation SET prefix=%s,version=version+1 WHERE id=1',(prefix,))
        db.execute('INSERT INTO demo_generation_events(actor_id,created_at,payload) VALUES(%s,%s,%s)',(user['id'],now(),json.dumps({'before':dict(current),'after_prefix':prefix,'validation':report})))
    return {'version':body.version+1,'report':report,'previous_data_preserved':True}
