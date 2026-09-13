"""Grouped navigation and local vector icons for the Dash shell."""
from urllib.parse import quote
from dash import html, dcc
from app.dash_ui.components import route

GROUPS=[('Pilotage',('overview','software','inventory','annual','licenses','flexlm','savings','cases')),
        ('Data Platform',('explore','quality','lake')),
        ('Espace de travail',('portfolio','settings','help'))]
ICONS={
    'overview':'<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 9v12"/>',
    'software':'<path d="m12 3 9 5-9 5-9-5zm-9 5v9l9 5 9-5V8M12 13v9"/>',
    'inventory':'<rect x="3" y="3" width="18" height="13" rx="2"/><path d="M8 21h8M12 16v5"/>',
    'annual':'<path d="M3 3v18h18M7 15l5-7 4 4 5-8"/>',
    'licenses':'<path d="m12 3 10 5-10 5L2 8zm-10 9 10 5 10-5M2 16l10 5 10-5"/>',
    'flexlm':'<path d="M3 18a10 10 0 1 1 18 0M12 13l5-6"/><circle cx="12" cy="13" r="1"/>',
    'savings':'<circle cx="12" cy="12" r="9"/><path d="M15 7H9v5h6v5H9M12 5v14"/>',
    'cases':'<path d="M3 7h7l2 2h9v11H3zM3 7V4h7l2 3"/>',
    'explore':'<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6M10 7v6M7 10h6"/>',
    'quality':'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zm-4 9 3 3 5-6"/>',
    'lake':'<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 4 18 4 18 0V5M3 12c0 4 18 4 18 0"/>',
    'portfolio':'<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V3h8v4M3 12h18M10 12v3h4v-3"/>',
    'settings':'<circle cx="12" cy="12" r="3"/><path d="m9 3-1 3-3 1-2 3 2 2-1 3 3 2 1 3h4l2-3 3-1 2-3-2-2 1-3-3-2-1-3z"/>',
    'help':'<circle cx="12" cy="12" r="9"/><path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 5M12 17h.01"/>',
}


def navigation(pages,active):
    groups=[]
    for title,keys in GROUPS:
        links=[]
        for key in keys:
            svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#b9cbd9" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'+ICONS[key]+'</svg>'
            links.append(dcc.Link([html.Img(src='data:image/svg+xml,'+quote(svg),alt='',className='nav-icon'),html.Span(pages[key][0])],
                href=route(key),className='nav-item active' if key==active else 'nav-item'))
        groups.append(html.Section([html.H2(title,className='nav-heading'),*links],className='nav-group'))
    return html.Nav(groups,**{'aria-label':'Navigation principale'})
