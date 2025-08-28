import datetime as dt
import sys

import configparser
import argparse
from argparse import ArgumentError
import shlex

import logging
import unicodedata
import builtins


def normalize_text(text):
    return unicodedata.normalize('NFC', text.strip())


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
    return config['DEFAULT']


def save_config(filename, **kwargs):
    config = configparser.ConfigParser()
    config['DEFAULT'] = {key: str(value) for key, value in kwargs.items()}
    with open(filename, 'w') as configfile:
        config.write(configfile)


def _check_len_range(val):
    i = int(val)
    if i < 2 or i > 30:
        raise ArgumentError(argument=None, message='Sprint length expected 2 to 30 days.')
    return i


class ExpendoArgumentParser(argparse.ArgumentParser):
    # TODO: ArgParser requires update of 'period' arguments
    def __init__(self):
        super(ExpendoArgumentParser, self).__init__(
            description='Expendo v.2.0 - Yandex Tracker stat crawler by VCh.',
            epilog='Tracker connection settings and params in "expendo2.ini".')
        self.add_argument('query', type=str, nargs='?', default=None,
                          help='issues query, default last call query')
        self.add_argument('-m', '--mode', type=str, choices=['daily', 'sprint'],
                          help='time span mode')
        self.add_argument('--length', type=_check_len_range,
                          help='sprint length')
        self.add_argument('--base', type=lambda s: dt.datetime.strptime(s, '%d.%m.%y').date(),
                          help='sprint base date [dd.mm.yy]')

        self.add_argument('--period', type=str, dest='p_from',
                          choices=["week", "sprint", "month", "quarter", "year", "all"],
                          help='data period')

        self.add_argument('--to', dest='p_to',
                          type=lambda s: dt.datetime.strptime(s, '%d.%m.%y').date(),
                          help='data period final date [dd.mm.yy]')

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
ctrl_tokens = ['info', 'help', '?', 'h', 'quit', 'exit', 'q', 'fortheemperor']
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
            "\n"
            "Data commands:\n"
            "[exporter] [data] [dv] [for filter] [at|to period]\n"
            "  exporter: dump|plot|copy|csv - how to output, 'dump' is default\n"
            "  data: estimate|spent|original|burn - what to output, default is previous or 'estimate'\n"
            "  dv: type 'dv' to make data derivative by time scale, default no\n"
            "  filter: list of data categories to sort (tags, queues, etc), type info to show categories\n"
            "  period: local modifier of data time range, format as mentioned above:\n"
            "    dd.mm.yy|week|sprint|month|quarter|year|all [to dd.mm.yy|today]\n"
            "Example:\n"
            "  plot estimate for techdebt at all - show's graph of summary estimate\n"
            "    for category 'techdebt' at all project(s) duration up to today.\n")

info_prompt = "Enter ? to commands list (i.e. 'plot estimate'), CR to statistic, or Q to quit."


class CommandError(BaseException):
    pass


def get_ngrams(token, n=2):
    """Generate token n-grams"""
    return [token[i:i + n] for i in range(len(token) - n + 1)]


def match_t(in_token, values, match_tolerance=0.5, n=2):
    """Finds best match token in values, using n-grams"""
    token = normalize_text(in_token)
    token_ngrams = set(get_ngrams(token, n))
    best_match = None
    best_score = 0.0
    for v in values:
        v = normalize_text(v)
        v_ngrams = set(get_ngrams(v, n))  # TODO: add lowered ngrams to additional case-insensitive match with penalty
        # Short words processing
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


