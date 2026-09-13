from app.dash_ui.navigation import GROUPS, ICONS, navigation
from app.dash_ui.app import PAGES


def test_every_page_has_one_group_and_icon():
    keys=[key for _,group in GROUPS for key in group]
    assert len(keys)==len(set(keys))
    assert set(keys)==set(PAGES)==set(ICONS)
    tree=navigation(PAGES,'licenses')
    for nav in (tree.children[0], tree.children[1].children[1]):
        links=[link for group in nav.children for link in group.children[1:]]
        assert sum('active' in link.className for link in links)==1
        assert next(link.href for link in links if 'active' in link.className)=='#/licenses'
        assert all(link.children[0].alt=='' for link in links)
