"""Test-only notation for exercising the BI reader without a web transport."""
from urllib.parse import urlsplit,parse_qs
import httpx
from app.bi import reader_service
from app.business.errors import BusinessError

class ReaderClient:
    def get(self,url,headers=None):
        path=urlsplit(url)
        token=(headers or {}).get('Authorization','').removeprefix('Bearer ') or None
        query=parse_qs(path.query)
        try:
            if path.path.endswith('/publication'):
                value=reader_service.current_publication(token)
            else:
                table={'pool-usage.csv':'pool_usage','inventory-counts.csv':'inventory_counts','license-entitlements.csv':'license_entitlements'}.get(path.path.split('/')[-1])
                value=reader_service.read_snapshot(query.get('snapshot_id',[None])[0],token,table)
            if isinstance(value,reader_service.Export):
                return httpx.Response(200,content=value.content,headers={'Cache-Control':'no-store','X-Nexora-Snapshot-ID':value.snapshot_id,'X-Nexora-Content-SHA256':value.checksum})
            return httpx.Response(200,json=value,headers={'Cache-Control':'no-store'})
        except BusinessError as exc:
            return httpx.Response(exc.status_code,json={'detail':exc.detail},headers={'Cache-Control':'no-store',**({'WWW-Authenticate':'Bearer'} if exc.status_code==401 else {})})
