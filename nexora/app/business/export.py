"""Self-contained printable dossier; all user-provided values are HTML-escaped."""
from html import escape

LABELS = {'preparing':'À examiner','in_progress':'En cours','sent':'En cours','response_received':'En cours','completed':'Terminé',
          'accepted':'Accord externe','refused':'Refus externe','revision_requested':'Compléments demandés'}

def dossier_html(case, workspace, exported_at):
    def safe(value): return escape(str(value)) if value is not None else 'Non renseigné'
    rows = [('Espace',workspace),('Identifiant',case['id']),('Logiciel / pool',case['pool_id']),
            ('État',LABELS[case['status']]),('Ancien état interne (sans valeur de validation externe)',case.get('legacy_status')),('Version',case['version']),('Responsable',case.get('assignee_name')),
            ('Quantité proposée',case['quantity']),('Coût annuel unitaire (€)',f"{case['annual_unit_cents']/100:.2f}"),
            ('Hypothèse annuelle (€)',f"{case['quantity']*case['annual_unit_cents']/100:.2f}"),
            ('Dernière référence externe',case['document_reference']),('Date de transmission',case['sent_on']),
            ('Décision reçue',LABELS.get(case['external_decision'])),('Date du retour',case['responded_on']),
            ('Date d’action déclarée',case['completed_on']),('Quantité réalisée déclarée',case['actual_quantity'])]
    rows = [(label, value) for label, value in rows if value is not None]
    table=''.join(f'<tr><th>{safe(label)}</th><td>{safe(value)}</td></tr>' for label,value in rows)
    actions = {'case.created':'Dossier créé','case.updated':'Dossier modifié','case.unassigned':'Assignation retirée','case.transition':'Changement d’état'}
    journal = ''.join(
        f"<li><strong>{safe(event['actor_name'])}</strong> · {safe(event['created_at'])}<p>{safe(actions[event['action']])}</p><p>{safe(event['payload'].get('reason', ''))}</p></li>"
        for event in case['events'] if event['action'] in actions)
    comments = ''.join(
        f"<li><strong>{safe(event['actor_name'])}</strong> : {safe(event['comment']['text'])}</li>"
        for event in case['events'] if event.get('comment') and not event['comment']['deleted'])
    return f'''<!doctype html><html lang="fr"><meta charset="utf-8"><title>{safe(case['title'])}</title>
<style>body{{font:15px system-ui;color:#182030;max-width:850px;margin:40px auto;padding:20px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:8px;text-align:left}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}}h1{{font-size:26px}}@media print{{body{{margin:0}}tr{{break-inside:avoid}}}}</style>
<h1>{safe(case['title'])}</h1><p>SAM · Dossier de démonstration · données fictives</p>
<p>Export du {safe(exported_at)}. Les quantités récupérées sont déclaratives. Les montants sont des estimations.</p>
<table>{table}</table><h2>Éléments d’analyse</h2><p>{safe(case['evidence'])}</p>
<h2>Notes</h2><ul>{comments}</ul>
<h2>Suivi du dossier</h2><ol>{journal}</ol></html>'''
