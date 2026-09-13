"""Replay legacy workflow scenarios as direct Python calls (no HTTP server).

The path strings in service_scenarios.json identify historical test cases only.
Production has no dispatcher, REST router, or dependency on this module.
"""
import asyncio
import importlib
import inspect
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from pydantic import BaseModel, TypeAdapter, ValidationError
import httpx
from app.business.errors import BusinessError
from app.business import workspace_service as business, portfolio_service as portfolio
from app.dependencies import get_pipeline


class ScenarioContext:
    def __init__(self): self.dependency_overrides={}


app=ScenarioContext()
SCENARIOS=json.loads(Path(__file__).with_name('service_scenarios.json').read_text())


def encoded(value):
    if isinstance(value,BaseModel): return value.model_dump(mode='json')
    if isinstance(value,list): return [encoded(v) for v in value]
    if isinstance(value,dict): return {k:encoded(v) for k,v in value.items()}
    if hasattr(value,'isoformat'): return value.isoformat()
    return value


class ScenarioClient:
    __test__ = False
    def __init__(self,context=app): self.context=context
    def __enter__(self): return self
    def __exit__(self,*_): pass
    def __getattr__(self,method):
        return lambda path,**kwargs:self.request(method.upper(),path,**kwargs)
    def request(self,method,path,headers=None,json=None,params=None,**_):
        import json as codec
        parsed=urlsplit(path)
        query={k:v[-1] for k,v in parse_qs(parsed.query).items()}
        query.update(params or {})
        try:
            for verb,pattern,module_name,name,status in SCENARIOS:
                matched=re.fullmatch(re.sub(r'\{([^}]+)\}',r'(?P<\1>[^/]+)',pattern),parsed.path)
                if verb!=method or not matched: continue
                module=importlib.import_module(module_name)
                fn=getattr(module,name)
                overrides=self.context.dependency_overrides
                def dependency(provider): return overrides.get(provider,provider)()
                token=(headers or {}).get('Authorization','').removeprefix('Bearer ') or None
                store=dependency(business.get_business_store) if business.get_business_store in overrides or module_name.startswith('app.business') else None
                if name=='login': user=None
                elif business.current_user in overrides: user=dependency(business.current_user)
                else: user=business.current_user(token,store)
                if name in ('sync','generate_demo','reset'):
                    if business.source_operator in overrides: dependency(business.source_operator)
                    else: business.source_operator(user,store)
                args={**matched.groupdict()}
                for key,param in inspect.signature(fn).parameters.items():
                    if key in args:
                        if param.annotation is not inspect.Parameter.empty:
                            args[key]=TypeAdapter(param.annotation).validate_python(args[key])
                        continue
                    if key=='user': args[key]=user
                    elif key=='store': args[key]=store
                    elif key=='pipeline': args[key]=dependency(get_pipeline)
                    elif key=='auth': args[key]=token
                    elif key=='pool_ids':
                        args[key]=(dependency(portfolio.selected_pools) if portfolio.selected_pools in overrides else portfolio.selected_pools(query.get('workspace_id'),user,store))
                    elif key=='body': args[key]=param.annotation.model_validate(json or {})
                    elif key in query:
                        args[key]=TypeAdapter(param.annotation).validate_python(query[key]) if param.annotation is not inspect.Parameter.empty else query[key]
                # Historical request validation, now required at each UI/CLI input boundary.
                if 'limit' in args and not 1<=args['limit']<=100: raise BusinessError(422,'Invalid limit')
                if 'offset' in args and args['offset']<0: raise BusinessError(422,'Invalid offset')
                if 'q' in args and len(args['q'])>200: raise BusinessError(422,'Invalid query')
                result=fn(**args)
                if inspect.isawaitable(result): result=asyncio.run(result)
                return httpx.Response(status,json=encoded(result))
            return httpx.Response(404,json={'detail':'Unknown scenario'})
        except BusinessError as exc: return httpx.Response(exc.status_code,json={'detail':exc.detail})
        except ValidationError as exc: return httpx.Response(422,json={'detail':str(exc)})
