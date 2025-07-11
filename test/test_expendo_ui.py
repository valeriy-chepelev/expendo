import pytest
import datetime
import argparse
from expendo_ui import ExpendoArgumentParser


def assert_content(n):
    assert 'query' in n
    assert 'mode' in n
    assert 'length' in n
    assert 'base' in n
    assert 'debug' in n
    assert 'token' in n
    assert 'org' in n


def test_expendo_argument_parser():
    p = ExpendoArgumentParser()
    assert p is not None
    args = p.parse_args([])
    assert_content(args)
    assert args.token is None
    for k, v in vars(args).items():
        print(f'{k} = {v}')
    args = p.parse_args(['Simple'])
    assert args.query == 'Simple'
    assert args.mode is None
    assert args.length is None
    assert args.base is None
    assert not args.debug
    args = p.parse_args(['Long spaced "quoted"'])
    assert_content(args)
    assert args.query == 'Long spaced "quoted"'
    assert p.parse_args('query --base 31.01.25'.split())
    args = p.parse_args('query --length 5 --base 1.1.25 --mode sprint'.split())
    assert_content(args)
    assert args.length == 5
    assert type(args.base) is datetime.date
    assert args.mode == 'sprint'
    args = p.parse_args('query -m daily --debug'.split())
    assert args.mode == 'daily'
    assert args.debug

    with pytest.raises(BaseException):
        p.parse_args('query --mode s'.split())
    with pytest.raises(BaseException):
        p.parse_args('query --length 1'.split())
    with pytest.raises(BaseException):
        p.parse_args('query --length 32'.split())
    with pytest.raises(BaseException):
        p.parse_args('query --base 31.02.25'.split())
    with pytest.raises(BaseException):
        p.parse_args('query --base 15-01-25'.split())
