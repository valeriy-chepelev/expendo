import datetime as dt
import sys

import configparser
import argparse
from argparse import ArgumentError
import shlex

import logging
import unicodedata
import builtins

from colorama import Fore, Back, Style


def normalize_text(text):
    return unicodedata.normalize('NFC', text.strip())


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
    def __init__(self):
        super(ExpendoArgumentParser, self).__init__(
            description='Expendo v.2.1 - Yandex Tracker stat crawler by VCh.',
            epilog='Settings and params to be stored in "expendo2.ini".')
        self.add_argument('query', type=str, nargs='?', default=None,
                          help='issues query, default last call query')
        # access to Tracker
        self.add_argument('--token', type=str,
                          help='Tracker access token')
        self.add_argument('--org', type=str,
                          help='Tracker organisation id')
        # mode and sprint
        self.add_argument('--mode', type=str, choices=['daily', 'sprint'],
                          help='time span mode')
        self.add_argument('--length', type=_check_len_range,
                          help='sprint length, days')
        self.add_argument('--base', type=lambda s: dt.datetime.strptime(s, '%d.%m.%y').date(),
                          help='sprint base date [dd.mm.yy]')
        # time range
        self.add_argument('--period', type=str, dest='p_from',
                          choices=["week", "sprint", "month", "quarter", "year", "all", "yesterday", "today"],
                          help='data period range')
        self.add_argument('--to', type=str, dest='p_to',
                          choices=["yesterday", "today"],
                          help='data period final')
        # trends
        self.add_argument('--trend', type=str, dest='regression',
                          choices=["residuals", "differences", "smooth"],
                          help='trends scoring method')
        self.add_argument('--factor', type=int,
                          help='trends scoring factor')
        self.add_argument('--velocity', type=float,
                          help='nominal team velocity, hrs/day')
        # debug
        self.add_argument('--debug', default=False, action='store_true',
                          help='logging in debug mode (include tracker and issues info)')


# ---------------------------------------------------------
#                      CLI commands parser
# ---------------------------------------------------------


set_tokens = ['mode', 'length', 'base', 'period', 'regression', 'factor', 'velocity']
ctrl_tokens = ['info', 'help', '?', 'h', 'quit', 'exit', 'q', 'simpleinfointernal', 'clear']
engine_tokens = ['dump', 'plot', 'copy', 'csv']
data_tokens = ['estimate', 'spent', 'original', 'burn']
dv_tokens = ['dv']
trend_tokens = ['trends']
filter_tokens = ['for', 'exclude']
mode_tokens = ['daily', 'sprint']
regression_tokens = ['residuals', 'differences', 'smooth']
period_tokens = ['today', 'now', 'yesterday', 'week', 'sprint', 'month', 'quarter', 'year', 'all', 'full']
date_tokens = ['today', 'now', 'yesterday']
period_bound_tokens = ['at', 'from', 'to']

help_str = ("General control commands:\n"
            "  help, ?, h - this description\n"
            "  quit, exit - quits\n"
            "  clear - reset selected categories (see 'for/exclude' below)\n"
            "  info or just Enter - common stat and settings info\n"
            "Settings commands (stored to .ini):\n"
            "  mode sprint|daily - set time mode\n"
            "  length N - set sprint length (2 to 30 days)\n"
            "  base dd.mm.yy - set sprints base date\n"
            "  period dd.mm.yy|today|week|sprint|month|quarter|year|all [to dd.mm.yy|today] -\n"
            "    set analysis time range, from first date (or 'today') or with specified duration\n"
            "    up 'to' specified date or 'today'; 'today' will be aligned at future runs\n"
            "  regression residuals|differences|smooth - set trends scoring method, res default\n"
            "  factor [3-10] - set trends scoring factor, 5 default\n"
            "  velocity - nominal velocity, 5.71 hrs/day default (8 hrs per day * 5/7 working days)\n"
            "Data commands:\n"
            "[exporter] [data] [dv] [trends] [for categories] [exclude categories] [at|from|to period]\n"
            "  exporter: dump|plot|copy - how to output, default is previous or 'dump'\n"
            "  data: estimate|spent|original|burn - what to output, default is previous or 'estimate'\n"
            "  dv: type 'dv' to make data derivative by time scale, default No\n"
            "  trends: type 'trends' to calculate linear regressions, default No\n"
            "  for: list of data categories to sort (tags, queues, etc), type info to show categories\n"
            "  exclude: list of data categories, any to be excluded from calculations\n"
            "  period: data time range, format as mentioned above:\n"
            "    dd.mm.yy|week|sprint|month|quarter|year|all [to dd.mm.yy|today]\n"
            "Example:\n"
            "  plot estimate for techdebt at all - show's graph of summary estimate\n"
            "    for category 'techdebt' at all project(s) duration up to today.\n")

