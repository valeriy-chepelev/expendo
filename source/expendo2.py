import sys
import logging
from expendo_ui import ExpendoArgumentParser, CmdParser, CommandError
from expendo_ui import read_config, save_config


class DataManager:  # TODO: DataManager Class, here is placeholder stub
    def __init__(self, *args):
        pass


data_manager = DataManager()


def export_handler(*args, **kwargs):
    engine = kwargs.get('engine', 'dump')
    title = kwargs.get('data', '')
    match engine:
        case 'dump':
            pass  # dump(title, data_manager.data())
        case 'plot':
            pass
        case 'copy':
            pass
        case 'csv':
            pass


def main():
    args = ExpendoArgumentParser().parse_args()
    logging.basicConfig(filename='expendo2.log',
                        filemode='a',
                        format='%(asctime)s %(name)s %(levelname)s %(message)s',
                        datefmt='%d/%m/%y %H:%M:%S',
                        level=logging.INFO if args.debug else logging.ERROR)
    logging.info('Started with arguments: %s', vars(args))
    cmd_parser = CmdParser()
    # Connect handlers
    # TODO: parser handlers
    cmd_parser.h_export = export_handler
    # Main command cycle
    while True:
        c = input('>')
        try:
            # cmd_parser.cat_list = data_manager.cat_list
            cmd_parser.parse(c)
        except CommandError as err:
            print('Error:', err.__cause__ if err.__cause__ else err)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('Execution error:', e)
        logging.exception(f'Unhandled common error: {e}')
        sys.exit(f'Execution error: {e}')
