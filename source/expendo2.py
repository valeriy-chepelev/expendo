import sys
import logging
from expendo_ui import ExpendoArgumentParser, CmdParser, CommandError
from expendo_ui import read_config, save_config
from data_engine import DataManager, issue_times, _cache_info
from yandex_tracker_client import TrackerClient
from alive_progress import alive_bar
from exporters import dump, plot, csv
from root_finder import TreeCache
from colorama import init as init_color


def export_data(engine, data, segments=None, nom_velocity=8.0):
    match engine:
        case 'dump':
            dump(data, segments, nom_velocity)
        case 'plot':
            plot(data, segments, nom_velocity)
        case 'copy':
            csv(data, segments, nom_velocity)


def main():
    # Handlers
    def categories_handler():
        nonlocal data_manager
        return data_manager.categories

    def cat_string_handler():
        nonlocal data_manager
        return data_manager.categories_info

    def export_handler(engine, velocity):
        nonlocal data_manager
        export_data(engine, data_manager.data, data_manager.segments, velocity)

    def stat_info_handler():
        nonlocal data_manager
        return data_manager.stat_info

    # Init and parse cl arguments

    cl_args = ExpendoArgumentParser().parse_args()

    # Init logging

    logging.basicConfig(filename='expendo2.log',
                        filemode='a',
                        format='%(asctime)s %(name)s %(levelname)s %(message)s',
                        datefmt='%d/%m/%y %H:%M:%S',
                        level=logging.DEBUG if cl_args.debug else logging.ERROR)
    logging.info('Started with arguments: %s', vars(cl_args))

    init_color(autoreset=True)

    # load ini-file

    ini_args = dict()
    try:
        ini_args = read_config('expendo2.ini')
    except FileNotFoundError:
        pass

    # -------------------------------------
    # Init CmdParser
    # -------------------------------------

    cmd_parser = CmdParser()

    # Boot options from ini

    cmd_parser.options.set_values(**ini_args)

    # Boot options from cl args

    cmd_parser.options.set_values(**cl_args.__dict__)

    # Crate and check Tracker client connection

    print('Connecting to Tracker...')

    client = TrackerClient(cmd_parser.options.token, cmd_parser.options.org)
    if client.myself is None:
        raise Exception('Unable to connect Yandex Tracker.')

    # Get Tracker issues

    print(f'Executing query "{cmd_parser.options.query}"...')

    if cmd_parser.options.query == '':
        raise Exception('Empty issues query.')
    issues = list(client.issues.find(query=cmd_parser.options.query))

    # precache issues

    with alive_bar(len(issues), title='Caching issues data', theme='classic') as bar:
        for issue in issues:
            issue_times(issue)
            bar()

    tree = TreeCache()
    with alive_bar(len(issues), title='Searching root epics', theme='classic') as bar:
        for issue in issues:
            tree.add(issue)
            bar()

    # -------------------------------------
    # Init Data Manager
    # -------------------------------------

    data_manager = DataManager(issues, tree.roots)

    # Connect  parser handlers

    cmd_parser.h_period = data_manager.update_period
    cmd_parser.h_recalc = data_manager.recalc
    cmd_parser.h_trends = data_manager.update_segments
    cmd_parser.h_cats = categories_handler
    cmd_parser.h_cats_str = cat_string_handler
    cmd_parser.h_export = export_handler
    cmd_parser.h_stat_info = stat_info_handler

    # -------------------------------------
    # Main command cycle
    # -------------------------------------

    try:
        c = ''  # Show info as first
        while True:
            try:
                cmd_parser.parse(c)
                c = input('>')
            except CommandError as err:
                c = 'simpleinfointernal'  # Show prompt if error
                print('Error:', err.__cause__ if err.__cause__ else err)
    finally:
        save_config('expendo2.ini', **cmd_parser.options.get_values_str())
        _cache_info()

    # ---------------end-------------------


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('Execution error:', e)
        logging.exception(f'Unhandled common error: {e}')
        sys.exit(f'Execution error: {e}')