info_prompt = (f"Enter {Fore.LIGHTGREEN_EX}?{Fore.RESET} to commands,"
               f" {Fore.LIGHTGREEN_EX}CR{Fore.RESET} to statistic,"
               f" {Fore.LIGHTGREEN_EX}Q{Fore.RESET} to quit.")


class CommandError(BaseException):
    pass


def get_ngrams(token, n=2):
    """Generate token n-grams"""
    return [token[i:i + n] for i in range(len(token) - n + 1)]


def match_t(in_token, values, match_tolerance=0.5, n=2, lowered_penalty=0.8):
    """Finds best match token in values, using n-grams"""
    token = normalize_text(in_token)
    token_ngrams = set(get_ngrams(token, n))
    best_match = None
    best_score = 0.0
    for v in values:
        v = normalize_text(v)
        v_ngrams = set(get_ngrams(v, n))
        # Short words processing
        if not token_ngrams and not v_ngrams:
            score = 1.0 if token == v else 0.0
            lowered_score = lowered_penalty if token.lower() == v.lower() else 0.0
        else:
            # case-sensitive match
            intersection = token_ngrams & v_ngrams
            union = token_ngrams | v_ngrams
            score = len(intersection) / len(union) if union else 0.0
            # case-insensitive match
            lowered_t_n = {s.lower() for s in token_ngrams}
            lowered_v_n = {s.lower() for s in v_ngrams}
            intersection = lowered_t_n & lowered_v_n
            union = lowered_t_n | lowered_v_n
            lowered_score = lowered_penalty * len(intersection) / len(union) if union else 0.0
        if (s := max(score, lowered_score)) > best_score:
            best_score = s
            best_match = v
    return best_match if best_score > match_tolerance else None


class OptionsManager:
    _names = ['query', 'org', 'token', 'base', 'length', 'mode', 'p_from', 'p_to',
              'regression', 'factor', 'velocity']

    def __init__(self):
        # RO values
        self._query = ''
        self._org = ''
        self._token = ''
        # RW values
        self._base = dt.date(2025, 8, 20)
        self._length = 14
        self._mode = 'daily'
        self._p_from = 'today'
        self._p_to = 'today'
        self._regression = 'residuals'
        self._factor = 5
        self._velocity = 8.0 * 5 / 7
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

    @property
    def velocity(self):
        return self._velocity

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

    @velocity.setter
    def velocity(self, value):
        # TODO: check velocity range
        if type(value) in [builtins.str, builtins.int, builtins.float]:
            n = float(value)
        else:
            raise Exception("Unknown type of 'velocity' value")
        if abs(n - self._velocity) > 1e-3:
            self._velocity = n
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

    @property
    def regression(self):
        return self._regression

    @regression.setter
    def regression(self, value):
        if value not in regression_tokens:
            raise Exception("Unknown 'regression' value")
        if value != self._regression:
            self._regression = value
            self._changed_flag = True

    @property
    def factor(self):
        return self._factor

    @factor.setter
    def factor(self, value):
        # TODO: check factor limits
        match type(value):
            case builtins.str:
                n = int(value)
            case builtins.int:
                n = value
            case _:
                raise Exception("Unknown type of 'factor' value")
        if n != self._factor:
            self._factor = n
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
                'p_to': self._p_to,
                'regression': self._regression,
                'factor': str(self._factor),
                'velocity': f'{self._velocity:.2f}'}

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
        return f"{self._mode}" \
               f"{sprint} at {self._p_from} to {self._p_to}; " \
               f"trend {self._regression} (C={self._factor}, Vnom={self._velocity:.2f})"


