"""Production entry point: Dash/Plotly only."""
from app.dash_ui.app import create_app
app = create_app()
server = app.server
