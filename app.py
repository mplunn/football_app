from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for
import requests
import os
import json
import time
import logging
from config import DevelopmentConfig, ProductionConfig
from flask_caching import Cache
from flask_wtf import FlaskForm
from wtforms import SelectField, SubmitField
from wtforms.validators import DataRequired
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from logging.handlers import RotatingFileHandler

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
env_config = os.getenv('APP_SETTINGS', 'config.DevelopmentConfig')
app.config.from_object(env_config)

# Secure app with Talisman
csp = {
    'default-src': [
        '\'self\'',
        'https://stackpath.bootstrapcdn.com',
        'https://code.jquery.com',
        'https://cdn.jsdelivr.net'
    ],
    'script-src': [
        '\'self\'',
        'https://stackpath.bootstrapcdn.com',
        'https://code.jquery.com',
        'https://cdn.jsdelivr.net',
        '\'unsafe-inline\''
    ],
    'style-src': [
        '\'self\'',
        'https://stackpath.bootstrapcdn.com',
        'https://code.jquery.com',
        'https://cdn.jsdelivr.net',
        '\'unsafe-inline\''
    ],
    'img-src': [
        '\'self\'',
        'https://crests.football-data.org'
    ]
}
talisman = Talisman(app, content_security_policy=csp)


# Setup Flask-Caching
cache = Cache(app, config={'CACHE_TYPE': 'simple'})

# Rate limiting to prevent abuse and DoS attacks
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"]
)

# Load API key from environment variable
API_KEY = app.config['FOOTBALL_DATA_API_KEY']
FAVORITES_FILE = 'favorites.json'

# Setup logging
if not os.path.exists('logs'):
    os.mkdir('logs')
file_handler = RotatingFileHandler(
    'logs/app.log', maxBytes=10240, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
file_handler.setLevel(app.config['LOG_LEVEL'])  # Set log level from config
app.logger.addHandler(file_handler)

app.logger.setLevel(app.config['LOG_LEVEL'])  # Set log level from config
app.logger.info('App startup')

# Function to load favorite teams from file


def load_favorites():
    app.logger.debug("Loading favorites from file")
    if os.path.exists(FAVORITES_FILE):
        with open(FAVORITES_FILE, 'r') as f:
            return json.load(f)
    return []

# Function to save favorite teams to file


def save_favorites(favorites):
    app.logger.debug("Saving favorites to file")
    with open(FAVORITES_FILE, 'w') as f:
        json.dump(favorites, f)

# Function to handle retries with exponential backoff


def get_with_retries(url, headers, max_retries=3):
    retry_delay = 1
    for attempt in range(max_retries):
        try:
            app.logger.debug(f"Attempt {attempt+1}: GET {url}")
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                app.logger.warning(
                    f"Rate limit exceeded. Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                app.logger.error(f"HTTPError: {e}")
                raise e
    raise Exception("Max retries exceeded")

# Form for league selection with input validation


class LeagueSelectForm(FlaskForm):
    league = SelectField('League', choices=[
        ('PL', 'Premier League'),
        ('SA', 'Serie A'),
        ('BL1', 'Bundesliga'),
        ('FL1', 'Ligue 1'),
        ('PD', 'La Liga'),
        ('EC', 'Euro 2024')
    ], validators=[DataRequired()])
    gameweek = SelectField('Gameweek', choices=[(
        str(i), f'Gameweek {i}') for i in range(1, 39)], validators=[DataRequired()])
    submit = SubmitField('Get Matches')


@app.route('/')
def index():
    app.logger.debug("Index page accessed")
    form = LeagueSelectForm()
    favorites = load_favorites()
    return render_template('index.html', form=form, favorites=favorites)


@cache.cached(timeout=300, query_string=True)
@app.route('/matches', methods=['POST'])
def matches():
    app.logger.debug("Matches endpoint accessed")
    form = LeagueSelectForm(request.form)
    app.logger.debug(f"Form data received: {request.form}")
    if form.validate_on_submit():
        league_code = form.league.data
        gameweek = form.gameweek.data
        app.logger.debug(
            f"League code selected: {league_code}, Gameweek selected: {gameweek}")
        url = f'https://api.football-data.org/v4/competitions/{league_code}/matches?matchday={gameweek}'
        headers = {
            'X-Auth-Token': API_KEY
        }
        matches_info = None
        error = None

        try:
            response = get_with_retries(url, headers)
            data = response.json()

            if 'matches' in data:
                matches_info = [
                    {
                        'homeTeam': match['homeTeam']['name'],
                        'homeTeamId': match['homeTeam']['id'],
                        'awayTeam': match['awayTeam']['name'],
                        'awayTeamId': match['awayTeam']['id'],
                        'utcDate': match['utcDate'],
                        'venue': match.get('venue', 'N/A'),
                        'status': match['status'],
                        'score': match['score']
                    }
                    for match in data['matches']
                ]
                app.logger.debug(f"Found {len(matches_info)} matches")
            else:
                error = "No matches found for the given league code and gameweek."
                app.logger.warning(error)
        except Exception as e:
            error = str(e)
            app.logger.error(f"Error retrieving matches: {error}")

        return render_template('index.html', form=form, matches=matches_info, error=error, favorites=load_favorites())
    else:
        app.logger.warning("Form validation failed")
        app.logger.debug(f"Form data: {request.form}")
        app.logger.debug(f"Form errors: {form.errors}")

    return render_template('index.html', form=form, favorites=load_favorites())


@app.route('/team/<int:team_id>')
def team_details(team_id):
    app.logger.debug(f"Team details accessed for team ID: {team_id}")
    url = f'https://api.football-data.org/v4/teams/{team_id}'
    headers = {
        'X-Auth-Token': API_KEY
    }
    team_info = None
    error = None

    try:
        response = get_with_retries(url, headers)
        team_info = response.json()
        app.logger.debug(f"Team info retrieved: {team_info}")
    except Exception as e:
        error = str(e)
        app.logger.error(f"Error retrieving team details: {error}")

    return render_template('team.html', team=team_info, error=error)


@app.route('/favorite', methods=['POST'])
def add_favorite():
    app.logger.debug("Adding a favorite team")
    team_id = request.form['team_id']
    team_name = request.form['team_name']
    favorites = load_favorites()
    if team_id not in [fav['id'] for fav in favorites]:
        favorites.append({'id': team_id, 'name': team_name})
        save_favorites(favorites)
        app.logger.info(f"Added favorite: {team_name} (ID: {team_id})")
    return redirect(url_for('index'))


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')


if __name__ == '__main__':
    app.run(debug=True)
