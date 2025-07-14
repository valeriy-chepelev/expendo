import datetime as dt
import sys

from dateutil.rrule import rrule, DAILY
from dateutil.relativedelta import relativedelta
import configparser
import argparse
from argparse import ArgumentError
import shlex
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


def _check_len_range(val):
    i = int(val)
    if i < 2 or i > 30:
        raise ArgumentError('Sprint length expected 2 to 30 days.')
    return i


class ExpendoArgumentParser(argparse.ArgumentParser):
    def __init__(self):
        super(ExpendoArgumentParser, self).__init__(
            description='Expendo v.2.0 - Yandex Tracker stat crawler by VCh.',
            epilog='Tracker connection settings and params in "expendo.ini".')
        self.add_argument('query', type=str, nargs='?', default=None,
                          help='issues query, default last call query')
        self.add_argument('-m', '--mode', type=str, choices=['daily', 'sprint'],
                          help='time span mode')
        self.add_argument('--length', type=_check_len_range,
                          help='sprint length')
        self.add_argument('--base', type=lambda s: dt.datetime.strptime(s, '%d.%m.%y').date(),
                          help='sprint base date [dd.mm.yy]')

        self.add_argument('--period', type=str,
                          choices=["custom", "week", "sprint", "month", "quarter", "year", "all"],
                          help='data period')
        self.add_argument('--from', type=lambda s: dt.datetime.strptime(s, '%d.%m.%y').date(),
                          help='custom data period start date [dd.mm.yy]')

        self.add_argument('--to', type=lambda s: dt.datetime.strptime(s, '%d.%m.%y').date(),
                          help='data period final date [dd.mm.yy]')
        self.add_argument('-f', '--freeze', default=False, action='store_true',
                          help='freeze stored data period final date (not up today)')

        self.add_argument('--token', type=str,
                          help='Tracker access token')
        self.add_argument('--org', type=str,
                          help='Tracker organisation id')
        self.add_argument('--debug', default=False, action='store_true',
                          help='logging in debug mode (include tracker and issues info)')


def update_args(args, values):
    pass


# ---------------------------------------------------------
#                      CLI commands parser
# ---------------------------------------------------------


set_tokens = ['mode', 'length', 'base', 'period']
ctrl_tokens = ['info', 'help', '?', 'h', 'quit', 'exit']
engine_tokens = ['dump', 'plot', 'copy', 'csv']
data_tokens = ['estimate', 'spent', 'original', 'burn']
dv_tokens = ['dv']
filter_tokens = ['for']
mode_tokens = ['daily', 'sprint']
period_tokens = ['week', 'sprint', 'month', 'quarter', 'year', 'all', 'full']
period_bound_tokens = ['to']
local_period_tokens = ['at', 'to']
match_tolerance = 0.8

help_str = ("General control commands:\n"
            "  help, ?, h - this description\n"
            "  quit, exit - quits\n"
            "  info or just Enter - common stat and settings info\n"
            "Global settings commands (stored to .ini):\n"
            "  mode sprint|daily - set time mode\n"
            "  length N - set sprint length (2 to 30 days)\n"
            "  base dd.mm.yy - set sprints base date\n"
            "  period dd.mm.yy|week|sprint|month|quarter|year|all [to dd.mm.yy|today] -\n"
            "    set analysis time range, from first date or with specified duration\n"
            "    up 'to' specified date or 'today'\n"
            "Data commands:\n"
            "[exporter] [data] [dv] [for filter] [at|to period]\n"
            "  exporter: dump|plot|copy|csv - how to output, 'dump' is default\n"
            "  data: estimate|spent|original|burn - what to output, default is previous or 'estimate'\n"
            "  dv: type 'dv' to make data derivative by time scale, default no\n"
            "  filter: list of data categories to sort (tags, queues, etc), type info to show categories\n"
            "  period: local modifier of data time range, format:\n"
            "    dd.mm.yy|week|sprint|month|quarter|year|all [to dd.mm.yy|today]\n"
            "Example:\n"
            "  plot estimate for techdebt at all - show's graph of summary estimate\n"
            "    for category 'techdebt' at all project(s) duration up to today.\n")


class CommandError(BaseException):
    pass


