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
import unicodedata


def normalize_text(text):
    return unicodedata.normalize('NFC', text.strip().lower())

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
        raise ArgumentError(argument=None, message='Sprint length expected 2 to 30 days.')
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
period_tokens = ['today', 'now', 'yesterday', 'week', 'sprint', 'month', 'quarter', 'year', 'all', 'full']
date_tokens = ['today', 'now', 'yesterday']
period_bound_tokens = ['at', 'to']

help_str = ("General control commands:\n"
            "  help, ?, h - this description\n"
            "  quit, exit - quits\n"
            "  info or just Enter - common stat and settings info\n"
            "Global settings commands (stored to .ini):\n"
            "  mode sprint|daily - set time mode\n"
            "  length N - set sprint length (2 to 30 days)\n"
            "  base dd.mm.yy - set sprints base date\n"
            "  period dd.mm.yy|today|week|sprint|month|quarter|year|all [to dd.mm.yy|today] -\n"
            "    set analysis time range, from first date (or 'today') or with specified duration\n"
            "    up 'to' specified date or 'today'; 'today' will be aligned at future runs\n"
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


def get_ngrams(token, n=2):
    """Генерация n-грамм для токена."""
    return [token[i:i + n] for i in range(len(token) - n + 1)]


def match_t(in_token, values, match_tolerance=0.5, n=2):
    """Находит наиболее похожий токен в словаре с учётом n-грамм."""
    token = normalize_text(in_token).lower()
    token_ngrams = set(get_ngrams(token, n))
    best_match = None
    best_score = 0.0
    for v in values:
        v_ngrams = set(get_ngrams(v, n))
        # Обработка коротких слов
        if not token_ngrams and not v_ngrams:
            score = 1.0 if token == v else 0.0
        else:
            intersection = token_ngrams & v_ngrams
            union = token_ngrams | v_ngrams
            score = len(intersection) / len(union) if union else 0.0
        if score > best_score:
            best_score = score
            best_match = v
    return best_match if best_score > match_tolerance else None


class CmdParser:

    def __init__(self):
        self.local_period = None
        self.global_period = None
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
        # === handlers ===
        self.h_info = lambda: None

    def parse(self, command: str):
        self.tokens = shlex.split(command)
        self.local_period = None
        data_required = False  # Flag user asks a new engine or new data processing
        # empty command is 'info'
        if len(self.tokens) == 0:
            self.tokens.append('info')
        # check controls
        if t := match_t(self.tokens[0], ctrl_tokens):
            self.tokens.pop(0)
            if len(self.tokens):
                raise CommandError(f"Command '{t}' don't need parameters.")
            match t:
                case 'help' | 'h' | '?':
                    print(help_str)
                case 'exit' | 'quit':
                    sys.exit(0)
                case 'info':
                    self.h_info()
        # check global settings (multi settings allowed
        while len(self.tokens) and match_t(self.tokens[0], set_tokens):
            self.parse_set_token()  # call another method, should pop its tokens
        # get engine
        if len(self.tokens) and (t := match_t(self.tokens[0], engine_tokens)):
            self.engine = t
            data_required = True
            self.tokens.pop(0)
        # get data
        if len(self.tokens) and (t := match_t(self.tokens[0], data_tokens)):
            self.data = t
            data_required = True
            self.tokens.pop(0)
        if len(self.tokens) and match_t(self.tokens[0], dv_tokens):
            self.dv = True
            data_required = True
            self.tokens.pop(0)
        if len(self.tokens) and match_t(self.tokens[0], filter_tokens):
            data_required = True
            self.tokens.pop(0)
            self.parse_filter()
        if len(self.tokens) and match_t(self.tokens[0], period_bound_tokens):
            data_required = True
            self.local_period = self.parse_period()  # call another method, should pop its tokens
        if len(self.tokens):
            raise CommandError(f"Can't understand '{' '.join(self.tokens)}'.")
        # TODO: not finished, here call handlers

    def parse_set_token(self):
        t = match_t(self.tokens[0], set_tokens)
        assert t is not None
        self.tokens.pop(0)
        if len(self.tokens) < 1:
            raise CommandError(f"Command '{t}' require more parameters.")
        match t:
            case 'mode':
                if v := match_t(self.tokens.pop(0), mode_tokens):
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
                self.global_period = self.parse_period()  # call another method, should pop its tokens

    def parse_period(self):
        # we enter here with tokens 'period xxxx [to yyyy]' - global setting
        # or 'at xxxx [to yyyy]' - local setting
        # or 'to yyyy' - local setting
        result = {'p': None, 'to': None}
        while len(self.tokens) and (t := match_t(self.tokens.pop(0), set(period_bound_tokens) | {'period'})):
            match t:
                case 'period' | 'at':
                    p_val = self.tokens.pop(0)
                    if p := match_t(p_val, period_tokens):
                        result['p'] = p
                    else:
                        try:
                            result['p'] = dt.datetime.strptime(p_val, '%d.%m.%y').date()
                        except ValueError as e:
                            raise CommandError from e
                case 'to':
                    p_val = self.tokens.pop(0)
                    if p := match_t(p_val, date_tokens):
                        result['to'] = p
                    else:
                        try:
                            result['to'] = dt.datetime.strptime(p_val, '%d.%m.%y').date()
                        except ValueError as e:
                            raise CommandError from e
        return result

    def parse_filter(self):
        # The 'next' construction return index of 'at'/'to' token (finishes a filter list)
        # or len(tokens) if no 'at'/'to'.
        index = next((i for i, t in enumerate(self.tokens) if match_t(t, period_bound_tokens)), len(self.tokens))
        if index == 0:
            raise CommandError('The "by" sentence requires list of actual categories.')
        f = [match_t(t, self.cat_list) for t in self.tokens[:index]]  # check categories actual
        self.filter = [i for i in f if i is not None]  # clear unknowns
        del self.tokens[:index]  # clear tokens to future processing


# === Test ===

from pprint import pprint


def print_info():
    print('info')


def tst():
    p = CmdParser()
    # Connect handlers
    p.h_info = print_info
    p.cat_list = ['mthw', 'mtfw', 'mtqa', 'some sheet']
    # Main command cycle
    while True:
        c = input('>')
        try:
            p.parse(c)
            print('Executed')
            pprint(p.__dict__)
        except CommandError as e:
            print('Error:', e.__cause__ if e.__cause__ else e)


if __name__ == '__main__':
    tst()