class CmdParser:

    def __init__(self):
        self.options = OptionsManager()

        self.filter = list()  # list of search categories
        self.exclude = list()  # list of excluded categories
        self.recalc_flag = True
        self.data = 'estimate'
        self.dv = False
        self.trends = False
        self.engine = 'dump'
        self.tokens = None

        # === handlers ===
        # period change handler, func(start, end, len, base)
        self.h_period = lambda *args, **kwargs: None
        # data recalculate handler, func(data_kind, dv, categories, exclusions)
        self.h_recalc = lambda *args, **kwargs: None
        # segments recalculate handler, func(method, c)
        self.h_trends = lambda *args, **kwargs: None
        # data export handler, func(engine, velocity)
        self.h_export = lambda *args, **kwargs: None
        # category list getter handler, func()
        self.h_cats = lambda *args, **kwargs: list()
        # categories extended info getter handler, func()
        self.h_ext_cats_info = lambda *args, **kwargs: dict()
        # stat info getter handler, func()
        self.h_stat_info = lambda *args, **kwargs: ''

    def _colorized_cat_info(self):
        def color(k):
            if k in self.exclude:
                return Fore.RED
            if k in self.filter:
                return Fore.LIGHTCYAN_EX
            return Fore.LIGHTGREEN_EX

        cats = self.h_ext_cats_info()
        s = 'Categories:'
        for cat_class in cats.keys():
            s += f'\n  -{cat_class}: '
            s += ', '.join([f'{color(key)}{key}{Fore.RESET}' +
                            ('' if value is None else f': {value}')
                            for key, value in cats[cat_class]])
        if len(cats) == 0:
            s += ' not found'
        return s

    def parse(self, command: str):
        sh = shlex.shlex(command)
        sh.whitespace += ','
        sh.wordchars += '.'
        sh.wordchars += 'абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ+-_'
        self.tokens = [s.replace('"', '') for s in list(sh)]
        # if empty command - use 'info'
        if len(self.tokens) == 0:
            self.tokens.append('info')
        settings_changed = False  # flag settings was changed - no exporting in this case
        new_dv = False
        new_trends = False
        tokens_count = len(self.tokens) + 1  # Tokens count are used to detect no tokens extracted during cycle
        while 0 < len(self.tokens) < tokens_count:
            tokens_count = len(self.tokens)
            # check controls and exit
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
                        print('Issues: ' + Fore.LIGHTCYAN_EX + self.options.query + Fore.RESET)
                        print(self.h_stat_info())
                        print(self._colorized_cat_info())
                        print('Settings:' + Fore.LIGHTCYAN_EX,
                              self.engine, self.data,
                              self.options.get_settings_str() + Fore.RESET, sep=' ')
                        print(info_prompt)
                    case 'simpleinfointernal':
                        print('Settings:' + Fore.LIGHTCYAN_EX,
                              self.engine, self.data,
                              self.options.get_settings_str() + Fore.RESET, sep=' ')
                        print(info_prompt)
                    case 'clear':
                        self.filter = []
                        self.exclude = []
                        self.recalc_flag = True
                return
            # check global settings
            if len(self.tokens) and match_t(self.tokens[0], set_tokens):
                self.parse_set_token()  # call another method, should pop its tokens
                settings_changed = True
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
            # check dv
            if len(self.tokens) and match_t(self.tokens[0], dv_tokens):
                new_dv = True
                self.tokens.pop(0)
            # check dv
            if len(self.tokens) and match_t(self.tokens[0], trend_tokens):
                new_trends = True
                self.tokens.pop(0)
            # check categories
            if len(self.tokens) and (t := match_t(self.tokens[0], filter_tokens)):
                self.tokens.pop(0)  # pop token only if it matches
                new_filter = self.parse_filter()
                if self.filter != new_filter and len(new_filter) and t == 'for':
                    self.filter = new_filter
                    self.recalc_flag = True
                if self.exclude != new_filter and len(new_filter) and t == 'exclude':
                    self.exclude = new_filter
                    self.recalc_flag = True
            # check period
            if len(self.tokens) and match_t(self.tokens[0], period_bound_tokens):
                self.parse_period()  # call another method, should pop its tokens

        # --- end tokens parsing ---

        if len(self.tokens):
            raise CommandError(f"Can't understand '{' '.join(self.tokens)}'.")
        if self.dv != new_dv:
            self.dv = new_dv
            self.recalc_flag = True
        if self.trends != new_trends:
            self.trends = new_trends
            self.recalc_flag = True
        # call handlers
        if self.options.changed:
            self.recalc_flag = True
            self.h_period(p_start=self.options.p_from,
                          p_end=self.options.p_to,
                          length=self.options.length if self.options.mode == 'sprint' else 1,
                          base=self.options.base)
        if self.recalc_flag:
            self.h_recalc(data_kind=self.data,
                          dv=self.dv,
                          categories=self.filter,
                          exclusions=self.exclude)
            if self.trends:
                self.h_trends(self.options.regression, self.options.factor)
            self.recalc_flag = False
        if not settings_changed:
            self.h_export(engine=self.engine, velocity=self.options.velocity)

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
            case 'factor':
                try:
                    v = int(self.tokens.pop(0))
                    self.options.factor = v
                except (ArgumentError, ValueError) as e:
                    raise CommandError from e
            case 'velocity':
                try:
                    v = float(self.tokens.pop(0))
                    self.options.velocity = v
                except (ArgumentError, ValueError) as e:
                    raise CommandError from e
            case 'regression':
                if v := match_t(self.tokens.pop(0), regression_tokens):
                    self.options.regression = v
                else:
                    raise CommandError(f"Regression value '{', '.join(regression_tokens)}' required.")

    def parse_period(self):
        # we enter here with tokens 'period xxxx [to yyyy]' - global setting
        # or 'at xxxx [to yyyy]' - local setting
        # or 'to yyyy' - local setting
        while len(self.tokens) and (t := match_t(self.tokens[0], set(period_bound_tokens) | {'period'})):
            self.tokens.pop(0)
            match t:
                case 'period' | 'at' | 'from':
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
        cat_list = self.h_cats()
        r = set()
        while len(self.tokens) and (v := match_t(self.tokens[0], cat_list)):
            r.add(v)
            self.tokens.pop(0)
        return sorted(list(r))