class CmdParser:

    def __init__(self):
        self.filter = list()
        self.cat_list = list()
        self.dv = False
        self.base = None
        self.length = None
        self.mode = None
        self.data = 'estimate'
        self.engine = 'dump'
        self.tokens = None
        self.p_length = 'month'
        self.p_from = None  # 'None' mean use p_length
        self.p_to = None  # 'None' mean up to 'today'
        #=== handlers ===
        self.h_help = None

    @staticmethod
    def match(token, values):
        m = {v: len(set(token) & set(v)) / len(set(token) | set(v)) for v in values}  # jaccard distance
        max_token = max(m, key=m.get)
        # TODO: this realisation leads to cafe=face, need advance
        return max_token if m[max_token] > match_tolerance else None

    def parse(self, command: str):
        self.tokens = shlex.split(command)
        # empty command is 'info'
        if len(self.tokens) == 0:
            self.tokens.append('info')
        # check controls
        if t := self.match(self.tokens[0], ctrl_tokens):
            self.tokens.pop(0)
            if len(self.tokens):
                raise CommandError(f"Command '{t}' don't need parameters.")
            # TODO: controls handler t
            match t:
                case 'help' | 'h' | '?': self.h_help()
                case 'exit' | 'quit': sys.exit(0)

        # check global settings (multi settings allowed
        while len(self.tokens) and self.match(self.tokens[0], set_tokens):
            self.parse_set_token()  # call another method, should pop it't tokens
        data_required = False  # Flag user asks a new engine or new data processing
        # get engine
        if len(self.tokens) and (t := self.match(self.tokens[0], engine_tokens)):
            self.engine = t
            data_required = True
            self.tokens.pop(0)
        # get data
        if len(self.tokens) and (t := self.match(self.tokens[0], data_tokens)):
            self.data = t
            data_required = True
            self.tokens.pop(0)
        if len(self.tokens) and (t := self.match(self.tokens[0], dv_tokens)):
            self.dv = True
            data_required = True
            self.tokens.pop(0)
        if len(self.tokens) and (t := self.match(self.tokens[0], filter_tokens)):
            data_required = True
            self.tokens.pop(0)
            self.parse_filter()
        if len(self.tokens) and (t := self.match(self.tokens[0], local_period_tokens)):
            data_required = True
            self.parse_period()  # call another method, should pop it't tokens
        if len(self.tokens):
            raise CommandError(f"Can't understand '{', '.join(self.tokens)}'.")
        # TODO: not finished, here call handlers

    def parse_set_token(self):
        t = self.match(self.tokens[0], set_tokens)
        assert t is not None
        self.tokens.pop(0)
        if len(self.tokens) < 1:
            raise CommandError(f"Command '{t}' require more parameters.")
        match t:
            case 'mode':
                if v := self.match(self.tokens.pop(0), mode_tokens):
                    self.mode = v
                else:
                    raise CommandError(f"Mode value '{', '.join(mode_tokens)}' required.")
            case 'length':
                try:
                    v = _check_len_range(self.tokens.pop(0))
                    self.length = v
                except (ArgumentError, ValueError) as e:
                    raise CommandError from e
            case 'base':
                try:
                    v = dt.datetime.strptime(self.tokens.pop(0), '%d.%m.%y').date()
                    self.base = v
                except ValueError as e:
                    raise CommandError from e
            case 'period':
                self.parse_period()  # call another method, should pop it't tokens

    def parse_period(self):
        pass

    def parse_filter(self):
        # The 'next' construction return index of 'at'/'to' token (finishes a filter list)
        # or len(tokens) if no 'at'/'to'.
        index = next((i for i, t in enumerate(self.tokens) if t in local_period_tokens), len(self.tokens))
        if index == 0:
            raise CommandError('The "by" sentence requires list of actual categories.')
        f = [self.match(self.cat_list, t) for t in self.tokens[:index]]  # check categories actual
        self.filter = [i for i in f if i is not None]  # clear unknowns
        del self.tokens[:index]  # clear tokens to future processing


# === Test ===

def print_help():
    print(help_str)


def tst():
    p = CmdParser()
    p.h_help = print_help
    while True:
        c = input('>')
        try:
            p.parse(c)
            print('Executed')
            print(p.__dict__)
        except CommandError as e:
            print(e)


tst()
