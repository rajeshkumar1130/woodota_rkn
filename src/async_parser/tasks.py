import os
import subprocess
from bz2 import decompress
from typing import Any

import requests
from celery import chain
from loguru import logger

from .celery import app
from settings import REPLAY_DIR, CLARITY_HOST, CLARITY_PORT


def download(url: str) -> bytes:
    logger.info(f'Downloading: {url}...')
    r = requests.get(url)
    r.raise_for_status()
    compressed_dem = r.content
    logger.info(f'Decompressing: {url}...')
    dem = decompress(compressed_dem)
    return dem


@app.task()
def download_save(match_id: str) -> str:
    file_name = match_id
    file_name += '.dem'
    path = os.path.join(REPLAY_DIR, file_name)

    if os.path.exists(path):
        logger.info(f'Dem file already exists: {path}...')
        return path
    
    url = retrive1(match_id)
    logger.info(f'{url}')
    dem_url = url
    logger.info(f'{dem_url=}')
    if dem_url is None:
        return 'Error:' + 'Demo URL not found'
    dem_url = dem_url.strip()
    
    dem = download(url)
    with open(path, 'wb') as fout:
        fout.write(dem)
    logger.info(f'Saved to {path}...')
    return path


class ClarityParserException(Exception):
    pass

def retrive1(match_id: int) -> str:
    logger.info(f'{match_id=}')
    try:
        match_id = int(match_id)
    except ValueError:
        return 'Error:' + 'Match ID is not a number'

    r = requests.get(
        'https://api.opendota.com/api/matches/'+ str(match_id)
    )
    try:
        r.raise_for_status()
        if not r.json():
            raise Exception(f'Replay not found for the Match ID: {match_id}')
    except Exception as err:
        return 'Error:' + str(err)

    replay = r.json()
    cluster = replay['cluster']
    match_id = replay['match_id']
    replay_salt = replay['replay_salt']
    url = f'http://replay{cluster}.valve.net/570/{match_id}_{replay_salt}.dem.bz2'
    logger.info(url)

    r = requests.head(url)
    try:
        r.raise_for_status()
    except Exception as err:
        return 'Error:' + str(err)

    return url

@app.task()
def parse(dem_path: str, remove_dem: bool = False) -> str:
    jsonlines_path = dem_path.replace('.dem', '.jsonlines')

    if not os.path.exists(jsonlines_path):
        logger.info(f'Parsing {jsonlines_path}...')
        cmd = f'curl {CLARITY_HOST}:{CLARITY_PORT} --data-binary "@{dem_path}" > {jsonlines_path}'
        subprocess.run(cmd, shell=True)
    else:
        logger.info(f'jsonlines file already exists: {jsonlines_path}...')

    if os.path.getsize(jsonlines_path) == 0:
        os.remove(jsonlines_path)
        raise ClarityParserException(
            f'Result file is empty: {jsonlines_path}...\nDid you forget to run odota/parser?')

    if os.path.exists(dem_path) and remove_dem:
        logger.info(f'Removing temporary file {dem_path}...')
        """os.remove(dem_path)"""
    return jsonlines_path


def download_parse_save(url: str) -> Any:
    res = chain(download_save.s(url), parse.s(True))()
    return res

def download_parse_save1(match_id: str) -> Any:
    path = download_save(match_id)
    res = parse(path, True)
    return res




def parse_from_file():
    urls = []
    urls_path = os.path.join(REPLAY_DIR, 'urls.txt')
    with open(urls_path, 'r') as fin:
        for line in fin.readlines():
            urls.append(line.replace('\n', ''))
    logger.info(f'Match URLs to Parse: {len(urls)}')

    for url in urls:
        download_parse_save(url)
