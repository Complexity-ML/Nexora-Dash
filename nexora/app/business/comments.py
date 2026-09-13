"""Project editable comments from an append-only audit journal."""


def project_comments(events):
    comments = {}
    for event in events:
        payload = event['payload']
        if event['action'] == 'case.comment':
            comments[event['id']] = {
                'text': payload.get('text', ''), 'deleted': False, 'version': event['id'],
                'modified_at': None,
            }
        elif event['action'] in ('comment.edited', 'comment.deleted'):
            current = comments.get(payload['comment_id'])
            if current is not None:
                current.update(text=payload.get('text', ''), deleted=event['action'] == 'comment.deleted',
                               version=event['id'], modified_at=str(event['created_at']))
    for event in events:
        if event['id'] in comments:
            event['comment'] = comments[event['id']]
    return events
