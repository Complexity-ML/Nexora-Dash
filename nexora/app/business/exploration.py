"""Bounded, workspace-authorized exploration of the published inventory projection.

The index is rebuildable from the lake. SQL identifiers come exclusively from
this module; user inputs are bound parameters. No raw SQL or lake credentials
are accepted from the browser.
"""
from app.business.errors import BusinessError
from app.business.workspace_service import member
from app.business.portfolio_service import read_portfolio
from app.business.inventory_service import inventory_head

DIMENSIONS={
    'subsidiary':('Filiale','subsidiary',"data->>'subsidiary'",('machines','users','sites')),
    'country':('Pays','country','country',('machines','users','sites')),
    'region':('Région','region','region',('machines','users','sites')),
    'site':('Site','site',"data->>'site'",('machines','users','sites')),
    'os':('Système','os','os',('machines',)),
    'kind':('Type de machine','kind','kind',('machines',)),
    'environment':('Environnement','environment','environment',('machines',)),
    'department':('Département',"data->>'department'","data->>'department'",('users',)),
    'employment_type':('Salariés / prestataires',"data->>'employment_type'","data->>'employment_type'",('users',)),
    'status':('Statut',"data->>'status'","data->>'status'",('users',)),
}
MEASURES={
    'count':('Nombre d’éléments','count(*)',('machines','users','sites')),
    'cpu_cores':('Cœurs inventoriés',"sum((data->>'cpu_cores')::bigint)",('machines',)),
    'memory_gb':('Mémoire inventoriée (Go)',"sum((data->>'memory_gb')::bigint)",('machines',)),
}


def selection(db,store,wid,user,entity,filters,query=''):
    member(db,wid,user)
    if entity not in ('machines','users','sites'): raise BusinessError(422,'Entité inconnue.')
    if len(query)>200: raise BusinessError(422,'Recherche trop longue.')
    head=inventory_head(db,store)
    if not head: raise BusinessError(409,'La projection d’exploration doit être construite depuis le lac.')
    portfolio=read_portfolio(db,wid)
    conditions=['run_id=%s','entity=%s']; params=[head['run_id'],entity]
    if not portfolio['all_catalog']:
        conditions.append('pool_ids && %s::text[]');params.append(portfolio['pool_ids'])
    for key,value in filters.items():
        if key not in DIMENSIONS or entity not in DIMENSIONS[key][3]: raise BusinessError(422,'Filtre incompatible avec cette vue.')
        expr=DIMENSIONS[key][1]
        if value is None: conditions.append(expr+' IS NULL')
        else: conditions.append(expr+'=%s');params.append(str(value))
    if query: conditions.append('strpos(search,%s)>0');params.append(query.casefold())
    return head,' AND '.join(conditions),params


def aggregate(wid,*,entity='machines',dimension='subsidiary',split=None,measure='count',filters=None,query='',offset=0,limit=50,user,store,pipeline):
    dimensions=[dimension]+([split] if split and split!=dimension else [])
    if any(d not in DIMENSIONS or entity not in DIMENSIONS[d][3] for d in dimensions): raise BusinessError(422,'Dimension incompatible.')
    if measure not in MEASURES or entity not in MEASURES[measure][2]: raise BusinessError(422,'Mesure incompatible.')
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100: raise BusinessError(422,'Pagination invalide.')
    with store.connect() as db:
        head,where,params=selection(db,pipeline.store,wid,user,entity,filters or {},query)
        columns=[];groups=[]
        for i,d in enumerate(dimensions):
            expr,label=DIMENSIONS[d][1:3]
            columns.extend([f'{expr} AS key{i}',f'min({label}) AS label{i}'])
            groups.append(expr)
        metric=MEASURES[measure][1]
        sql=f"SELECT {','.join(columns)}, {metric} AS value,count(*) AS records,count(*) OVER() AS groups FROM inventory_entities WHERE {where} GROUP BY {','.join(groups)} ORDER BY value DESC NULLS LAST,{','.join(groups)} NULLS LAST LIMIT %s OFFSET %s"
        rows=[dict(r) for r in db.execute(sql,[*params,limit,offset])]
        totals=db.execute(f'SELECT count(*) AS records,{metric} AS value FROM inventory_entities WHERE {where}',params).fetchone()
        return {'run_id':head['run_id'],'captured_at':head['captured_at'],'source':head['source'],
                'rows':rows,'groups':rows[0]['groups'] if rows else 0,'records':totals['records'],'value':totals['value'],
                'dimensions':dimensions,'measure':measure}


def records(wid,*,entity='machines',filters=None,query='',offset=0,limit=25,user,store,pipeline):
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=100: raise BusinessError(422,'Pagination invalide.')
    with store.connect() as db:
        head,where,params=selection(db,pipeline.store,wid,user,entity,filters or {},query)
        total=db.execute(f'SELECT count(*) AS n FROM inventory_entities WHERE {where}',params).fetchone()['n']
        rows=[dict(r) for r in db.execute(f"SELECT id,name,data->>'subsidiary' AS subsidiary,data->>'site' AS site,os FROM inventory_entities WHERE {where} ORDER BY name,id LIMIT %s OFFSET %s",[*params,limit,offset])]
        return {'rows':rows,'total':total,'run_id':head['run_id']}


def completeness(wid,*,entity='machines',user,store,pipeline):
    with store.connect() as db:
        head,where,params=selection(db,pipeline.store,wid,user,entity,{})
        checks=[(key,value) for key,value in DIMENSIONS.items() if entity in value[3]]
        terms=[f"count(*) FILTER(WHERE {value[1]} IS NULL OR {value[1]}='') AS {key}" for key,value in checks]
        result=dict(db.execute(f"SELECT count(*) AS total,{','.join(terms)} FROM inventory_entities WHERE {where}",params).fetchone())
        return {'run_id':head['run_id'],'total':result['total'],'fields':[{'name':value[0],'missing':result[key]} for key,value in checks]}
