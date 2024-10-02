import os
import requests
from flask import Flask, Response, request, jsonify
from loguru import logger

from async_parser.tasks import download_parse_save
from async_parser.tasks import download_parse_save1

from async_parser.celery import app as celery_app
from dota import Match, NotParsedError
from settings import REPLAY_DIR
"""import easyocr
import io
from PIL import Image"""

app = Flask(__name__)

@app.route('/')
def index() -> str:
    return 'Send your queries to /parse'


@app.route('/retrieve/<match_id>')
def retrive(match_id: int) -> Response:
    logger.info(f'{match_id=}')
    try:
        match_id = int(match_id)
    except ValueError:
        return jsonify(dict(
            success=False,
            error='Match ID is not a number'
        )), 400

    r = requests.get(
        'https://api.opendota.com/api/matches/'+ str(match_id)
    )
    try:
        r.raise_for_status()
        if not r.json():
            raise Exception(f'Replay not found for the Match ID: {match_id}')
    except Exception as err:
        return jsonify(dict(
            success=False,
            error=str(err),
        )), 404

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
        return jsonify(dict(
            success=False,
            error=str(err),
        )), 404

    return jsonify(dict(
        success=True,
        url=url
    ))




@app.route('/parse')
def parse() -> Response:
    """
    Example: http://localhost:8000/parse?url=http://replay191.valve.net/570/6216665747_89886887.dem.bz2
    """
    dem_url = request.args.get('url')
    logger.info(f'{dem_url=}')
    if dem_url is None:
        return jsonify(dict(
            success=False,
            error='Demo URL not found'
        )), 400
    dem_url = dem_url.strip()

    async_result = download_parse_save(dem_url)
    logger.info(f'{async_result}')
    return jsonify(dict(
        success=True,
        url=dem_url,
        job_id=async_result.id
    ))

def parse1(match_id: str) -> str:
    """
    Example: http://localhost:8000/parse?url=http://replay191.valve.net/570/6216665747_89886887.dem.bz2
    """

    async_result = download_parse_save1(match_id)
    logger.info(f'{async_result}')
    return async_result


@app.route('/job/<job_id>')
def get_job(job_id: str) -> Response:
    task = celery_app.AsyncResult(job_id)
    details = task.get()
    return jsonify(details)


@app.route('/getHighlights/<match_id>')
def get_highlights(match_id: int) -> Response:
    """
    Example: http://localhost:8000/getHighlights/6216665747
    """
    logger.info(f'{match_id=}')
    try:
        match_id = int(match_id)
    except ValueError:
        return jsonify(dict(
            success=False,
            error='Match ID is not a number'
        )), 400

    try:
        match = Match.from_id(match_id)
        match.parse()
    except NotParsedError as err:
        return jsonify(dict(
            success=False,
            error=str(err)
        )), 404

    action_moments = match.get_action_moments()
    return jsonify(dict(
        success=True,
        data=action_moments,
    ))

@app.route('/getHighlights1/<match_id>')
def get_highlights1(match_id: int) -> Response:
    """
    Example: http://localhost:8000/getHighlights/6216665747
    """
    logger.info(f'{match_id=}')

    job_id = parse1(match_id)

    logger.info(f'{job_id}')

    try:
        match_id = int(match_id)
    except ValueError:
        return jsonify(dict(
            success=False,
            error='Match ID is not a number'
        )), 400

    try:
        match = Match.from_id(match_id)
        match.parse()
    except NotParsedError as err:
        return jsonify(dict(
            success=False,
            error=str(err)
        )), 404

    action_moments = match.get_action_moments()
    return jsonify(dict(
        success=True,
        data=action_moments,
    ))

@app.route('/getSinglePlayerHighlights', methods=['GET'])
def getSinglePlayerHighlights() -> Response:
    
    match_id = request.args.get('match_id')
    hero_Name = request.args.get('hero_name')

    logger.info(f'{match_id=}')
    logger.info(f'{hero_Name=}')

    job_id = parse1(match_id)

    logger.info(f'{job_id}')

    try:
        match_id = int(match_id)
    except ValueError:
        return jsonify(dict(
            success=False,
            error='Match ID is not a number'
        )), 400

    try:
        match = Match.from_id(match_id)
        match.parse()
    except NotParsedError as err:
        return jsonify(dict(
            success=False,
            error=str(err)
        )), 404

    action_moments = match.get_single_player_action_moments(hero_Name)
    return jsonify(dict(
        success=True,
        data=action_moments,
    ))

"""@app.route('/ocr', methods=['POST'])
def ocr():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    file_path = os.path.join(REPLAY_DIR, file.filename)
    file.save(file_path)

    try:
        results = reader.readtext(file_path)
        output = [{'text': result[1], 'confidence': result[2]} for result in results]
        return jsonify(output)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)"""


