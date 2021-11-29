#!/usr/bin/env python3

import argparse
import datetime
import json
import os
import re
import requests
import shutil
import tempfile
from enum import Enum, Flag, auto

class IncludeHidden(Enum):
    NO = 'no'
    YES = 'yes'
    LEARNED = 'learned'

    def __str__(self):
        return self.value

class Cleanup(Flag):
    NONE = 0
    SURU = auto()
    TILDE = auto()

API_KEY = ''
INCLUDE_HIDDEN = IncludeHidden.NO

def _get_paging(wk_endpoint):
    wk_url = 'https://api.wanikani.com/v2' + wk_endpoint
    while True:
        r = requests.get(wk_url, headers={
            'Wanikani-Revision': '20170710',
            'Authorization': 'Bearer ' + API_KEY,
        })
        r.raise_for_status()
        response = r.json()
        yield from response['data']
        wk_url = response['pages']['next_url']
        if wk_url is None:
            break

def get_subjects(only_hidden = False):
    endpoint = '/subjects?types=kanji,vocabulary'
    if only_hidden:
        endpoint += '&hidden=true'
    return _get_paging(endpoint)

def get_assignments(subject_ids):
    if len(subject_ids) == 0:
        return []
    endpoint = '/assignments?subject_ids=' + ','.join(map(str, subject_ids))
    return _get_paging(endpoint)

def subject_to_metadata(subject):
    type = subject['object']
    data = subject['data']
    if type == 'vocabulary':
        cleanup_flags = is_cleanup_needed(data['characters'])
        meta = ([
            clean_characters(data['characters'], cleanup_flags),
            'freq',
            {
                'reading': clean_characters(reading['reading'], cleanup_flags),
                'frequency': {
                    'value': data['level'],
                    'displayValue': f"L{data['level']}"
                }
            }
        ] for reading in data['readings'])
    elif type == 'kanji':
        meta = [[
            data['characters'],
            'freq',
            {
                'value': data['level'],
                'displayValue': f"L{data['level']}"
            }
        ]]
    else:
        raise NotImplementedError(f'Cannot handle type "{type}"')

    return type, meta

_suru_pattern = re.compile(r'^[\u4e00-\u9fff]{2,}する$')

def is_cleanup_needed(characters):
    flags = Cleanup.NONE
    if _suru_pattern.match(characters) is not None:
        flags = flags | Cleanup.SURU
    if '〜' in characters:
        flags = flags | Cleanup.TILDE
    return flags

def clean_characters(characters, flags):
    if Cleanup.SURU in flags:
        characters = re.sub('する$', '', characters)
    if Cleanup.TILDE in flags:
        characters = characters.replace('〜', '')
    return characters

def get_learned_hidden():
    try:
        return get_learned_hidden.ids
    except AttributeError:
        hidden_subjects = get_subjects(only_hidden=True)
        subject_ids = [sub['id'] for sub in hidden_subjects]
        assignments = get_assignments(subject_ids)
        get_learned_hidden.ids = [a['data']['subject_id'] for a in assignments if a['data']['passed_at'] is not None]
        return get_learned_hidden.ids

def filter_hidden(subject):
    if INCLUDE_HIDDEN is IncludeHidden.YES:
        return True

    hidden_at = subject['data']['hidden_at']
    if hidden_at is not None:
        if INCLUDE_HIDDEN is IncludeHidden.NO:
            return False
        if INCLUDE_HIDDEN is IncludeHidden.LEARNED:
            return subject['id'] in get_learned_hidden()
    return True

def parse_args():
    global API_KEY
    global INCLUDE_HIDDEN

    parser = argparse.ArgumentParser('Converts all Wanikani kanji and vocab subjects into a Yomichan metadata dictionary')
    parser.add_argument('--api-key', help='your Wanikani API key. If you do not use this option, you will be asked to enter it when you execute the script')
    parser.add_argument('--hidden', type=IncludeHidden, choices=list(IncludeHidden), default=IncludeHidden.NO, help='include hidden items (default: %(default)s)')

    args = parser.parse_args()

    API_KEY = args.api_key
    if not API_KEY:
        API_KEY = input('Please enter your Wanikani API key:\n')
        if not API_KEY:
            print('No API key specified, abort')
            exit(1)
    INCLUDE_HIDDEN = args.hidden

if __name__ == '__main__':
    parse_args()

    print('Fetch and process Wanikani data...')
    meta_vocab = []
    meta_kanji = []
    subjects = get_subjects()
    for sub in filter(filter_hidden, subjects):
        type, meta = subject_to_metadata(sub)
        for m in meta:
            if type == 'vocabulary':
                meta_vocab.append(m)
            else:
                meta_kanji.append(m)
    tmpdir = tempfile.mkdtemp()
    try:
        print('Create archive...')
        with open(os.path.join(tmpdir, 'index.json'), 'w+') as indexfile:
            json.dump({'revision': 'wk-meta-' + datetime.date.today().isoformat(), 'title': 'WK', 'format': 3}, indexfile)
        with open(os.path.join(tmpdir, 'term_meta_bank_1.json'), 'w+') as termfile:
            json.dump(meta_vocab, fp=termfile, ensure_ascii=False)
        with open(os.path.join(tmpdir, 'kanji_meta_bank_1.json'), 'w+') as kanjifile:
            json.dump(meta_kanji, fp=kanjifile, ensure_ascii=False)

        dict_path = os.path.join(os.getcwd(), 'wk-yomichan-metadata')
        shutil.make_archive(dict_path, 'zip', tmpdir)
        print(f"Created file {dict_path}.zip")
    finally:
        shutil.rmtree(tmpdir)
