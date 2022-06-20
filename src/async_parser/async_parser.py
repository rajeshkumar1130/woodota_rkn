import os
import subprocess
from bz2 import decompress

import requests
from celery import chain
from loguru import logger

from .celery import app


REPLAY_DIR = os.path.join('..', 'replays')


def download(url):
    r = requests.get(url)
    logger.info(f'Downloading: {url}...')
    r.raise_for_status()
    compressed_dem = r.content
    logger.info(f'Decompressing: {url}...')
    dem = decompress(compressed_dem)
    return dem


@app.task()
def download_save(url):
    right = url.split('/')[-1]
    match_salt = right.replace('dem.bz2', '')
    file_name = match_salt.split('_')[0]
    file_name += '.dem'
    
    dem = download(url)
    path = os.path.join(REPLAY_DIR, file_name)
    with open(path, 'wb') as fout:
        fout.write(dem)
    logger.info(f'Saved to {path}...')
    return path


@app.task()
def parse(dem_path, remove_dem=False):
    jsonlines_path = dem_path.replace('.dem', '.jsonlines')
    logger.info(f'Parsing {jsonlines_path}...')
    cmd = f'curl localhost:5600 --data-binary "@{dem_path}" > {jsonlines_path}'
    subprocess.run(cmd, shell=True)
    
    if os.path.exists(dem_path) and remove_dem:
        logger.info(f'Removing temporary file {dem_path}...')
        os.remove(dem_path)
    return jsonlines_path


def download_parse_save(url):
    res = chain(download_save.s(url), parse.s(True))()
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
