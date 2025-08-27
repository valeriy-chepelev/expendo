import sys
import logging
from expendo_ui import ExpendoArgumentParser, CmdParser, CommandError
from expendo_ui import read_config, save_config
from data_engine import DataManager
from yandex_tracker_client import TrackerClient
from yandex_tracker_client.exceptions import NotFound, BadRequest


def export_data(engine, data):
    # TODO: exporter
    match engine:
        case 'dump':
            pass
            # dump(data)
        case 'plot':
            pass
        case 'copy':
            pass
        case 'csv':
            pass


def main():

    # Handlers
    def categories_handler():
        nonlocal data_manager
        return data_manager.categories

    def cat_string_handler():
        nonlocal data_manager
        return data_manager.categories_info

    def export_handler(engine):
        nonlocal data_manager
        export_data(engine, data_manager.data)

    def stat_info_handler():
        nonlocal data_manager
        return data_manager.stat_info

    def query_info_handler():
        nonlocal cl_args
        return cl_args.query

    # Init and parse cl arguments

    cl_args = ExpendoArgumentParser().parse_args()

    # Init logging

    logging.basicConfig(filename='expendo2.log',
                        filemode='a',
                        format='%(asctime)s %(name)s %(levelname)s %(message)s',
                        datefmt='%d/%m/%y %H:%M:%S',
                        level=logging.INFO if cl_args.debug else logging.ERROR)
    logging.info('Started with arguments: %s', vars(cl_args))

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
    # TODO: ini args to parser

    # Boot options from cl args
    # TODO: cl args to parser

    # Crate and check Tracker client connection

    client = TrackerClient(cmd_parser.token, cmd_parser.org)
    if client.myself is None:
        raise Exception('Unable to connect Yandex Tracker.')

    # Get Tracker issues

    issues = None  # TODO: issues selector

    # -------------------------------------
    # Init Data Manager
    # -------------------------------------

    data_manager = DataManager(issues)

    # Connect  parser handlers

    cmd_parser.h_period = data_manager.update_period
    cmd_parser.h_recalc = data_manager.recalc
    cmd_parser.h_cats = categories_handler
    cmd_parser.h_cats_str = cat_string_handler
    cmd_parser.h_export = export_handler
    cmd_parser.h_stat_info = stat_info_handler
    cmd_parser.h_query_str = query_info_handler

    # Show info

    pass  # TODO: print info

    # -------------------------------------
    # Main command cycle
    # -------------------------------------

    try:
        while True:
            c = input('>')
            try:
                cmd_parser.parse(c)
            except CommandError as err:
                print('Error:', err.__cause__ if err.__cause__ else err)
    finally:
        save_config('expendo2.ini', **cmd_parser.get_options())

    # ---------------end-------------------


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('Execution error:', e)
        logging.exception(f'Unhandled common error: {e}')
        sys.exit(f'Execution error: {e}')
