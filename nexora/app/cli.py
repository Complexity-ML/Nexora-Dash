"""One command-line entry point; importing it never connects to the data lake."""
from importlib.util import find_spec
import runpy
import sys

# (command, implementation module, implementation accepts argparse options)
COMMANDS = [
    ('collect run', 'app.commands.collect_daily', True),
    ('collect recover', 'app.commands.recover_collections', True),
    ('collect status', 'app.commands.collection_status', True),
    ('lake compact', 'app.commands.compact_collection', True),
    ('lake retention', 'app.commands.plan_collection_retention', False),
    ('lake prune-index', 'app.commands.prune_inventory_index', True),
    ('lake rebuild-summary', 'app.commands.rebuild_software_summary', False),
    ('lake import', 'app.commands.import_collection_history', True),
    ('bi policy', 'app.commands.bi_s3_policy', True),
    ('bi issue', 'app.commands.issue_bi_reader', True),
    ('bi revoke', 'app.commands.revoke_bi_reader', True),
    ('bi reconcile', 'app.commands.revoke_restored_bi_readers', True),
    ('backup hold', 'app.commands.hold_backup_snapshot', True),
    ('dev demo initialize', 'devtools.demo.initialize_demo', False),
    ('dev demo inventory', 'devtools.demo.seed_enterprise_inventory', True),
    ('dev demo usage', 'devtools.demo.seed_enterprise_product_usage', False),
    ('dev demo analyze', 'devtools.demo.analyze_enterprise_installations', False),
    ('dev demo licenses', 'devtools.demo.complete_demo_licenses', False),
    ('dev demo reindex', 'devtools.demo.reindex_enterprise_inventory', False),
    ('dev verify services', 'devtools.verify.verify_backend', False),
    ('dev verify restore', 'devtools.verify.verify_collection_restore', True),
    ('dev verify pages', 'devtools.verify.verify_dash_pages', False),
    ('dev verify delta', 'devtools.verify.verify_fresh_delta', False),
    ('dev verify tests', 'devtools.verify.test_isolated', False),
    ('dev verify benchmark-bi', 'devtools.verify.benchmark_bi_inventory', True),
    ('dev verify benchmark-reads', 'devtools.verify.benchmark_local_reads', True),
    ('dev migrate activate', 'devtools.migrate.activate_delta', True),
    ('dev migrate cleanup', 'devtools.migrate.cleanup_migrated_demo', True),
    ('dev migrate inventory', 'devtools.migrate.migrate_enterprise_delta', True),
    ('dev migrate pools', 'devtools.migrate.migrate_pool_delta', True),
 ]


def available_commands():
    development = find_spec('devtools') is not None
    return [entry for entry in COMMANDS if development or not entry[0].startswith('dev ')]


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    commands = available_commands()
    if not args or args[-1] in ('-h', '--help'):
        prefix = args[:-1] if args and args[-1] in ('-h','--help') else args
        exact = next((entry for entry in commands if entry[0].split() == prefix), None)
        if exact and exact[2]:
            args = prefix + ['--help']
        else:
            matches = [entry for entry in commands if entry[0].split()[:len(prefix)] == prefix]
            if not matches:
                print('Unknown command. Use nexora --help.', file=sys.stderr)
                return 2
            print('Usage: nexora <command> [options]\n')
            for command, _, _ in matches:
                print('  '+command)
            print('\nUse nexora <command> --help for command options.')
            return 0
    for command, module, accepts_options in commands:
        words = command.split()
        if args[:len(words)] != words:
            continue
        remaining = args[len(words):]
        if remaining and not accepts_options and command != 'dev verify tests':
            print('This command accepts no arguments.',file=sys.stderr)
            return 2
        previous = sys.argv
        try:
            sys.argv = ['nexora '+command, *remaining]
            runpy.run_module(module, run_name='__main__')
        finally:
            sys.argv = previous
        return 0
    print('Unknown command. Use nexora --help.', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
