"""Read-only smoke check of Dash layouts against the configured demo lake."""
import json
import os
from flask import session
from plotly.utils import PlotlyJSONEncoder
from app.dash_ui.app import create_app,PAGES
from app.business import workspace_service as business


def main():
    app=create_app(testing=True)
    store=business.get_business_store()
    result=business.login(business.Login(email='admin@sam.demo',password=os.environ['SAM_DEMO_PASSWORD']),store)
    token=result['token']
    try:
        render=app.callback_map['shell.children']['callback'].__wrapped__
        with app.server.test_request_context('/'):
            session['token']=token
            for page in PAGES:
                tree=render('#/'+page,0)
                output=json.dumps(tree,cls=PlotlyJSONEncoder)
                if 'Lecture indisponible' in output or 'Connectez-vous' in output:
                    raise AssertionError('Page failed: '+page)
                print(page,len(output),'bytes')
    finally:
        business.logout(token,result['user'],store)

if __name__=='__main__': main()