class OptionsManager:
    _names = ['query', 'org', 'token', 'base', 'length', 'mode', 'p_from', 'p_to']

    def __init__(self):
        # RO values
        self._query = ''
        self._org = ''
        self._token = ''
        # RW values
        self._base = dt.date(2025, 8, 20)
        self._length = 1
        self._mode = 'daily'
        self._p_from = 'today'
        self._p_to = 'today'
        self._changed_flag = False

    @property
    def query(self):
        return self._query

    @query.setter
    def query(self, value):
        if value is not None:
            self._query = value

    @property
    def org(self):
        return self._org

    @org.setter
    def org(self, value):
        if value is not None:
            self._org = value

    @property
    def token(self):
        return self._token

    @token.setter
    def token(self, value):
        if value is not None:
            self._token = value

    @property
    def base(self):
        return self._base

    @property
    def length(self):
        return self._length

    @property
    def mode(self):
        return self._mode

    @property
    def p_from(self):
        return self._p_from

    @property
    def p_to(self):
        return self._p_to

    @base.setter
    def base(self, value):
        match type(value):
            case builtins.str:
                b = dt.datetime.strptime(value, '%d.%m.%y').date()
            case dt.date:
                b = value
            case dt.datetime:
                b = value.date()
            case _:
                raise Exception("Unknown type of 'base' value")
        if b != self._base:
            self._base = b
            self._changed_flag = True

    @length.setter
    def length(self, value):
        # TODO: check length limits
        match type(value):
            case builtins.str:
                n = int(value)
            case builtins.int:
                n = value
            case _:
                raise Exception("Unknown type of 'length' value")
        if n != self._length:
            self._length = n
            self._changed_flag = True

    @mode.setter
    def mode(self, value: str):
        if value not in mode_tokens:
            raise Exception("Unknown 'mode' value")
        if value != self._mode:
            self._mode = value
            self._changed_flag = True

    @p_from.setter
    def p_from(self, value):
        if value is None:
            return
        if value in period_tokens:
            p = value
        else:
            try:
                dt.datetime.strptime(value, '%d.%m.%y')
                p = value
            except ValueError as e:
                raise Exception("Wrong 'period' value") from e
        if p != self._p_from:
            self._p_from = p
            self._changed_flag = True

    @p_to.setter
    def p_to(self, value):
        if value is None:
            return
        if value in date_tokens:
            p = value
        else:
            try:
                dt.datetime.strptime(value, '%d.%m.%y')
                p = value
            except ValueError as e:
                raise Exception("Wrong 'period to' value") from e
        if p != self._p_to:
            self._p_to = p
            self._changed_flag = True

    def set_values(self, **kwargs):
        for name in self._names:
            if name in kwargs and getattr(self, name) != kwargs[name] and kwargs[name] is not None:
                setattr(self, name, kwargs[name])
                self._changed_flag = True

    def get_values_str(self) -> dict:
        return {'query': self._query,
                'org': self._org,
                'token': self._token,
                'base': self._base.strftime('%d.%m.%y'),
                'length': str(self._length),
                'mode': self._mode,
                'p_from': self._p_from,
                'p_to': self._p_to}

    @property
    def changed(self):
        r = self._changed_flag
        self._changed_flag = False
        return r

    def get_settings_str(self):
        """Settings: Daily for all, Sprint (14 days based 01.01.25) for quarter to 31.12.24"""
        sprint = ""
        if self._mode == "sprint":
            sprint = f" ({self._length} days based {self._base.strftime('%d.%m.%y')})"
        return f"Settings: {self._mode.capitalize()}" \
               f"{sprint} at {self._p_from} to {self._p_to}"


