import datetime as dt
from dateutil.rrule import rrule, DAILY
from dateutil.relativedelta import relativedelta
import configparser
import argparse
import datetime
import cmd
from prettytable import PrettyTable
import logging


# =======================================================================
# Expendo-2 UI command system:
# combine of argument parser to select issues and define parameters
# and command prompt to process data, export results and change parameters
# command interpreter see https://docs.python.org/dev/library/cmd.html
#
# Arguments:
#  - query
#  - (sprint or daily time mode)
#  - (sprint base date)
#  - (sprint length)
#  - (debug mode)
#
# Commands:
#  - [info] - list wellcome prompt
#  - ?/help - list commands help string
#  - set length (int) - change length value
#  - set base (dd.mm.yy) - change base date
#  - set mode ("daily"/"sprint") - change mode value
#  - set period (dd.mm.yy/"week"/"sprint"/"month"/"quarter"/"year"/"all") [to (dd.mm.yy/"today")] - change period values
#  - [dump]/plot/copy/excel ("this"/"estimate"/"spent"/"original"/"burned") [dv] [for {vals}] [at (period)] -
# retrieve data (2-nd group) for period (or use predefined period), make dv/dt (if dv specified), filters and sorts by
# defined vals, sent result to output engine specified in 1st group.
#
# Prompt info:
#  Query text
#  | tasks: count, open, estimate, spent, original, burned
#  | bugs:
#  | total:
#  Settings: Daily for all, Sprint (14 days based 01.01.25) for quarter to 31.12.24
#  Categories:
#  - Queues: MTHW, MTFW, MTPD
#  - Tags: fw, schematic, construction, qa
#  - Components: None
#  - Top Epics: None (top-level Epic ids and names of projects)
#  - Projects: Name (all the projects of queried issues)
#  Enter ? to commands list (i.e. 'plot estimate'), CR to this stat, or Q to quit.


def read_config(filename):
    config = configparser.ConfigParser()
    config.read(filename)
    assert 'token' in config['DEFAULT']
    assert 'org' in config['DEFAULT']
    return config['DEFAULT']


def save_config(filename, **kwargs):
    config = configparser.ConfigParser()
    config['DEFAULT'] = {key: str(value) for key, value in kwargs.items()}
    assert 'token' in config['DEFAULT']
    assert 'org' in config['DEFAULT']
    with open(filename, 'w') as configfile:
        config.write(configfile)


class ExpendoArgumentParser(argparse.ArgumentParser):
    def __init__(self):
        super(ExpendoArgumentParser, self).__init__(
            description='Expendo v.2.0 - Yandex Tracker stat crawler by VCh.',
            epilog='Tracker connection settings and params in "expendo.ini".')
        self.add_argument('query', type=str,
                          help='issues query')
        self.add_argument('-m', '--mode', type=str, choices=['daily', 'sprint'],
                          help='time span mode')
        self.add_argument('--length', type=int,
                          help='sprint length')
        self.add_argument('--base', type=lambda s: dt.datetime.strptime(s, '%d.%m.%y').date(),
                          help='sprint base date')
        self.add_argument('--debug', default=False, action='store_true',
                          help='logging in debug mode (include tracker and issues info)')


def update_args(args, values):
    pass


class ExpendoCmdParser(argparse.ArgumentParser):
    def __init__(self):
        super(ExpendoCmdParser, self).__init__()