class CmdParser:

    def __init__(self):
        self.options = OptionsManager()

        self.filter = list()
        self.recalc_flag = True
        self.data = 'estimate'
        self.dv = False
        self.engine = 'dump'
        self.tokens = None

        # === handlers ===
        self.h_period = lambda *args, **kwargs: None  # period change handler, func(start, end, len, base)
        self.h_recalc = lambda *args, **kwargs: None  # data recalculate handler, func(datakind, dv, categories)
        self.h_export = lambda *args, **kwargs: None  # data export handler, func(engine)
        self.h_cats = lambda *args, **kwargs: list()  # category list getter handler, func()
        self.h_cats_str = lambda *args, **kwargs: ''  # categories string info getter handler, func()
        self.h_stat_info = lambda *args, **kwargs: ''  # stat info getter handler, func()

    def parse(self, command: str):
        sh = shlex.shlex(command)
        sh.whitespace += ','
        sh.wordchars += '.'
        self.tokens = [s.replace('"', '') for s in list(sh)]
        # if empty command - use 'info'
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
                case 'exit' | 'quit' | 'q':
                    sys.exit(0)
                case 'info':
                    print('\n'.join([self.options.query,
                                     self.h_stat_info(),
                                     self.options.get_settings_str(),
                                     self.h_cats_str(),
                                     info_prompt]))
                case 'fortheemperor':
                    print(info_prompt)
            return
        # check global settings (multi settings allowed)
        sets_flag = False
        while len(self.tokens) and match_t(self.tokens[0], set_tokens):
            self.parse_set_token()  # call another method, should pop its tokens
            sets_flag = True
        # get engine
        if len(self.tokens) and (t := match_t(self.tokens[0], engine_tokens)):
            self.engine = t
            self.tokens.pop(0)
        # get data
        if len(self.tokens) and (t := match_t(self.tokens[0], data_tokens)):
            if t != self.data:
                self.data = t
                self.recalc_flag = True
            self.tokens.pop(0)
        if new_dv := (len(self.tokens) > 0 and match_t(self.tokens[0], dv_tokens) is not None):
            self.tokens.pop(0)
        if self.dv != new_dv:
            self.dv = new_dv
            self.recalc_flag = True
        if len(self.tokens) and match_t(self.tokens[0], filter_tokens):
            self.tokens.pop(0)
            new_filter = self.parse_filter()
            if self.filter != new_filter:
                self.filter = new_filter
                self.recalc_flag = True

        if len(self.tokens) and match_t(self.tokens[0], period_bound_tokens):
            self.parse_period()  # call another method, should pop its tokens
        if len(self.tokens):
            raise CommandError(f"Can't understand '{' '.join(self.tokens)}'.")
        # here call handlers
        if self.options.changed:
            self.recalc_flag = True
            self.h_period(p_start=self.options.p_from,
                          p_end=self.options.p_to,
                          length=self.options.length if self.options.mode == 'sprint' else 1,
                          base=self.options.base)
        if self.recalc_flag:
            self.h_recalc(data_kind=self.data,
                          dv=self.dv,
                          categories=self.filter)
            self.recalc_flag = False
        if not sets_flag:
            self.h_export(engine=self.engine)

    def parse_set_token(self):
        t = match_t(self.tokens[0], set_tokens)
        assert t is not None
        self.tokens.pop(0)
        if len(self.tokens) < 1:
            raise CommandError(f"Command '{t}' require more parameters.")
        match t:
            case 'mode':
                if v := match_t(self.tokens.pop(0), mode_tokens):
                    self.options.mode = v
                else:
                    raise CommandError(f"Mode value '{', '.join(mode_tokens)}' required.")
            case 'length':
                try:
                    v = _check_len_range(self.tokens.pop(0))
                    self.options.length = v
                except (ArgumentError, ValueError) as e:
                    raise CommandError from e
            case 'base':
                try:
                    v = dt.datetime.strptime(self.tokens.pop(0), '%d.%m.%y').date()
                    self.options.base = v
                except ValueError as e:
                    raise CommandError from e
            case 'period':
                self.tokens.insert(0, 'period')
                self.parse_period()  # call another method, should pop its tokens

    def parse_period(self):
        # we enter here with tokens 'period xxxx [to yyyy]' - global setting
        # or 'at xxxx [to yyyy]' - local setting
        # or 'to yyyy' - local setting
        while len(self.tokens) and (t := match_t(self.tokens.pop(0), set(period_bound_tokens) | {'period'})):
            match t:
                case 'period' | 'at':
                    p_val = self.tokens.pop(0)
                    if p := match_t(p_val, period_tokens):
                        self.options.p_from = p
                    elif match_t(p_val, ['to']):
                        self.tokens.insert(0, 'to')
                    else:
                        try:
                            dt.datetime.strptime(p_val, '%d.%m.%y')
                            self.options.p_from = p_val
                        except ValueError as e:
                            raise CommandError from e
                case 'to':
                    p_val = self.tokens.pop(0)
                    if p := match_t(p_val, date_tokens):
                        self.options.p_to = p
                    else:
                        try:
                            dt.datetime.strptime(p_val, '%d.%m.%y')
                            self.options.p_to = p_val
                        except ValueError as e:
                            raise CommandError from e

    def parse_filter(self):
        # The 'next' construction return index of 'at'/'to' token (finishes a filter list)
        # or len(tokens) if no 'at'/'to'.
        index = next((i for i, t in enumerate(self.tokens) if match_t(t, period_bound_tokens)), len(self.tokens))
        if index == 0:
            raise CommandError('The "by" sentence requires list of categories.')
        cat_list = self.h_cats()
        r = set()
        for i in range(index):
            if v := match_t(t := self.tokens.pop(0), cat_list):
                r.add(v)
            else:
                print(f'Warning: "{t}" is not a category.')
        return sorted(list(r))
